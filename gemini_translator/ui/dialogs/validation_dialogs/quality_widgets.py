# -*- coding: utf-8 -*-
"""Small building blocks of the quality window, made only of the theme's style hooks."""

from __future__ import annotations

from datetime import datetime
from html import escape

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

from ....qa.language_validation import describe_refusal
from ....qa.models import QaSuggestion
from ....qa.report_snapshot import chapter_display_name
from ....qa.text_diff import highlight_pair


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


def plural(count: int, one: str, few: str, many: str) -> str:
    """Pick the form a Russian noun takes after a number: 1 глава, 2 главы, 5 глав."""
    tail = abs(int(count)) % 100
    if 11 <= tail <= 19:
        return many
    if tail % 10 == 1:
        return one
    if 2 <= tail % 10 <= 4:
        return few
    return many


def chapters_caption(count: int) -> str:
    return f"{count} {plural(count, 'глава', 'главы', 'глав')}"


# How a suggestion's category reads on its chip; an unknown code is shown as is.
CATEGORY_LABELS = {
    "typo": "опечатка",
    "grammar": "грамматика",
    "punctuation": "пунктуация",
    "calque": "калька",
    "repetition": "повтор",
    "meta_comment": "служебный комментарий",
    "hallucinated_addition": "добавленный факт",
    "style_suggestion": "стиль",
}


def category_label(code: str) -> str:
    return CATEGORY_LABELS.get(code, code)


def pending_caption(count: int) -> str:
    """«N правок ждут решения», agreeing with the number the way Russian does."""
    noun = plural(count, "правка", "правки", "правок")
    verb = "ждёт" if plural(count, "one", "few", "many") == "one" else "ждут"
    return f"{count} {noun} {verb} решения"


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


class SuggestionCard(QFrame):
    """One refused fix: where, what kind, why it was not applied, and both texts."""

    apply_requested = pyqtSignal(str)
    dismiss_requested = pyqtSignal(str)

    def __init__(
        self, suggestion: QaSuggestion, *, show_chapter: bool = True, parent=None
    ) -> None:
        super().__init__(parent)
        self.suggestion = suggestion
        self.setObjectName("statusSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        if show_chapter:
            top.addWidget(
                make_label(
                    chapter_display_name(suggestion.chapter_id), "projectCardTitle", parent=self
                )
            )
        self.category_chip = StatusChip(category_label(suggestion.category), "neutral", self)
        top.addWidget(self.category_chip)
        reason = (
            f"не принято: {describe_refusal(suggestion.reason)}"
            if suggestion.reason
            else "не принято"
        )
        self.reason_label = make_label(reason, "mutedLabel", wrap=True, parent=self)
        top.addWidget(self.reason_label, 1)
        layout.addLayout(top)

        if suggestion.replacement_text:
            before_html, after_html = highlight_pair(
                suggestion.original_text, suggestion.replacement_text
            )
        else:
            before_html, after_html = escape(suggestion.original_text), "удалить фрагмент"
        self.before_label = self._text_row(layout, "было", before_html)
        self.after_label = self._text_row(layout, "стало", after_html)
        if suggestion.explanation:
            layout.addWidget(
                make_label(suggestion.explanation, "mutedLabel", wrap=True, parent=self)
            )

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.note_label = make_label("", "helperLabel", wrap=True, parent=self)
        actions.addWidget(self.note_label, 1)
        stale = suggestion.status == "stale"
        self.dismiss_button = make_button(
            "Убрать из списка" if stale else "Отклонить", "ghostActionButton", self
        )
        self.dismiss_button.clicked.connect(
            lambda: self.dismiss_requested.emit(self.suggestion.suggestion_id)
        )
        actions.addWidget(self.dismiss_button)
        self.apply_button: QPushButton | None = None
        if stale:
            note = suggestion.status_note
            self.note_label.setText(f"устарело: {note}" if note else "устарело")
        else:
            self.apply_button = make_button("Применить", "compactActionButton", self)
            self.apply_button.clicked.connect(
                lambda: self.apply_requested.emit(self.suggestion.suggestion_id)
            )
            actions.addWidget(self.apply_button)
            if not suggestion.applicable:
                self.note_label.setText("Нет текста замены: такую правку вносит человек.")
        layout.addLayout(actions)
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.dismiss_button.setEnabled(not busy)
        if self.apply_button is not None:
            self.apply_button.setEnabled(not busy and self.suggestion.applicable)

    def _text_row(self, layout: QVBoxLayout, caption: str, html_text: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(10)
        caption_label = make_label(caption, "mutedLabel", parent=self)
        caption_label.setFixedWidth(42)
        # The caption never wraps, so the alignment flag costs it nothing.
        row.addWidget(caption_label, 0, Qt.AlignmentFlag.AlignTop)
        # Rich text only for the diff marks: highlight_pair escapes both texts.
        text_label = QLabel(html_text, self)
        text_label.setTextFormat(Qt.TextFormat.RichText)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(text_label, 1)
        layout.addLayout(row)
        return text_label
