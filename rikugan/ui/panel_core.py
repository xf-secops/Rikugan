"""Shared Rikugan panel widget used by host-specific wrappers."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable, Dict, Optional

from .qt_compat import (
    QVBoxLayout, QHBoxLayout, QSplitter, QWidget, QPushButton, QTimer,
    QTabWidget, QTabBar, QToolButton, Signal, QFileDialog, QMenu, QMessageBox, Qt,
)
from .styles import DARK_THEME
from .chat_view import ChatView
from .input_area import InputArea
from .context_bar import ContextBar
from .mutation_log_view import MutationLogPanel
from .tool_widgets import _SharedSpinnerTimer
from .settings_dialog import SettingsDialog, _resolve_auth_cached
from ..core.config import RikuganConfig
from ..core.logging import log_error, log_info, log_debug
from ..agent.turn import TurnEvent, TurnEventType
from ..agent.mutation import MutationRecord
from ..core.types import Role

_TOOL_RESULT_TRUNCATE_CHARS = 2000
_SMALL_BTN_STYLE = (
    "QPushButton { background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; "
    "border-radius: 6px; padding: 4px; font-size: 11px; }"
    "QPushButton:hover { background: #3c3c3c; }"
)
_CANCEL_BTN_STYLE = (
    "QPushButton { background: #2d2d2d; color: #c42b1c; border: 1px solid #3c3c3c; "
    "border-radius: 6px; padding: 4px; font-size: 11px; }"
    "QPushButton:hover { background: #3c3c3c; }"
)

_TOOL_LANG_MAP = {
    "execute_python": "python",
    "decompile_function": "c",
    "get_il": "c",
    "declare_c_type": "c",
    "define_types": "c",
    "set_function_prototype": "c",
    "fetch_disassembly": "x86asm",
}


def _export_detect_lang(text: str, tool_name: str = "", arg_key: str = "") -> str:
    """Detect markdown language hint from content heuristics and tool/arg context."""
    if arg_key in ("code", "python"):
        return "python"
    if arg_key in ("c_code", "c_declaration", "prototype"):
        return "c"
    if tool_name in _TOOL_LANG_MAP:
        return _TOOL_LANG_MAP[tool_name]

    sample = text[:_TOOL_RESULT_TRUNCATE_CHARS]
    if re.search(r"^[0-9a-fA-F]{8,16}\s+([0-9a-fA-F]{2}\s+){4,}", sample, re.M):
        return "text"

    asm_pat = r"(?:mov|lea|push|pop|call|ret|jmp|je|jne|jz|jnz|cmp|test|xor|add|sub|nop|int)\s"
    if re.search(asm_pat, sample, re.I) and re.search(r"0x[0-9a-fA-F]+", sample):
        return "x86asm"

    c_indicators = 0
    if re.search(r"\b(void|int|char|uint\d+_t|int\d+_t|struct|enum|typedef)\b", sample):
        c_indicators += 1
    if re.search(r"[{};]", sample):
        c_indicators += 1
    if re.search(r"\b(if|while|for|return|switch)\s*\(", sample):
        c_indicators += 1
    if c_indicators >= 2:
        return "c"

    if re.search(r"^(def |class |import |from .+ import |print\()", sample, re.M):
        return "python"

    return ""


def _export_format_tool_args(tc) -> str:
    """Format tool call arguments as markdown with per-argument code blocks."""
    parts = []
    for k, v in tc.arguments.items():
        if isinstance(v, str) and ("\n" in v or len(v) > 80):
            lang = _export_detect_lang(v, tc.name, k)
            parts.append(f"  - `{k}`:\n\n```{lang}\n{v}\n```\n")
        else:
            parts.append(f"  - `{k}`: `{v!r}`")
    return "\n".join(parts)


def _export_format_tool_result(tr) -> str:
    """Format tool result content as a markdown code block."""
    content = tr.content
    if len(content) > _TOOL_RESULT_TRUNCATE_CHARS:
        content = content[:_TOOL_RESULT_TRUNCATE_CHARS] + "\n... (truncated)"
    lang = _export_detect_lang(content, tr.name)
    return f"```{lang}\n{content}\n```"


class _AddButtonTabBar(QTabBar):
    """Tab bar with an integrated '+' button positioned after the last tab."""

    add_tab_requested = Signal()
    export_tab_requested = Signal(int)
    fork_tab_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._add_btn = QToolButton(self)
        self._add_btn.setText("+")
        self._add_btn.setAutoRaise(True)
        self._add_btn.setFixedSize(20, 20)
        self._add_btn.setStyleSheet(
            "QToolButton { color: #d4d4d4; font-size: 14px; font-weight: bold; "
            "border: none; background: transparent; }"
            "QToolButton:hover { background: #3c3c3c; border-radius: 3px; }"
        )
        self._add_btn.clicked.connect(self.add_tab_requested)

    def _show_context_menu(self, pos):
        index = self.tabAt(pos)
        if index < 0:
            return
        menu = QMenu(self)
        export_action = menu.addAction("Export Chat")
        fork_action = menu.addAction("Fork Session")
        action = menu.exec_(self.mapToGlobal(pos))
        if action == export_action:
            self.export_tab_requested.emit(index)
        elif action == fork_action:
            self.fork_tab_requested.emit(index)

    def tabInserted(self, index):
        super().tabInserted(index)
        self._reposition()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self._reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self):
        count = self.count()
        if count > 0:
            rect = self.tabRect(count - 1)
            y = (self.height() - self._add_btn.height()) // 2
            self._add_btn.move(rect.right() + 2, max(0, y))
        else:
            self._add_btn.move(0, 0)


class RikuganPanelCore(QWidget):
    """Host-agnostic chat panel widget."""

    def __init__(
        self,
        controller_factory: Callable[[RikuganConfig], Any],
        ui_hooks_factory: Optional[Callable[[Callable[[], Any]], Any]] = None,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self._config = RikuganConfig.load_or_create()
        log_debug(
            f"Config loaded: provider={self._config.provider.name} "
            f"model={self._config.provider.model}",
        )
        self._ctrl = controller_factory(self._config)
        self._poll_timer: Optional[QTimer] = None
        self._polling = False
        self._pending_answer = False
        self._is_shutdown = False
        self._ui_hooks_factory = ui_hooks_factory
        self._ui_hooks = None

        # Tab-to-ChatView mapping
        self._chat_views: Dict[str, ChatView] = {}
        self._context_bar: Optional[ContextBar] = None
        self._mutation_panel: Optional[MutationLogPanel] = None
        self._skills_refresh_timer: Optional[QTimer] = None

        def _warm_oauth() -> None:
            try:
                _resolve_auth_cached()
            except Exception as e:
                log_debug(f"OAuth warm-up failed: {e}")

        threading.Thread(target=_warm_oauth, daemon=True).start()
        self._build_ui()

    def _ensure_skills_refresh_timer(self) -> None:
        """Refresh skill autocomplete once background discovery completes."""
        if self._skills_refresh_timer is not None:
            return
        self._skills_refresh_timer = QTimer(self)
        self._skills_refresh_timer.setInterval(300)
        self._skills_refresh_timer.timeout.connect(self._refresh_skill_slugs)
        self._skills_refresh_timer.start()

    def _stop_skills_refresh_timer(self) -> None:
        if self._skills_refresh_timer is None:
            return
        self._skills_refresh_timer.stop()
        try:
            self._skills_refresh_timer.timeout.disconnect(self._refresh_skill_slugs)
        except (RuntimeError, TypeError) as e:
            log_debug(f"skills refresh timer disconnect failed: {e}")
        self._skills_refresh_timer.deleteLater()
        self._skills_refresh_timer = None

    def _refresh_skill_slugs(self) -> None:
        if self._is_shutdown:
            self._stop_skills_refresh_timer()
            return
        slugs = self._ctrl.skill_slugs
        if slugs:
            self._input_area.set_skill_slugs(slugs)
            self._stop_skills_refresh_timer()
            return
        if getattr(self._ctrl, "runtime_ready", False):
            # Runtime init completed but no skills found; stop polling.
            self._stop_skills_refresh_timer()

    def _build_ui(self) -> None:
        self.setStyleSheet(DARK_THEME)
        self.setObjectName("rikugan_panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._build_tab_widget()
        self._build_main_splitter(layout)
        self._create_tab(self._ctrl.active_tab_id, "New Chat")
        layout.addWidget(self._build_input_section())

        self._context_bar = ContextBar()
        self._context_bar.set_model(self._config.provider.model)
        layout.addWidget(self._context_bar)

        if self._ui_hooks_factory is not None:
            try:
                self._ui_hooks = self._ui_hooks_factory(lambda: self)
                self._ui_hooks.hook()
            except Exception as e:
                log_debug(f"UI hook setup failed: {e}")
                self._ui_hooks = None

        self._try_restore_session()

    def _build_tab_widget(self) -> None:
        """Create the tab widget with custom tab bar."""
        self._tab_widget = QTabWidget()
        self._tab_bar = _AddButtonTabBar()
        self._tab_widget.setTabBar(self._tab_bar)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.tabCloseRequested.connect(self._on_close_tab)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.add_tab_requested.connect(self._on_new_tab)
        self._tab_bar.export_tab_requested.connect(self._on_export_tab)
        self._tab_bar.fork_tab_requested.connect(self._on_fork_tab)
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane { border: none; }"
            "QTabBar { background: #1e1e1e; border: none; }"
            "QTabBar::tab { background: #252526; color: #cccccc; padding: 2px 8px; "
            "border: none; border-right: 1px solid #3c3c3c; "
            "font-size: 11px; max-width: 140px; }"
            "QTabBar::tab:selected { background: #1e1e1e; color: #ffffff; }"
            "QTabBar::tab:hover { background: #2d2d2d; }"
            "QTabBar::close-button { image: none; border: none; padding: 1px; }"
            "QTabBar::close-button:hover { background: #c42b1c; border-radius: 2px; }"
        )
        self._tab_bar.setExpanding(False)
        self._tab_bar.setVisible(False)  # hidden until 2+ tabs

    def _build_main_splitter(self, layout: QVBoxLayout) -> None:
        """Create the horizontal splitter (chat | mutation log) and add to layout."""
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setHandleWidth(1)
        self._main_splitter.setStyleSheet("QSplitter::handle { background: #3c3c3c; }")
        self._main_splitter.addWidget(self._tab_widget)

        self._mutation_panel = MutationLogPanel()
        self._mutation_panel.undo_requested.connect(self._on_undo_requested)
        self._mutation_panel.setVisible(False)
        self._main_splitter.addWidget(self._mutation_panel)
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 1)

        layout.addWidget(self._main_splitter, 1)

    def _build_input_section(self) -> QWidget:
        """Build the bottom input area with text field and action buttons."""
        self._input_container = QWidget()
        input_layout = QHBoxLayout(self._input_container)
        input_layout.setContentsMargins(8, 4, 8, 4)

        self._input_area = InputArea()
        self._input_area.set_submit_callback(self._on_submit)
        self._input_area.set_cancel_callback(self._on_cancel)
        self._input_area.set_skill_slugs(self._ctrl.skill_slugs)
        self._ensure_skills_refresh_timer()
        input_layout.addWidget(self._input_area, 1)
        input_layout.addLayout(self._build_action_buttons())
        return self._input_container

    def _build_action_buttons(self) -> QVBoxLayout:
        """Build the vertical stack of action buttons (Send, Stop, New, etc.)."""
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("send_button")
        self._send_btn.setFixedWidth(64)
        self._send_btn.setStyleSheet(_SMALL_BTN_STYLE)
        self._send_btn.clicked.connect(self._on_send_clicked)
        btn_layout.addWidget(self._send_btn)
        self._cancel_btn = QPushButton("Stop")
        self._cancel_btn.setObjectName("cancel_button")
        self._cancel_btn.setFixedWidth(64)
        self._cancel_btn.setStyleSheet(_CANCEL_BTN_STYLE)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)
        self._new_btn = QPushButton("New")
        self._new_btn.setFixedWidth(64)
        self._new_btn.setStyleSheet(_SMALL_BTN_STYLE)
        self._new_btn.clicked.connect(self._on_new_tab)
        btn_layout.addWidget(self._new_btn)
        self._export_btn = QPushButton("Export")
        self._export_btn.setFixedWidth(64)
        self._export_btn.setStyleSheet(_SMALL_BTN_STYLE)
        self._export_btn.clicked.connect(self._on_export_current)
        btn_layout.addWidget(self._export_btn)
        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setFixedWidth(64)
        self._settings_btn.setStyleSheet(_SMALL_BTN_STYLE)
        self._settings_btn.clicked.connect(self._on_settings)
        btn_layout.addWidget(self._settings_btn)
        self._mutations_btn = QPushButton("Mutations")
        self._mutations_btn.setFixedWidth(64)
        self._mutations_btn.setStyleSheet(_SMALL_BTN_STYLE)
        self._mutations_btn.setCheckable(True)
        self._mutations_btn.clicked.connect(self._on_toggle_mutation_log)
        self._mutations_btn.setVisible(False)  # shown when first mutation is recorded
        btn_layout.addWidget(self._mutations_btn)

        btn_layout.addStretch()
        return btn_layout

    # --- Tab management ---

    def _update_tab_bar_visibility(self) -> None:
        """Show the tab bar only when there are 2+ tabs."""
        self._tab_bar.setVisible(self._tab_widget.count() > 1)

    def _create_tab(self, tab_id: str, label: str) -> ChatView:
        """Create a new ChatView and add it as a tab."""
        chat_view = ChatView()
        chat_view.setProperty("tab_id", tab_id)  # O(1) lookup in _tab_id_at_index
        chat_view.tool_approval_submitted.connect(self._on_tool_approval)
        chat_view.user_answer_submitted.connect(self._on_user_answer_submitted)
        self._chat_views[tab_id] = chat_view
        index = self._tab_widget.addTab(chat_view, label)
        self._tab_widget.setCurrentIndex(index)
        self._update_tab_bar_visibility()
        return chat_view

    def _on_new_tab(self) -> None:
        """Create a new chat tab, with optional context clearing."""
        if self._is_shutdown:
            return
        session = self._ctrl.session
        has_messages = session and session.messages
        if has_messages:
            ctx_window = self._config.provider.context_window or 200000
            used = session.last_prompt_tokens if session.last_prompt_tokens is not None else session.total_usage.total_tokens
            pct = min(int(used * 100 / ctx_window), 100) if ctx_window > 0 else 0
            result = self._show_new_chat_dialog(pct)
            if result == "no":
                return
            if result == "clear":
                # Clear current tab instead of creating a new one
                self._ctrl.new_chat()
                chat_view = self._active_chat_view()
                if chat_view:
                    chat_view.clear_chat()
                self._update_token_display(0)
                self._update_tab_label(self._ctrl.active_tab_id)
                return
            # "yes" — fall through to create a new tab
        tab_id = self._ctrl.create_tab()
        self._create_tab(tab_id, "New Chat")
        self._ctrl.switch_tab(tab_id)

    def _on_fork_tab(self, index: int) -> None:
        """Fork (duplicate) a session into a new tab."""
        source_tab_id = self._tab_id_at_index(index)
        if source_tab_id is None:
            return
        new_tab_id = self._ctrl.fork_session(source_tab_id)
        if new_tab_id is None:
            return
        label = self._ctrl.tab_label(new_tab_id)
        chat_view = self._create_tab(new_tab_id, f"{label} (fork)")
        # Restore messages into the forked chat view
        source_session = self._ctrl._sessions.get(new_tab_id)
        if source_session and source_session.messages:
            chat_view.restore_from_messages(source_session.messages)
        self._ctrl.switch_tab(new_tab_id)
        log_info(f"Forked tab {source_tab_id} → {new_tab_id}")

    def _on_close_tab(self, index: int) -> None:
        """Close a tab. Prevents closing the last tab."""
        if self._tab_widget.count() <= 1:
            return  # Don't close the last tab
        tab_id = self._tab_id_at_index(index)
        if tab_id is None:
            return
        self._ctrl.close_tab(tab_id)
        chat_view = self._chat_views.pop(tab_id, None)
        self._tab_widget.removeTab(index)
        if chat_view:
            chat_view.shutdown()
            chat_view.deleteLater()
        self._update_tab_bar_visibility()

    def _on_export_tab(self, index: int) -> None:
        """Export a tab's chat to a Markdown file."""
        tab_id = self._tab_id_at_index(index)
        if tab_id is None:
            return
        session = self._ctrl._sessions.get(tab_id)
        if session is None or not session.messages:
            return
        label = self._ctrl.tab_label(tab_id).replace("/", "-").replace("\\", "-")
        default_name = f"rikugan-{label}-{time.strftime('%Y%m%d-%H%M%S')}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Chat", default_name,
            "Markdown (*.md);;Text (*.txt);;All Files (*)",
        )
        if not path:
            return
        try:
            self._export_session_to_file(session, path)
            log_info(f"Exported chat to {path}")
        except Exception as e:
            log_error(f"Failed to export chat: {e}")

    @staticmethod
    def _export_session_to_file(session, path: str) -> None:
        """Write session messages to a Markdown file."""
        lines = ["# Rikugan Chat Export\n"]
        lines.append(f"- **Model**: {session.model_name or 'unknown'}")
        lines.append(f"- **Exported**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        if session.idb_path:
            lines.append(f"- **File**: `{os.path.basename(session.idb_path)}`")
        lines.append("")
        lines.append("---\n")
        for msg in session.messages:
            if msg.role == Role.USER:
                lines.append(f"## You\n\n{msg.content}\n")
            elif msg.role == Role.ASSISTANT:
                if msg.content:
                    lines.append(f"## Rikugan\n\n{msg.content}\n")
                for tc in msg.tool_calls:
                    lines.append(f"**Tool call**: `{tc.name}`\n")
                    lines.append(_export_format_tool_args(tc))
                    lines.append("")
            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    status = "Error" if tr.is_error else "Result"
                    lines.append(f"**{status}** (`{tr.name}`):\n")
                    lines.append(_export_format_tool_result(tr))
                    lines.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _on_export_current(self) -> None:
        """Export the currently active tab's chat."""
        index = self._tab_widget.currentIndex()
        if index >= 0:
            self._on_export_tab(index)

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab switch."""
        if index < 0 or self._is_shutdown:
            return
        tab_id = self._tab_id_at_index(index)
        if tab_id is None:
            return
        self._ctrl.switch_tab(tab_id)
        self._update_token_display()

    def _tab_id_at_index(self, index: int) -> Optional[str]:
        """Find the tab_id for a given tab index via the stored property (O(1))."""
        widget = self._tab_widget.widget(index)
        if widget is None:
            return None
        tid = widget.property("tab_id")
        if tid and tid in self._chat_views:
            return tid
        # Fallback for tabs created before property was set
        for tid, cv in self._chat_views.items():
            if cv is widget:
                return tid
        return None

    def _active_chat_view(self) -> Optional[ChatView]:
        """Return the ChatView for the currently active tab."""
        return self._chat_views.get(self._ctrl.active_tab_id)

    def _update_token_display(self, token_count: Optional[int] = None) -> None:
        """Update the context bar token display with context window percentage."""
        if self._context_bar is None:
            return
        if token_count is None:
            session = self._ctrl.session
            # Show current context size (last prompt), not cumulative total
            token_count = session.last_prompt_tokens if session.last_prompt_tokens is not None else session.total_usage.total_tokens
        ctx_window = self._config.provider.context_window or 0
        self._context_bar.set_tokens(token_count, ctx_window)

    def _update_tab_label(self, tab_id: str) -> None:
        """Update tab label from the first user message."""
        label = self._ctrl.tab_label(tab_id)
        cv = self._chat_views.get(tab_id)
        if cv is None:
            return
        for i in range(self._tab_widget.count()):
            if self._tab_widget.widget(i) is cv:
                self._tab_widget.setTabText(i, label)
                break

    # --- Public API ---

    def prefill_input(self, text: str, auto_submit: bool = False) -> None:
        self._input_area.setPlainText(text)
        if auto_submit:
            self._input_area.clear()
            self._on_submit(text)
        else:
            self._input_area.setFocus()

    def shutdown(self) -> None:
        if self._is_shutdown:
            return
        self._is_shutdown = True
        try:
            self._stop_poll_timer()
            self._stop_skills_refresh_timer()
            _SharedSpinnerTimer.shutdown()
            if self._context_bar:
                self._context_bar.stop()
            for cv in self._chat_views.values():
                cv.shutdown()
            if self._ui_hooks:
                self._ui_hooks.unhook()
                self._ui_hooks = None
            self._ctrl.shutdown()
        except Exception as e:
            log_error(f"Panel teardown error: {e}")

    def on_database_changed(self, new_path: str) -> None:
        """Called when the user opens a different file."""
        normalized = os.path.normcase(os.path.realpath(os.path.abspath(new_path))) if new_path else ""
        if normalized == self._ctrl._idb_path:
            return
        self._ctrl.reset_for_new_file(normalized)
        # Remove all existing tabs
        for cv in self._chat_views.values():
            cv.shutdown()
        while self._tab_widget.count():
            w = self._tab_widget.widget(0)
            self._tab_widget.removeTab(0)
            if w:
                w.deleteLater()
        self._chat_views.clear()
        # Create default tab and try to restore saved sessions
        self._create_tab(self._ctrl.active_tab_id, "New Chat")
        self._try_restore_session()

    def _on_submit(self, text: str) -> None:
        if not text or self._is_shutdown:
            return
        chat_view = self._active_chat_view()
        if chat_view is None:
            return
        if self._pending_answer:
            self._pending_answer = False
            chat_view.add_user_message(text)
            self._set_running(True)
            runner = self._ctrl.get_runner()
            if runner:
                runner.agent_loop.submit_user_answer(text)
            return
        # Queue while the agent is actively running.
        if self._ctrl.is_agent_running:
            self._ctrl.queue_message(text)
            chat_view.add_queued_message(text)
            return
        self._start_agent(text)

    def _on_send_clicked(self) -> None:
        text = self._input_area.toPlainText().strip()
        if text:
            self._input_area.clear()
            self._on_submit(text)

    def _on_cancel(self) -> None:
        if self._is_shutdown:
            return
        self._ctrl.cancel()
        # Remove [queued] widgets from the active chat view
        chat_view = self._active_chat_view()
        if chat_view is not None:
            chat_view.remove_queued_messages()

    def _on_settings(self) -> None:
        try:
            dlg = SettingsDialog(self._config, registry=self._ctrl.provider_registry)
            result = dlg.exec_()
            if result:
                self._config.save()
                self._ctrl.update_settings()
                self._context_bar.set_model(self._config.provider.model)
                log_info(f"Settings updated: {self._config.provider.name}/{self._config.provider.model}")
            dlg.setParent(None)
        except Exception as e:
            log_error(f"Settings dialog error: {e}")

    def _show_new_chat_dialog(self, context_pct: int) -> str:
        """Show a confirmation dialog with context usage. Returns 'yes', 'clear', or 'no'."""
        dlg = QMessageBox(self)
        dlg.setWindowTitle("New Chat")
        dlg.setText("Start a new chat? Current conversation will be saved.")
        dlg.setInformativeText(f"Context usage: {context_pct}%")
        dlg.setStyleSheet(
            "QMessageBox { background: #1e1e1e; color: #d4d4d4; }"
            "QLabel { color: #d4d4d4; font-size: 12px; }"
            "QPushButton { background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "border-radius: 4px; padding: 6px 16px; font-size: 11px; min-width: 80px; }"
            "QPushButton:hover { background: #3c3c3c; }"
        )
        yes_btn = dlg.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        clear_btn = dlg.addButton(
            f"Yes, clear context ({context_pct}% used)",
            QMessageBox.ButtonRole.AcceptRole,
        )
        no_btn = dlg.addButton("No", QMessageBox.ButtonRole.RejectRole)
        dlg.setDefaultButton(no_btn)
        dlg.exec_()
        clicked = dlg.clickedButton()
        if clicked is clear_btn:
            return "clear"
        if clicked is yes_btn:
            return "yes"
        return "no"

    def _start_agent(self, user_message: str) -> None:
        chat_view = self._active_chat_view()
        if chat_view is None:
            return
        chat_view.add_user_message(user_message)
        self._set_running(True)

        # Update tab label after first user message
        self._update_tab_label(self._ctrl.active_tab_id)

        error = self._ctrl.start_agent(user_message)
        if error:
            chat_view.add_error_message(error)
            self._set_running(False)
            return

        self._ensure_poll_timer()
        self._poll_timer.start(50)

    def _ensure_poll_timer(self) -> None:
        if self._poll_timer is not None:
            return
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_events)

    def _stop_poll_timer(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            try:
                self._poll_timer.timeout.disconnect(self._poll_events)
            except (RuntimeError, TypeError) as e:
                log_debug(f"panel_core timer disconnect failed: {e}")
            self._poll_timer.deleteLater()
            self._poll_timer = None

    def _poll_events(self) -> None:
        if self._polling or self._is_shutdown:
            return
        self._polling = True
        try:
            for _ in range(20):
                event = self._ctrl.get_event(timeout=0)
                if event is None:
                    if not self._ctrl.is_agent_running:
                        self._on_agent_finished()
                    return
                self._on_event(event)
        finally:
            self._polling = False

    def _on_event(self, event: TurnEvent) -> None:
        if self._is_shutdown:
            return
        chat_view = self._active_chat_view()
        if chat_view is None:
            return
        chat_view.handle_event(event)
        if event.usage:
            # Use prompt_tokens from the event directly — session hasn't
            # been updated yet during streaming, so session.last_prompt_tokens
            # would be stale.  prompt_tokens reflects current context size.
            token_count = event.usage.prompt_tokens if event.usage.prompt_tokens is not None else event.usage.total_tokens
            if token_count > 0:
                self._update_token_display(token_count)
        if event.type in (TurnEventType.USER_QUESTION, TurnEventType.SAVE_APPROVAL_REQUEST,
                          TurnEventType.PLAN_GENERATED):
            self._pending_answer = True
            self._set_running(False)
        if event.type == TurnEventType.MUTATION_RECORDED:
            self._on_mutation_recorded(event)

    def _on_tool_approval(self, tool_call_id: str, decision: str) -> None:
        """Forward tool approval to the agent loop."""
        runner = self._ctrl.get_runner()
        if runner:
            runner.agent_loop.submit_tool_approval(decision)

    def _on_user_answer_submitted(self, answer: str) -> None:
        """Handle a button click from UserQuestionWidget (plan/save/ask_user)."""
        if not self._pending_answer:
            return
        self._pending_answer = False
        chat_view = self._active_chat_view()
        if chat_view is not None:
            chat_view.add_user_message(answer)
        self._set_running(True)
        runner = self._ctrl.get_runner()
        if runner:
            runner.agent_loop.submit_user_answer(answer)

    def _on_agent_finished(self) -> None:
        if self._is_shutdown:
            return
        if self._poll_timer:
            self._poll_timer.stop()

        self._ctrl.on_agent_finished()
        # Remove any [queued] widgets since the queue was cleared.
        chat_view = self._active_chat_view()
        if chat_view is not None:
            chat_view.remove_queued_messages()
        self._set_running(False)

    def _try_restore_session(self) -> None:
        restored = self._ctrl.restore_sessions()
        if restored:
            # Remove the default empty tab if it was replaced
            default_cv = None
            for tid, cv in list(self._chat_views.items()):
                if tid not in self._ctrl.tab_ids:
                    # This tab was removed during restore
                    for i in range(self._tab_widget.count()):
                        if self._tab_widget.widget(i) is cv:
                            self._tab_widget.removeTab(i)
                            break
                    cv.shutdown()
                    cv.deleteLater()
                    del self._chat_views[tid]

            for tab_id, session in restored:
                label = self._ctrl.tab_label(tab_id)
                chat_view = self._create_tab(tab_id, label)
                chat_view.restore_from_messages(session.messages)

            # Activate the last (most recent) tab
            if restored:
                last_tab_id = restored[-1][0]
                cv = self._chat_views.get(last_tab_id)
                if cv:
                    for i in range(self._tab_widget.count()):
                        if self._tab_widget.widget(i) is cv:
                            self._tab_widget.setCurrentIndex(i)
                            break
                self._update_token_display()
        else:
            # No saved sessions — try legacy single-session restore
            session = self._ctrl.restore_session()
            if session:
                chat_view = self._active_chat_view()
                if chat_view:
                    chat_view.restore_from_messages(session.messages)
                self._update_token_display()

    # --- Mutation log integration ---

    def _on_mutation_recorded(self, event: TurnEvent) -> None:
        """Handle a MUTATION_RECORDED event by adding it to the mutation log panel."""
        if self._mutation_panel is None:
            return
        meta = event.metadata
        record = MutationRecord(
            tool_name=event.tool_name,
            arguments={},
            reverse_tool=meta.get("reverse_tool", ""),
            reverse_arguments=meta.get("reverse_args", {}),
            description=event.text,
            reversible=meta.get("reversible", False),
        )
        self._mutation_panel.add_mutation(record)
        # Show the mutations button once the first mutation is recorded
        self._mutations_btn.setVisible(True)

    def _on_toggle_mutation_log(self) -> None:
        """Toggle visibility of the mutation log panel."""
        if self._mutation_panel is None:
            return
        visible = not self._mutation_panel.isVisible()
        self._mutation_panel.setVisible(visible)
        self._mutations_btn.setChecked(visible)

    def _on_undo_requested(self, count: int) -> None:
        """Handle undo request from the mutation log panel."""
        if self._is_shutdown:
            return
        # Submit /undo command through the normal agent path
        self._start_agent(f"/undo {count}")

    def _set_running(self, running: bool) -> None:
        # Keep input enabled so users can queue follow-up messages while running.
        self._input_area.set_enabled(True)
        if running:
            self._input_area.setPlaceholderText(
                "Rikugan is thinking... press Enter (or Queue) to queue a follow-up."
            )
        else:
            self._input_area.setPlaceholderText(
                "Ask about this binary... (/ for skills, /modify to patch)"
            )

        self._send_btn.setVisible(True)
        self._send_btn.setEnabled(True)
        self._send_btn.setText("Queue" if running else "Send")
        self._cancel_btn.setVisible(running)
