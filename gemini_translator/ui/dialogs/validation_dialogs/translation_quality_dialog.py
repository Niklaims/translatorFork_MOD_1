# -*- coding: utf-8 -*-
"""The «Качество перевода» window: a header, four tabs and one action bar."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ....qa.report_snapshot import BookQaReportSnapshot
from ....qa.settings import QaSettings
from .quality_report_view import QualityReportView
from .quality_settings_view import QualitySettingsView
from .quality_suggestions_view import QualitySuggestionsView
from .quality_widgets import StatusChip, format_checked_at, make_button, make_label


# The log keeps the newest chapters; a six-hundred-chapter book would otherwise
# grow one document until the window slows down.
LOG_MAX_BLOCKS = 4000


def describe_checks(settings: QaSettings) -> str:
    """Name the checks that run after each chapter, the way the header says it."""
    checks = []
    if settings.check_language_after_chapter:
        checks.append("язык")
    if settings.check_completeness_after_chapter:
        checks.append("полнота")
    if settings.capabilities.cometkiwi_enabled:
        checks.append("оценка CometKiwi")
    if not checks:
        return "Проверки после глав выключены."
    return "После каждой главы: " + ", ".join(checks) + "."


class TranslationQualityDialog(QDialog):
    """Show what quality control found and let the user act on it."""

    check_chapter_requested = pyqtSignal(str)
    check_all_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    undo_chapter_requested = pyqtSignal(str)
    undo_all_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    settings_changed = pyqtSignal(object)
    embedding_test_requested = pyqtSignal(object)
    export_requested = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        *,
        settings: QaSettings | None = None,
        key_counter=None,
        book_title: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Качество перевода")
        self.setMinimumSize(1040, 640)
        self._settings = settings or QaSettings()
        self._snapshot = BookQaReportSnapshot()
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(self._build_header(book_title))

        self.report_view = QualityReportView(self)
        self.suggestions_view = QualitySuggestionsView(self)
        self.settings_view = QualitySettingsView(
            self._settings, key_counter=key_counter, parent=self
        )
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.report_view, "Отчёт")
        self.tabs.addTab(self.suggestions_view, "Предложения")
        self.tabs.addTab(self._build_log_tab(), "Журнал правок")
        self.tabs.addTab(self.settings_view, "Настройки")
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self._build_action_bar())

        self.report_view.check_chapter_requested.connect(self.check_chapter_requested.emit)
        self.report_view.undo_chapter_requested.connect(self._request_undo_chapter)
        self.report_view.undo_all_requested.connect(self._request_undo_all)
        self.report_view.open_suggestions_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.suggestions_view)
        )
        self.settings_view.settings_changed.connect(self._on_settings_changed)
        self.settings_view.embedding_test_requested.connect(
            self.embedding_test_requested.emit
        )

        self._refresh_header()
        self._update_action_state()

    # -- building ----------------------------------------------------------

    def _build_header(self, book_title: str) -> QFrame:
        header = QFrame(self)
        header.setObjectName("projectHeaderCard")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)
        intro = QVBoxLayout()
        intro.setSpacing(2)
        intro.addWidget(make_label("Качество перевода", "sectionEyebrow", parent=header))
        self.title_label = make_label(
            book_title or "Книга без названия", "heroTitle", wrap=True, parent=header
        )
        self.subtitle_label = make_label("", "heroSubtitle", wrap=True, parent=header)
        intro.addWidget(self.title_label)
        intro.addWidget(self.subtitle_label)
        row.addLayout(intro, 1)
        self.state_chip = StatusChip("Готово к проверке", "success", header)
        row.addWidget(self.state_chip, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_log_tab(self) -> QWidget:
        """The running account of what the check changed, chapter by chapter.

        The report is rebuilt from the journal; a pass over a book takes hours,
        and this is what can be read while it runs.
        """
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 10, 0, 0)
        card = QFrame(page)
        card.setObjectName("projectPathCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        self.log_view = QTextEdit(card)
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText(
            "Здесь появится каждая глава: что найдено, что исправлено и что "
            "осталось предложением."
        )
        # A long book would otherwise grow the document without limit.
        self.log_view.document().setMaximumBlockCount(LOG_MAX_BLOCKS)
        card_layout.addWidget(self.log_view)
        page_layout.addWidget(card)
        return page

    def _build_action_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("actionBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.status_label = make_label("", "helperLabel", wrap=True, parent=bar)
        row.addWidget(self.status_label, 1)
        self.progress = QProgressBar(bar)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumWidth(220)
        self.progress.setVisible(False)
        row.addWidget(self.progress)

        self.export_button = make_button("Экспорт отчёта", "compactActionButton", bar)
        self.check_all_button = make_button("Проверить все главы", "compactActionButton", bar)
        self.resume_button = make_button("Продолжить проверку", "primaryActionButton", bar)
        self.resume_button.setToolTip(
            "Проверить только те главы, которые ещё не проверялись, были "
            "отложены, остались с неустранённым риском или изменились после "
            "проверки. Уже улаженные главы не перепроверяются."
        )
        # Takes the primary button's place while a pass runs: the one thing to
        # do then is stop it.
        self.cancel_button = make_button("Остановить проверку", "dangerActionButton", bar)
        self.close_button = make_button("Закрыть", "ghostActionButton", bar)

        self.export_button.clicked.connect(self._request_export)
        self.check_all_button.clicked.connect(self.check_all_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.close_button.clicked.connect(self.reject)
        for button in (
            self.export_button,
            self.check_all_button,
            self.resume_button,
            self.cancel_button,
            self.close_button,
        ):
            row.addWidget(button)
        return bar

    # -- public API --------------------------------------------------------

    def set_report(self, snapshot: BookQaReportSnapshot) -> None:
        """Replace the report with an immutable snapshot from the journal."""
        self.report_view.set_report(
            snapshot, scoring_enabled=self._settings.capabilities.cometkiwi_enabled
        )
        self._snapshot = snapshot
        self._refresh_header()
        self._update_action_state()

    def set_busy(self, busy: bool) -> None:
        """Disable everything a running check must own exclusively."""
        self._busy = bool(busy)
        self.progress.setVisible(self._busy)
        self.report_view.set_busy(self._busy)
        self._refresh_header()
        self._update_action_state()

    def set_progress(self, checked: int, total: int, chapter_id: str = "") -> None:
        """Show honest progress of a whole-book pass."""
        total = max(int(total), 0)
        self.progress.setVisible(True)
        self.progress.setRange(0, total or 0)
        self.progress.setValue(min(int(checked), total) if total else 0)
        suffix = f" — {chapter_id}" if chapter_id else ""
        self.progress.setFormat(f"Проверено %v из %m{suffix}")

    def append_log(self, html: str) -> None:
        """Add one finished chapter to the log and keep the newest in view."""
        text = str(html or "").strip()
        if not text:
            return
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)
        self.log_view.insertHtml(text + "<hr>")
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_status(self, message: str) -> None:
        """Report one short outcome or failure without touching the report."""
        self.status_label.setText(str(message or ""))

    def set_embedding_result(self, message: str) -> None:
        """Show what the connection check answered next to the embedding settings."""
        self.settings_view.set_embedding_result(message)

    def selected_chapter_id(self) -> str:
        """Return the chapter the user is acting on, if any."""
        return self.report_view.selected_chapter_id()

    def select_chapter(self, chapter_id: str) -> bool:
        """Move the report to one chapter; used when navigating from a finding."""
        return self.report_view.select_chapter(chapter_id)

    def qa_settings(self) -> QaSettings:
        """Return the settings exactly as the settings tab currently expresses them."""
        return self.settings_view.qa_settings()

    # -- internals ---------------------------------------------------------

    def _on_settings_changed(self, settings: QaSettings) -> None:
        self._settings = settings
        self.report_view.set_report(
            self._snapshot, scoring_enabled=settings.capabilities.cometkiwi_enabled
        )
        self._refresh_header()
        self.settings_changed.emit(settings)

    def _refresh_header(self) -> None:
        parts = [describe_checks(self._settings)]
        last_pass = format_checked_at(self._snapshot.last_checked_at)
        if last_pass:
            parts.append(f"Последний проход: {last_pass}.")
        self.subtitle_label.setText(" ".join(parts))
        if self._busy:
            self.state_chip.set_state("Идёт проверка", "warning")
        else:
            self.state_chip.set_state("Готово к проверке", "success")

    def _update_action_state(self) -> None:
        busy = self._busy
        self.export_button.setEnabled(bool(self._snapshot.rows) and not busy)
        self.check_all_button.setEnabled(not busy)
        self.resume_button.setEnabled(not busy)
        self.resume_button.setVisible(not busy)
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setVisible(busy)

    def _request_export(self) -> None:
        """Ask where to write the report bundle, then hand the path over."""
        directory = QFileDialog.getExistingDirectory(self, "Куда сохранить отчёт", "")
        if directory:
            self.export_requested.emit(directory)

    def _request_check_chapter(self) -> None:
        chapter_id = self.selected_chapter_id()
        if chapter_id:
            self.check_chapter_requested.emit(chapter_id)

    def _request_undo_chapter(self, chapter_id: str = "") -> None:
        chapter_id = chapter_id or self.selected_chapter_id()
        if chapter_id and self._confirm_undo([chapter_id]):
            self.undo_chapter_requested.emit(chapter_id)

    def _request_undo_all(self) -> None:
        chapters = list(self._snapshot.repaired_chapters)
        if chapters and self._confirm_undo(chapters):
            self.undo_all_requested.emit()

    def _confirm_undo(self, chapters) -> bool:
        listing = "\n".join(f"  • {chapter}" for chapter in chapters[:20])
        if len(chapters) > 20:
            listing += f"\n  … и ещё {len(chapters) - 20}"
        answer = QMessageBox.question(
            self,
            "Отменить автоматические исправления",
            "Будут восстановлены исходные версии глав:\n"
            f"{listing}\n\nГлавы, изменённые вручную после исправления, "
            "останутся нетронутыми.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
