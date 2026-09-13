# -*- coding: utf-8 -*-
"""Small building blocks of the quality window, made only of the theme's style hooks."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


STATUS_TONES = ("success", "warning", "danger", "neutral")
# Month names in the genitive: the form a date takes inside a Russian sentence.
_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
EMPTY_STATE_TEXT_WIDTH = 560


def make_label(text: str = "", name: str = "", *, wrap: bool = False, parent=None) -> QLabel:
    """A label styled by its name that never renders its text as markup."""
    label = QLabel(text, parent)
    if name:
        label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    return label


def make_button(text: str, name: str, parent=None) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName(name)
    return button


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a property the style rules select on changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def format_checked_at(value: str) -> str:
    """Say when something was checked the way a date reads in a Russian sentence."""
    try:
        moment = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}, {moment:%H:%M}"


class StatusChip(QLabel):
    """A short state in a pill; the words carry the meaning, the colour only helps."""

    def __init__(self, text: str = "", tone: str = "neutral", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("statusChip")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        value = tone if tone in STATUS_TONES else "neutral"
        if self.property("tone") == value:
            return
        self.setProperty("tone", value)
        repolish(self)

    def set_state(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)


class MetricCard(QFrame):
    """One book total: what it counts, the number, and one line of detail."""

    action_clicked = pyqtSignal()

    def __init__(self, title: str, action_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("projectStatsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self.title_label = make_label(title, "projectCardTitle", parent=self)
        self.value_label = make_label("0", "metricValueLabel", parent=self)
        self.detail_label = make_label("", "mutedLabel", wrap=True, parent=self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        self.action_button: QPushButton | None = None
        if action_text:
            self.action_button = make_button(action_text, "pathActionButton", self)
            self.action_button.clicked.connect(self.action_clicked.emit)
            layout.addWidget(self.action_button)
        layout.addStretch(1)

    def set_values(self, value: str, detail: str) -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class EmptyState(QFrame):
    """A whole-tab card that says why nothing is here and what will fill it."""

    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("projectPathCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(10)
        layout.addStretch(1)
        self.title_label = make_label(title, "heroTitle", parent=self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        self.text_label = make_label(text, "heroSubtitle", wrap=True, parent=self)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A word-wrapped label added to a box layout with an alignment flag gets
        # no height-for-width and is cut to one line.  The text keeps a fixed
        # width, is centred by stretches, and reserves its wrapped height.
        self.text_label.setFixedWidth(EMPTY_STATE_TEXT_WIDTH)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.text_label)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self._fit_text()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_text()

    def _fit_text(self) -> None:
        self.text_label.ensurePolished()
        self.text_label.setMinimumHeight(
            self.text_label.heightForWidth(EMPTY_STATE_TEXT_WIDTH)
        )
