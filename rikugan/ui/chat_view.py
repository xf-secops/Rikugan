"""Chat view: scrollable area containing message widgets."""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from .qt_compat import (
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy, QTimer, Qt, Signal,
)
from .message_widgets import (
    AssistantMessageWidget, ErrorMessageWidget, ExplorationFindingWidget,
    ExplorationPhaseWidget, QueuedMessageWidget,
    ThinkingWidget, ToolApprovalWidget, ToolBatchWidget, ToolCallWidget,
    ToolGroupWidget, UserMessageWidget, UserQuestionWidget,
)
from ..agent.turn import TurnEvent, TurnEventType
from ..core.types import Message, Role
from .plan_view import PlanView

# Max tool previews shown per turn before hiding further previews.
_MAX_TOOL_PREVIEWS = 3


class ChatView(QScrollArea):
    """Scrollable chat area that renders TurnEvents into widgets."""

    tool_approval_submitted = Signal(str, str)  # (tool_call_id, "allow"/"deny")

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("chat_scroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container.setObjectName("chat_container")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        self.setWidget(self._container)

        # Track current assistant widget for streaming
        self._current_assistant: Optional[AssistantMessageWidget] = None
        self._tool_widgets: Dict[str, ToolCallWidget] = {}
        self._thinking: Optional[ThinkingWidget] = None
        self._thinking_shown_at: float = 0.0
        self._plan_view: Optional[PlanView] = None

        # --- Tool batching state ---
        self._current_batch: Optional[ToolBatchWidget] = None
        self._current_batch_name: str = ""
        # Map tool_call_id -> batch widget it belongs to
        self._batch_map: Dict[str, ToolBatchWidget] = {}
        # Preview budget: how many tool previews left in this turn
        self._preview_budget: int = _MAX_TOOL_PREVIEWS
        # Collapsible group for overflow tool calls
        self._tool_group: Optional[ToolGroupWidget] = None
        # Map tool_call_id -> group it belongs to (for result routing)
        self._group_map: Dict[str, ToolGroupWidget] = {}

        # Member timer for scroll-to-bottom
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._do_scroll)

        # Timer for minimum thinking display duration (500ms)
        self._thinking_hide_timer = QTimer(self)
        self._thinking_hide_timer.setSingleShot(True)
        self._thinking_hide_timer.timeout.connect(self._force_hide_thinking)

    def add_user_message(self, text: str) -> None:
        widget = UserMessageWidget(text)
        self._insert_widget(widget)
        self._current_assistant = None

    def add_error_message(self, text: str) -> None:
        self._insert_widget(ErrorMessageWidget(text))
        self._scroll_to_bottom()

    def add_queued_message(self, text: str) -> None:
        self._insert_widget(QueuedMessageWidget(text))
        self._scroll_to_bottom()

    def remove_queued_messages(self) -> None:
        """Remove all [queued] message widgets (e.g. on cancel)."""
        for i in reversed(range(self._layout.count())):
            item = self._layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, QueuedMessageWidget):
                self._layout.removeWidget(widget)
                widget.deleteLater()

    def pop_first_queued_message(self) -> None:
        """Remove the first [queued] widget (when it gets submitted)."""
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, QueuedMessageWidget):
                self._layout.removeWidget(widget)
                widget.deleteLater()
                return

    def _show_thinking(self) -> None:
        if self._thinking is not None:
            return
        self._thinking = ThinkingWidget()
        self._thinking_shown_at = time.monotonic()
        self._insert_widget(self._thinking)
        self._scroll_to_bottom()

    def _hide_thinking(self) -> None:
        if self._thinking is None:
            return
        elapsed_ms = (time.monotonic() - self._thinking_shown_at) * 1000
        if elapsed_ms < 500:
            remaining = int(500 - elapsed_ms)
            self._thinking_hide_timer.start(remaining)
            return
        self._force_hide_thinking()

    def _force_hide_thinking(self) -> None:
        if self._thinking is None:
            return
        self._thinking.stop()
        self._layout.removeWidget(self._thinking)
        self._thinking.deleteLater()
        self._thinking = None

    # --- Tool batching ---

    def _flush_batch(self) -> None:
        """End current batch. Called when a non-matching event arrives."""
        self._current_batch = None
        self._current_batch_name = ""

    def _flush_tool_group(self) -> None:
        """End the current tool group (called on turn end or non-tool event)."""
        self._tool_group = None

    def handle_event(self, event: TurnEvent) -> None:
        """Process a TurnEvent and update the UI accordingly."""
        etype = event.type

        if etype == TurnEventType.TEXT_DELTA:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            if self._current_assistant is None:
                self._current_assistant = AssistantMessageWidget()
                self._insert_widget(self._current_assistant)
            self._current_assistant.append_text(event.text)
            self._scroll_to_bottom()

        elif etype == TurnEventType.TEXT_DONE:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            if self._current_assistant is not None:
                self._current_assistant.set_text(event.text)
            self._current_assistant = None

        elif etype == TurnEventType.TOOL_CALL_START:
            self._hide_thinking()
            tool_name = event.tool_name
            tool_id = event.tool_call_id

            if tool_name == self._current_batch_name and self._current_batch is not None:
                # Same tool as current batch — merge into it
                self._current_batch.add_call(tool_id)
                self._batch_map[tool_id] = self._current_batch
            else:
                # Different tool or no batch — flush and start new
                self._flush_batch()

                tw = ToolCallWidget(tool_name, tool_id)
                self._tool_widgets[tool_id] = tw
                self._current_batch_name = tool_name

                if self._preview_budget > 0:
                    # Within budget — show directly in chat
                    self._preview_budget -= 1
                    self._insert_widget(tw)
                else:
                    # Over budget — add to collapsible group
                    tw.hide_preview()
                    if self._tool_group is None:
                        self._tool_group = ToolGroupWidget()
                        self._insert_widget(self._tool_group)
                    self._tool_group.add_widget(tw)
                    self._group_map[tool_id] = self._tool_group

            self._scroll_to_bottom()

        elif etype == TurnEventType.TOOL_CALL_ARGS_DELTA:
            batch = self._batch_map.get(event.tool_call_id)
            if batch:
                pass  # Batched calls don't stream args
            else:
                tw = self._tool_widgets.get(event.tool_call_id)
                if tw:
                    tw.append_args_delta(event.tool_args)

        elif etype == TurnEventType.TOOL_CALL_DONE:
            batch = self._batch_map.get(event.tool_call_id)
            if batch:
                batch.set_args_for_call(event.tool_call_id, event.tool_args)
            else:
                tw = self._tool_widgets.get(event.tool_call_id)
                if tw:
                    tw.set_arguments(event.tool_args)

                    # Check if we should upgrade this to a batch for next call
                    # (handled implicitly by _current_batch_name tracking)

        elif etype == TurnEventType.TOOL_RESULT:
            batch = self._batch_map.get(event.tool_call_id)
            if batch:
                batch.set_result_for_call(
                    event.tool_call_id, event.tool_result, event.tool_is_error
                )
            else:
                tw = self._tool_widgets.get(event.tool_call_id)
                if tw:
                    tw.set_result(event.tool_result, event.tool_is_error)
            # Notify group if this tool belongs to one
            group = self._group_map.get(event.tool_call_id)
            if group:
                group.notify_result(event.tool_is_error)
            self._scroll_to_bottom()

        elif etype == TurnEventType.TURN_START:
            self._current_assistant = None
            self._flush_batch()
            self._flush_tool_group()
            self._group_map.clear()
            self._preview_budget = _MAX_TOOL_PREVIEWS  # Reset budget per turn
            self._show_thinking()
            self._scroll_to_bottom()

        elif etype == TurnEventType.TURN_END:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            self._current_assistant = None

        elif etype == TurnEventType.ERROR:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            self._insert_widget(ErrorMessageWidget(event.error or "Unknown error"))
            self._scroll_to_bottom()

        elif etype == TurnEventType.USER_QUESTION:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            options = event.metadata.get("options", [])
            self._insert_widget(UserQuestionWidget(event.text, options))
            self._scroll_to_bottom()

        elif etype == TurnEventType.PLAN_GENERATED:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            self._plan_view = PlanView()
            if event.plan_steps:
                self._plan_view.set_plan(event.plan_steps)
            self._insert_widget(self._plan_view)
            self._scroll_to_bottom()

        elif etype == TurnEventType.PLAN_STEP_START:
            if self._plan_view:
                self._plan_view.set_step_status(event.plan_step_index, "active")
                self._plan_view.set_buttons_visible(False)
            self._scroll_to_bottom()

        elif etype == TurnEventType.PLAN_STEP_DONE:
            if self._plan_view:
                self._plan_view.set_step_status(event.plan_step_index, "done")
            self._scroll_to_bottom()

        elif etype == TurnEventType.TOOL_APPROVAL_REQUEST:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            widget = ToolApprovalWidget(
                event.tool_call_id, event.tool_name,
                event.tool_args, event.text,
            )
            widget.approved.connect(self._on_tool_approval)
            self._insert_widget(widget)
            self._scroll_to_bottom()

        elif etype == TurnEventType.EXPLORATION_PHASE_CHANGE:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            meta = event.metadata
            self._insert_widget(ExplorationPhaseWidget(
                meta.get("from_phase", ""),
                meta.get("to_phase", ""),
                event.text,
            ))
            self._scroll_to_bottom()

        elif etype == TurnEventType.EXPLORATION_FINDING:
            meta = event.metadata
            self._insert_widget(ExplorationFindingWidget(
                meta.get("category", "general"),
                event.text,
                meta.get("address"),
                meta.get("relevance", "medium"),
            ))
            self._scroll_to_bottom()

        elif etype == TurnEventType.SAVE_APPROVAL_REQUEST:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            # Rendered as a user question with save options
            options = ["Save All", "Discard All"]
            self._insert_widget(UserQuestionWidget(event.text, options))
            self._scroll_to_bottom()

        elif etype == TurnEventType.CANCELLED:
            self._hide_thinking()
            self._flush_batch()
            self._flush_tool_group()
            self._insert_widget(ErrorMessageWidget("Cancelled by user"))
            self._scroll_to_bottom()

    def _on_tool_approval(self, tool_call_id: str, decision: str) -> None:
        """Forward tool approval decision to the panel/controller."""
        self.tool_approval_submitted.emit(tool_call_id, decision)

    def restore_from_messages(self, messages: List[Message]) -> None:
        """Replay saved Message objects into the chat view."""
        self.clear_chat()

        # For batching during restore
        current_batch_name = ""
        current_batch: Optional[ToolBatchWidget] = None
        tool_widgets_restore: Dict[str, ToolCallWidget] = {}
        batch_map_restore: Dict[str, ToolBatchWidget] = {}

        for msg in messages:
            if msg.role == Role.USER:
                current_batch_name = ""
                current_batch = None
                self.add_user_message(msg.content)

            elif msg.role == Role.ASSISTANT:
                current_batch_name = ""
                current_batch = None
                if msg.content:
                    w = AssistantMessageWidget()
                    w.set_text(msg.content)
                    self._insert_widget(w)

                # Group consecutive same-name tool calls
                for tc in msg.tool_calls:
                    if tc.name == current_batch_name and current_batch is not None:
                        # Add to existing batch
                        try:
                            args_str = json.dumps(tc.arguments, indent=2)
                        except Exception:
                            args_str = str(tc.arguments)
                        current_batch.add_call(tc.id, args_str)
                        batch_map_restore[tc.id] = current_batch
                    elif tc.name == current_batch_name and current_batch is None:
                        # Second call of same name — upgrade previous to batch
                        pass  # Handled by batch creation below
                    else:
                        # New tool name
                        current_batch_name = tc.name
                        current_batch = None

                        tw = ToolCallWidget(tc.name, tc.id)
                        try:
                            args_str = json.dumps(tc.arguments, indent=2)
                        except Exception:
                            args_str = str(tc.arguments)
                        tw.set_arguments(args_str)
                        tw.mark_done()
                        tool_widgets_restore[tc.id] = tw
                        self._tool_widgets[tc.id] = tw
                        self._insert_widget(tw)

            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    batch = batch_map_restore.get(tr.tool_call_id)
                    if batch:
                        batch.set_result_for_call(tr.tool_call_id, tr.content, tr.is_error)
                    else:
                        tw = self._tool_widgets.get(tr.tool_call_id)
                        if tw:
                            tw.set_result(tr.content, tr.is_error)

        self._current_assistant = None
        self._scroll_to_bottom()

    def clear_chat(self) -> None:
        self._force_hide_thinking()
        self._thinking_hide_timer.stop()
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._current_assistant = None
        self._tool_widgets.clear()
        self._plan_view = None
        self._flush_batch()
        self._batch_map.clear()
        self._flush_tool_group()
        self._group_map.clear()
        self._preview_budget = _MAX_TOOL_PREVIEWS

    def _insert_widget(self, widget: QWidget) -> None:
        """Insert before the stretch at the end."""
        idx = self._layout.count() - 1
        self._layout.insertWidget(idx, widget)

    def _scroll_to_bottom(self) -> None:
        self._scroll_timer.start()

    def _do_scroll(self) -> None:
        self._container.adjustSize()
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def shutdown(self) -> None:
        self._scroll_timer.stop()
        self._thinking_hide_timer.stop()
        self._force_hide_thinking()
