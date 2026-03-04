"""Plan mode view: step-by-step plan display with approve/reject."""

from __future__ import annotations

from typing import List, Optional

from .qt_compat import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QSizePolicy, Qt,
)


class PlanStepWidget(QFrame):
    """Single plan step with status indicator."""

    def __init__(self, index: int, text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("plan_step")
        self._index = index
        self._status = "pending"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._status_label = QLabel("○")
        self._status_label.setFixedWidth(20)
        self._status_label.setStyleSheet("color: #808080; font-size: 14px;")
        layout.addWidget(self._status_label)

        self._step_label = QLabel(f"{index + 1}. {text}")
        self._step_label.setWordWrap(True)
        self._step_label.setStyleSheet("color: #d4d4d4; font-size: 12px;")
        layout.addWidget(self._step_label, 1)

    def set_status(self, status: str) -> None:
        self._status = status
        if status == "active":
            self.setObjectName("plan_step_active")
            self._status_label.setText("▶")
            self._status_label.setStyleSheet("color: #007acc; font-size: 14px;")
        elif status == "done":
            self.setObjectName("plan_step_done")
            self._status_label.setText("✓")
            self._status_label.setStyleSheet("color: #4ec9b0; font-size: 14px;")
        elif status == "error":
            self._status_label.setText("✗")
            self._status_label.setStyleSheet("color: #f44747; font-size: 14px;")
        elif status == "skipped":
            self._status_label.setText("−")
            self._status_label.setStyleSheet("color: #808080; font-size: 14px;")
        else:
            self.setObjectName("plan_step")
            self._status_label.setText("○")
            self._status_label.setStyleSheet("color: #808080; font-size: 14px;")
        self.style().unpolish(self)
        self.style().polish(self)


class PlanView(QFrame):
    """Plan mode view with approve/reject controls.

    Uses plain Python callbacks instead of Signal() to avoid corrupting
    Shiboken's global signal registry on Python 3.14.
    """

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("plan_view")
        self._steps: List[PlanStepWidget] = []
        self._on_approved = None
        self._on_rejected = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header
        self._header = QLabel("Plan")
        self._header.setStyleSheet("color: #569cd6; font-weight: bold; font-size: 13px;")
        layout.addWidget(self._header)

        # Steps container
        self._steps_container = QVBoxLayout()
        layout.addLayout(self._steps_container)

        # Approve/reject buttons
        btn_layout = QHBoxLayout()

        self._approve_btn = QPushButton("Approve & Execute")
        self._approve_btn.setStyleSheet(
            "QPushButton { background: #2ea043; color: white; border: none; "
            "border-radius: 6px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background: #3fb950; }"
        )
        self._approve_btn.clicked.connect(self._fire_approved)
        btn_layout.addWidget(self._approve_btn)

        self._reject_btn = QPushButton("Reject")
        self._reject_btn.setStyleSheet(
            "QPushButton { background: #c72e2e; color: white; border: none; "
            "border-radius: 6px; padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background: #d73a49; }"
        )
        self._reject_btn.clicked.connect(self._fire_rejected)
        btn_layout.addWidget(self._reject_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()

    def set_plan(self, steps: List[str]) -> None:
        """Set plan steps and display them."""
        self.clear()
        for i, text in enumerate(steps):
            step_widget = PlanStepWidget(i, text)
            self._steps.append(step_widget)
            self._steps_container.addWidget(step_widget)

    def set_step_status(self, index: int, status: str) -> None:
        if 0 <= index < len(self._steps):
            self._steps[index].set_status(status)

    def set_buttons_visible(self, visible: bool) -> None:
        self._approve_btn.setVisible(visible)
        self._reject_btn.setVisible(visible)

    def set_approved_callback(self, callback) -> None:
        self._on_approved = callback

    def set_rejected_callback(self, callback) -> None:
        self._on_rejected = callback

    def _fire_approved(self) -> None:
        if self._on_approved is not None:
            self._on_approved()

    def _fire_rejected(self) -> None:
        if self._on_rejected is not None:
            self._on_rejected()

    def clear(self) -> None:
        for step in self._steps:
            step.deleteLater()
        self._steps.clear()
