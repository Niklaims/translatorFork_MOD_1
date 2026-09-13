# -*- coding: utf-8 -*-
"""The «Отчёт» tab: book totals, the chapter list, and the selected chapter."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....qa.report_snapshot import (
    CHAPTER_STATUS_LABELS,
    BookQaReportSnapshot,
    ChapterQaRow,
    chapter_display_name,
    chapter_display_names,
)
from ... import theme_manager
from .quality_widgets import (
    EmptyState,
    MetricCard,
    StatusChip,
    SuggestionCard,
    chapters_caption,
    format_checked_at,
    make_button,
    make_label,
    plural,
)
from .translation_quality_models import DECISION_LABELS


# Only the statuses that ask for attention are coloured: a column where every
# «Проверена» is green hides the one chapter that is not.
ATTENTION_TONES = {"deferred": "warning", "blocked": "danger"}
# How the chapter card's sentence begins.  A blocked chapter was checked; that
# it holds the translation up is what the chip under the sentence says.
STATUS_SENTENCES = {
    "checked": "Проверена",
    "blocked": "Проверена",
    "deferred": "Отложена",
    "": "Нет данных о проверке",
}
BLOCK_CHIP_TEXT = "Перевод остановлен"
BASE_COLUMNS = (
    ("Глава", "chapter_id"),
    ("Статус", "status"),
    ("Исправлено", "applied_repairs"),
    ("Ждут решения", "pending_suggestions"),
)
# Only the short numbers a list has room for.  The book norm and the confirmed
# gaps are sentences; the chapter card shows them in full.
COMPLETENESS_COLUMNS = (
    ("Длина", "length_ratio"),
    ("Пропуски", "possible_gaps"),
)
SCORE_COLUMNS = (("Оценка", "quality_score"),)
# Text reads from the left edge; numbers sit centred under their headers.
TEXT_FIELDS = frozenset({"chapter_id", "status"})
REPORT_EMPTY_TITLE = "Отчёт пока пуст"
REPORT_EMPTY_TEXT = (
    "Проверенные главы появятся здесь после первого прохода. Проверка идёт после "
    "каждой переведённой главы или по кнопке «Проверить все главы»."
)
NO_CHAPTER_TITLE = "Глава не выбрана"
NO_CHAPTER_TEXT = "Выберите главу в списке слева."


def report_columns(snapshot: BookQaReportSnapshot) -> tuple[tuple[str, str], ...]:
    """The table's columns: completeness and score only where the book has them."""
    columns = BASE_COLUMNS
    if snapshot.has_completeness:
        columns += COMPLETENESS_COLUMNS
    if snapshot.has_scores:
        columns += SCORE_COLUMNS
    return columns


class QualityReportView(QWidget):
    """Show one report snapshot and ask for actions on what the user selected."""

    check_chapter_requested = pyqtSignal(str)
    undo_chapter_requested = pyqtSignal(str)
    undo_all_requested = pyqtSignal()
    open_suggestions_requested = pyqtSignal()
    apply_suggestion_requested = pyqtSignal(str)
    dismiss_suggestion_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._snapshot = BookQaReportSnapshot()
        self._busy = False
        self._scoring_enabled = False
        self._display_names: dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)
        self.content = QWidget(self.stack)
        self.empty_state = EmptyState(REPORT_EMPTY_TITLE, REPORT_EMPTY_TEXT, self.stack)
        self.stack.addWidget(self.content)
        self.stack.addWidget(self.empty_state)

        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addLayout(self._build_totals())
        split = QHBoxLayout()
        split.setSpacing(10)
        split.addWidget(self._build_chapter_list(), 5)
        split.addWidget(self._build_chapter_card(), 6)
        content_layout.addLayout(split, 1)

        self.stack.setCurrentWidget(self.empty_state)
        self._update_actions()

    # -- building ----------------------------------------------------------

    def _build_totals(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.checked_card = MetricCard("Проверено", parent=self.content)
        self.repaired_card = MetricCard("Исправлено автоматически", parent=self.content)
        # Always available: with nothing waiting it leads to an empty state that
        # says why, while a greyed-out button only looked broken.
        self.pending_card = MetricCard("Ждут решения", "Открыть предложения", self.content)
        self.pending_card.action_clicked.connect(self.open_suggestions_requested.emit)
        self.score_card = MetricCard("Оценка CometKiwi", parent=self.content)
        self.score_card.setVisible(False)
        row.addWidget(self.checked_card, 3)
        row.addWidget(self.repaired_card, 2)
        row.addWidget(self.pending_card, 2)
        row.addWidget(self.score_card, 2)
        return row

    def _build_chapter_list(self) -> QFrame:
        card = QFrame(self.content)
        card.setObjectName("projectPathCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(make_label("Главы", "projectCardTitle", parent=card))

        self.table = QTableWidget(0, len(BASE_COLUMNS), card)
        self.table.setObjectName("qualityChapterTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._set_columns(BASE_COLUMNS)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        undo_row = QHBoxLayout()
        self.undo_all_button = make_button(
            "Отменить все автоисправления книги", "dangerActionButton", card
        )
        self.undo_all_button.clicked.connect(self.undo_all_requested.emit)
        undo_row.addWidget(self.undo_all_button)
        undo_row.addStretch(1)
        layout.addLayout(undo_row)
        return card

    def _build_chapter_card(self) -> QFrame:
        self.chapter_card = QFrame(self.content)
        self.chapter_card.setObjectName("projectHeaderCard")
        self.chapter_layout = QVBoxLayout(self.chapter_card)
        self.chapter_layout.setContentsMargins(14, 12, 14, 12)
        self.chapter_layout.setSpacing(8)
        self.chapter_layout.addWidget(
            make_label("Глава", "sectionEyebrow", parent=self.chapter_card)
        )
        self.chapter_title_label = make_label(
            NO_CHAPTER_TITLE, "heroTitle", wrap=True, parent=self.chapter_card
        )
        # The chapter's full path inside the book, when the title is only its
        # file name: two books can name a file alike, a path tells them apart.
        self.chapter_path_label = make_label(
            "", "mutedLabel", wrap=True, parent=self.chapter_card
        )
        self.chapter_path_label.setVisible(False)
        self.chapter_meta_label = make_label(
            NO_CHAPTER_TEXT, "heroSubtitle", wrap=True, parent=self.chapter_card
        )
        block_row = QHBoxLayout()
        block_row.setContentsMargins(0, 0, 0, 0)
        self.chapter_block_chip = StatusChip(BLOCK_CHIP_TEXT, "danger", self.chapter_card)
        self.chapter_block_chip.setVisible(False)
        block_row.addWidget(self.chapter_block_chip)
        block_row.addStretch(1)
        self.chapter_details_label = make_label(
            "", "mutedLabel", wrap=True, parent=self.chapter_card
        )
        self.chapter_details_label.setVisible(False)
        self.chapter_layout.addWidget(self.chapter_title_label)
        self.chapter_layout.addWidget(self.chapter_path_label)
        self.chapter_layout.addWidget(self.chapter_meta_label)
        self.chapter_layout.addLayout(block_row)
        self.chapter_layout.addWidget(self.chapter_details_label)
        self.pending_title_label = make_label(
            "", "projectCardTitle", parent=self.chapter_card
        )
        self.pending_title_label.setVisible(False)
        self.chapter_layout.addWidget(self.pending_title_label)
        self.pending_container = QWidget()
        self.pending_layout = QVBoxLayout(self.pending_container)
        self.pending_layout.setContentsMargins(0, 0, 0, 0)
        self.pending_layout.setSpacing(8)
        self.pending_layout.addStretch(1)
        self.pending_area = QScrollArea(self.chapter_card)
        self.pending_area.setWidgetResizable(True)
        self.pending_area.setFrameShape(QFrame.Shape.NoFrame)
        self.pending_area.setWidget(self.pending_container)
        self.pending_area.setVisible(False)
        self.chapter_layout.addWidget(self.pending_area, 1)
        self.pending_cards: list[SuggestionCard] = []
        self._pending_suggestions: tuple = ()
        # No stretch factor of its own: it holds the buttons down only while the
        # list is hidden, and a visible list then takes all the room, not half.
        self.chapter_layout.addStretch()

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.check_chapter_button = make_button(
            "Проверить главу", "compactActionButton", self.chapter_card
        )
        self.undo_chapter_button = make_button(
            "Отменить исправления главы", "compactActionButton", self.chapter_card
        )
        self.check_chapter_button.clicked.connect(self._request_check_chapter)
        self.undo_chapter_button.clicked.connect(self._request_undo_chapter)
        buttons.addWidget(self.check_chapter_button)
        buttons.addWidget(self.undo_chapter_button)
        buttons.addStretch(1)
        self.chapter_layout.addLayout(buttons)
        return self.chapter_card

    # -- public API --------------------------------------------------------

    def set_report(
        self, snapshot: BookQaReportSnapshot, *, scoring_enabled: bool = False
    ) -> None:
        """Show one immutable report; an unchanged chapter list is not rebuilt."""
        if not isinstance(snapshot, BookQaReportSnapshot):
            raise TypeError("snapshot must be a BookQaReportSnapshot")
        previous = self._snapshot
        self._snapshot = snapshot
        self._scoring_enabled = bool(scoring_enabled)
        self.stack.setCurrentWidget(self.content if snapshot.rows else self.empty_state)
        self._refresh_totals()
        if snapshot.rows != previous.rows or self.table.rowCount() != len(snapshot.rows):
            self._rebuild_table()
        if snapshot.rows and not self.selected_chapter_id():
            # Opening on nothing left half the tab empty; the chapter that most
            # needs a look is the natural place to start.
            self.select_chapter(_attention_chapter(snapshot))
        self._refresh_chapter_card()
        self._update_actions()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        for card in self.pending_cards:
            card.set_busy(self._busy)
        self._update_actions()

    def selected_chapter_id(self) -> str:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return ""
        item = self.table.item(indexes[0].row(), 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def select_chapter(self, chapter_id: str) -> bool:
        for index, row in enumerate(self._snapshot.rows):
            if row.chapter_id == chapter_id:
                self.table.selectRow(index)
                return True
        return False

    # -- Qt events ---------------------------------------------------------

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() == QEvent.Type.StyleChange:
            # The theme installs its stylesheet before its palette, so the
            # colours are read once both have changed.
            QTimer.singleShot(0, self._recolor_statuses)

    # -- internals ---------------------------------------------------------

    def _set_columns(self, columns) -> None:
        """Only the chapter column stretches; every other one is as wide as its values."""
        table = self.table
        table.setColumnCount(len(columns))
        header = table.horizontalHeader()
        for index, (title, field_name) in enumerate(columns):
            item = QTableWidgetItem(title)
            item.setTextAlignment(_alignment(field_name))
            table.setHorizontalHeaderItem(index, item)
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.Stretch
                if field_name == "chapter_id"
                else QHeaderView.ResizeMode.ResizeToContents,
            )

    def _rebuild_table(self) -> None:
        selected = self.selected_chapter_id()
        columns = report_columns(self._snapshot)
        rows = self._snapshot.rows
        self._display_names = chapter_display_names(row.chapter_id for row in rows)
        table = self.table
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        try:
            table.clearContents()
            self._set_columns(columns)
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, (_title, field_name) in enumerate(columns):
                    table.setItem(
                        row_index,
                        column_index,
                        _item(row, field_name, self._display_names),
                    )
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)
        if selected:
            self.select_chapter(selected)

    def _recolor_statuses(self) -> None:
        """Repaint the coloured statuses in the palette that is current now."""
        columns = report_columns(self._snapshot)
        column = next(
            (index for index, (_title, name) in enumerate(columns) if name == "status"),
            None,
        )
        if column is None or self.table.rowCount() != len(self._snapshot.rows):
            return
        for row_index, row in enumerate(self._snapshot.rows):
            item = self.table.item(row_index, column)
            if item is not None:
                _paint_status(item, row)

    def _refresh_totals(self) -> None:
        snapshot = self._snapshot
        self.checked_card.set_values(
            f"{snapshot.checked_count} из {len(snapshot.rows)}",
            _held_back(snapshot.deferred_count, snapshot.blocking_count),
        )
        self.repaired_card.set_values(
            str(snapshot.repair_count),
            f"{_in_chapters(len(snapshot.repaired_chapters))} Откатываются по главе."
            if snapshot.repair_count
            else "Автоисправлений пока нет.",
        )
        self.pending_card.set_values(
            str(snapshot.pending_suggestion_count),
            _in_chapters(len(snapshot.pending_suggestion_chapters))
            if snapshot.pending_suggestion_count
            else "Непринятых правок нет.",
        )
        average = snapshot.average_score
        scored = sum(1 for row in snapshot.rows if row.quality_score is not None)
        self.score_card.set_values(
            f"{average:.2f}" if average is not None else "—",
            f"Оценено: {chapters_caption(scored)}." if scored else "Оценок пока нет.",
        )
        self.score_card.setVisible(self._scoring_enabled)

    def _selected_row(self) -> ChapterQaRow | None:
        chapter_id = self.selected_chapter_id()
        if not chapter_id:
            return None
        return next(
            (row for row in self._snapshot.rows if row.chapter_id == chapter_id), None
        )

    def _refresh_chapter_card(self) -> None:
        row = self._selected_row()
        if row is None:
            self.chapter_title_label.setText(NO_CHAPTER_TITLE)
            self.chapter_path_label.clear()
            self.chapter_path_label.setVisible(False)
            self.chapter_meta_label.setText(NO_CHAPTER_TEXT)
            self.chapter_block_chip.setVisible(False)
            self.chapter_details_label.clear()
            self.chapter_details_label.setVisible(False)
            self._refresh_pending("")
            return
        name = self._display_names.get(row.chapter_id) or chapter_display_name(
            row.chapter_id
        )
        self.chapter_title_label.setText(name)
        shows_path = name != row.chapter_id
        self.chapter_path_label.setText(row.chapter_id if shows_path else "")
        self.chapter_path_label.setVisible(shows_path)
        self.chapter_meta_label.setText(_chapter_meta(row))
        self.chapter_block_chip.setVisible(row.status == "blocked" or bool(row.blocked_reason))
        details = _chapter_details(
            row, self._snapshot.decisions_by_chapter.get(row.chapter_id, ())
        )
        self.chapter_details_label.setText(details)
        self.chapter_details_label.setVisible(bool(details))
        self._refresh_pending(row.chapter_id)

    def _refresh_pending(self, chapter_id: str) -> None:
        suggestions = self._snapshot.suggestions_for(chapter_id) if chapter_id else ()
        if suggestions != self._pending_suggestions:
            for card in self.pending_cards:
                card.setParent(None)
                card.deleteLater()
            self.pending_cards = []
            for suggestion in suggestions:
                card = SuggestionCard(
                    suggestion, show_chapter=False, parent=self.pending_container
                )
                card.apply_requested.connect(self.apply_suggestion_requested.emit)
                card.dismiss_requested.connect(self.dismiss_suggestion_requested.emit)
                self.pending_layout.insertWidget(self.pending_layout.count() - 1, card)
                self.pending_cards.append(card)
            self._pending_suggestions = suggestions
        for card in self.pending_cards:
            card.set_busy(self._busy)
        self.pending_title_label.setText(f"Ждут решения: {len(suggestions)}")
        self.pending_title_label.setVisible(bool(suggestions))
        self.pending_area.setVisible(bool(suggestions))

    def _on_selection_changed(self) -> None:
        self._refresh_chapter_card()
        self._update_actions()

    def _update_actions(self) -> None:
        chapter_id = self.selected_chapter_id()
        repaired = set(self._snapshot.repaired_chapters)
        idle = not self._busy
        self.check_chapter_button.setEnabled(bool(chapter_id) and idle)
        self.undo_chapter_button.setEnabled(
            bool(chapter_id) and chapter_id in repaired and idle
        )
        self.undo_all_button.setEnabled(bool(repaired) and idle)

    def _request_check_chapter(self) -> None:
        chapter_id = self.selected_chapter_id()
        if chapter_id:
            self.check_chapter_requested.emit(chapter_id)

    def _request_undo_chapter(self) -> None:
        chapter_id = self.selected_chapter_id()
        if chapter_id:
            self.undo_chapter_requested.emit(chapter_id)


def _attention_chapter(snapshot: BookQaReportSnapshot) -> str:
    """The chapter to open on: blocking first, then deferred, then one with suggestions."""
    rows = snapshot.rows
    for needs_attention in (
        lambda row: row.status == "blocked" or bool(row.blocked_reason),
        lambda row: row.status == "deferred",
        lambda row: row.pending_suggestions > 0,
    ):
        found = next((row for row in rows if needs_attention(row)), None)
        if found is not None:
            return found.chapter_id
    return rows[0].chapter_id if rows else ""


def _held_back(deferred: int, blocking: int) -> str:
    """Say how many chapters are held back, in words that agree with the numbers."""
    parts = []
    if deferred:
        parts.append(
            f"{chapters_caption(deferred)} "
            f"{plural(deferred, 'отложена', 'отложены', 'отложено')}."
        )
    if blocking:
        parts.append(
            f"{chapters_caption(blocking)} "
            f"{plural(blocking, 'блокирует', 'блокируют', 'блокируют')} перевод."
        )
    return " ".join(parts) or "Отложенных и блокирующих глав нет."


def _in_chapters(count: int) -> str:
    """«В 1 главе», «В 21 главе», «В 2 главах»: the locative after a number."""
    noun = "главе" if count % 10 == 1 and count % 100 != 11 else "главах"
    return f"В {count} {noun}."


def _alignment(field_name: str) -> Qt.AlignmentFlag:
    if field_name in TEXT_FIELDS:
        return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    return Qt.AlignmentFlag.AlignCenter


def _paint_status(item: QTableWidgetItem, row: ChapterQaRow) -> None:
    tone = ATTENTION_TONES.get(row.status)
    if tone:
        item.setForeground(QBrush(QColor(theme_manager.color(f"{tone}_text"))))
    else:
        item.setData(Qt.ItemDataRole.ForegroundRole, None)


def _item(row: ChapterQaRow, field_name: str, names: dict[str, str]) -> QTableWidgetItem:
    item = QTableWidgetItem(_cell_text(row, field_name, names))
    item.setTextAlignment(_alignment(field_name))
    if field_name == "chapter_id":
        item.setData(Qt.ItemDataRole.UserRole, row.chapter_id)
        if item.text() != row.chapter_id:
            item.setToolTip(row.chapter_id)
    elif field_name == "status":
        _paint_status(item, row)
        if row.blocked_reason:
            item.setToolTip(f"Перевод остановлен: {row.blocked_reason}")
    return item


def _cell_text(row: ChapterQaRow, field_name: str, names: dict[str, str]) -> str:
    if field_name == "chapter_id":
        return names.get(row.chapter_id) or chapter_display_name(row.chapter_id)
    if field_name == "status":
        label = CHAPTER_STATUS_LABELS.get(row.status, row.status)
        # Colour is never the only signal: a blocked chapter says so in words.
        return f"⛔ {label}" if row.blocked_reason else label
    if field_name in ("applied_repairs", "pending_suggestions"):
        value = int(getattr(row, field_name))
        return str(value) if value else ""
    if field_name == "quality_score":
        return f"{row.quality_score:.2f}" if row.quality_score is not None else "—"
    if not row.has_completeness:
        return "—"
    if field_name == "length_ratio":
        return f"{row.length_ratio:.2f}"
    return str(getattr(row, field_name))


def _chapter_meta(row: ChapterQaRow) -> str:
    sentence = STATUS_SENTENCES.get(
        row.status, CHAPTER_STATUS_LABELS.get(row.status, row.status)
    )
    checked_at = format_checked_at(row.checked_at)
    if checked_at:
        sentence += f" {checked_at}"
    if row.risk_label:
        sentence += f", риск {row.risk_label.lower()}"
    return f"{sentence}. Исправлено автоматически: {row.applied_repairs}."


def _chapter_details(row: ChapterQaRow, decisions) -> str:
    lines: list[str] = []
    if row.blocked_reason:
        lines.append(f"Причина: {row.blocked_reason}")
    if row.has_completeness:
        lines.append(
            f"{row.language_pair}, длина {row.length_ratio:.2f} — {row.profile_status}"
        )
        lines.append(f"Книжная норма: {row.book_position}")
        lines.append(
            f"Возможные пропуски: {row.possible_gaps}, подтверждённые: {row.confirmed_gaps}"
        )
        lines.append(
            f"Конфликты терминов: {row.glossary_conflicts}, остатки исходника: "
            f"{row.untranslated_fragments}, языковые дефекты: {row.language_issues}"
        )
    if row.quality_score is not None:
        lines.append(f"Оценка CometKiwi: {row.quality_score:.2f}")
    if decisions:
        lines.append(
            "Решения проверки: "
            + ", ".join(DECISION_LABELS.get(decision, decision) for decision in decisions)
        )
    return "\n".join(lines)
