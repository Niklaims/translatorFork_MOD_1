"""The report tab: totals, a chapter list that fits the data, and the chosen chapter."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, QaChapterState
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot
from gemini_translator.ui.dialogs.validation_dialogs.quality_report_view import (
    QualityReportView,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _journal() -> QaJournal:
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id, status in (
        ("chapter-1", "checked"),
        ("chapter-2", "deferred"),
        ("chapter-3", "blocked"),
    ):
        journal.record_chapter_state(
            QaChapterState(
                chapter_id=chapter_id, status=status, updated_at="2026-09-09T10:05:00"
            )
        )
    journal.append_repair({"patch_id": "lang-1", "chapter_id": "chapter-1"})
    journal.append_repair({"patch_id": "lang-2", "chapter_id": "chapter-1"})
    return journal


def _headers(view: QualityReportView) -> list[str]:
    return [
        view.table.horizontalHeaderItem(index).text()
        for index in range(view.table.columnCount())
    ]


def test_the_totals_match_the_snapshot(qt_app):
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.checked_card.value_label.text() == "1 из 3"
    assert view.checked_card.detail_label.text() == "отложено 1, блокирует 1"
    assert view.repaired_card.value_label.text() == "2"
    assert view.repaired_card.detail_label.text() == "В главах: 1."
    assert view.pending_card.value_label.text() == "0"
    assert not view.pending_card.action_button.isEnabled()


def test_a_language_only_book_shows_the_four_base_columns(qt_app):
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert _headers(view) == ["Глава", "Статус", "Исправлено", "Ждут решения"]
    assert view.table.rowCount() == 3
    assert view.table.item(0, 1).text() == "Проверена"
    assert view.table.item(0, 2).text() == "2"
    assert view.table.item(1, 2).text() == ""


def test_completeness_and_score_columns_appear_only_with_their_data(qt_app):
    journal = _journal()
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-1",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=2900,
            quality_score=0.83,
            quality_score_status="scored",
        )
    )
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert _headers(view) == [
        "Глава",
        "Статус",
        "Исправлено",
        "Ждут решения",
        "Длина",
        "Пропуски",
        "Оценка",
    ]
    assert view.table.item(0, 4).text() == "2.90"
    assert view.table.item(0, 6).text() == "0.83"
    assert view.table.item(1, 4).text() == "—"


def test_the_status_colour_is_the_readable_status_token(qt_app):
    from gemini_translator.ui import theme_manager

    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.table.item(0, 1).foreground().color().name() == theme_manager.color(
        "success_text"
    )
    assert view.table.item(2, 1).foreground().color().name() == theme_manager.color(
        "danger_text"
    )


def test_the_chapter_card_follows_the_selection(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.chapter_title_label.text() == "Глава не выбрана"
    assert view.select_chapter("chapter-1") is True
    assert view.selected_chapter_id() == "chapter-1"
    assert view.chapter_title_label.text() == "chapter-1"
    assert view.chapter_meta_label.text() == (
        "Проверена · 9 сентября 2026, 10:05 · риск: низкий · "
        "исправлено автоматически: 2"
    )

    view.select_chapter("chapter-2")

    assert view.chapter_title_label.text() == "chapter-2"
    assert view.select_chapter("chapter-404") is False


def test_a_blocked_chapter_says_why(qt_app):
    class _Gate:
        chapter_id = "chapter-3"
        reason = "подтверждённый пропуск"

    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal(), [_Gate()]))

    view.select_chapter("chapter-3")

    assert view.table.item(2, 1).text() == "⛔ Блокирует"
    assert "Перевод остановлен: подтверждённый пропуск" in view.chapter_details_label.text()


def test_actions_follow_the_selection_and_the_busy_state(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert not view.check_chapter_button.isEnabled()
    assert view.undo_all_button.isEnabled()
    view.select_chapter("chapter-2")
    assert view.check_chapter_button.isEnabled()
    assert not view.undo_chapter_button.isEnabled()
    view.select_chapter("chapter-1")
    assert view.undo_chapter_button.isEnabled()

    view.set_busy(True)

    assert not view.check_chapter_button.isEnabled()
    assert not view.undo_chapter_button.isEnabled()
    assert not view.undo_all_button.isEnabled()


def test_the_buttons_ask_for_what_is_selected(qt_app):
    view = QualityReportView()
    checks: list[str] = []
    undos: list[str] = []
    everything: list[int] = []
    opened: list[int] = []
    view.check_chapter_requested.connect(checks.append)
    view.undo_chapter_requested.connect(undos.append)
    view.undo_all_requested.connect(lambda: everything.append(1))
    view.open_suggestions_requested.connect(lambda: opened.append(1))
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    view.select_chapter("chapter-1")

    view.check_chapter_button.click()
    view.undo_chapter_button.click()
    view.undo_all_button.click()
    view.pending_card.action_clicked.emit()

    assert checks == ["chapter-1"]
    assert undos == ["chapter-1"]
    assert everything == [1]
    assert opened == [1]


def test_an_empty_report_shows_the_empty_state(qt_app):
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot())
    assert view.stack.currentWidget() is view.empty_state
    assert view.empty_state.title_label.text() == "Отчёт пока пуст"

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    assert view.stack.currentWidget() is view.content


def test_the_score_card_shows_only_when_scoring_is_on(qt_app):
    view = QualityReportView()
    snapshot = BookQaReportSnapshot.from_journal(_journal())

    view.set_report(snapshot)
    assert view.score_card.isHidden()

    view.set_report(snapshot, scoring_enabled=True)
    assert not view.score_card.isHidden()
    assert view.score_card.value_label.text() == "—"


def test_an_unchanged_report_does_not_rebuild_the_table(qt_app):
    """Проход обновляет отчёт каждые несколько секунд; пересборка на 600 глав — рывок."""
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    first = view.table.item(0, 0)

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.table.item(0, 0) is first


def test_a_rebuilt_table_keeps_the_selected_chapter(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    view.select_chapter("chapter-2")
    journal = _journal()
    journal.append_repair({"patch_id": "lang-3", "chapter_id": "chapter-2"})

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert view.selected_chapter_id() == "chapter-2"
    assert view.table.item(1, 2).text() == "1"


def test_six_hundred_chapters_fill_the_table(qt_app):
    journal = QaJournal.empty(book_id="book-1")
    for index in range(600):
        journal.record_chapter_state(
            QaChapterState(chapter_id=f"chapter-{index}", status="checked")
        )
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert view.table.rowCount() == 600
    assert view.table.item(599, 0).text() == "chapter-599"


def test_only_a_snapshot_reaches_the_table(qt_app):
    """A live DataFrame from a background thread must never reach the table."""
    with pytest.raises(TypeError):
        QualityReportView().set_report({"rows": []})


def test_a_chapter_path_is_shown_by_its_file_name(qt_app):
    """Настоящие главы — пути вида OEBPS/chapter12.xhtml, и все 484 строки выглядели одинаково."""
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id in ("OEBPS/chapter12.xhtml", "OEBPS/chapter2.xhtml"):
        journal.record_chapter_state(QaChapterState(chapter_id=chapter_id, status="checked"))
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    first = view.table.item(0, 0)
    assert first.text() == "chapter2"
    assert first.toolTip() == "OEBPS/chapter2.xhtml"
    assert view.select_chapter("OEBPS/chapter12.xhtml")
    assert view.selected_chapter_id() == "OEBPS/chapter12.xhtml"
    assert view.chapter_title_label.text() == "chapter12"
    assert view.chapter_path_label.text() == "OEBPS/chapter12.xhtml"
    assert not view.chapter_path_label.isHidden()


def test_a_chapter_without_a_folder_shows_no_path_line(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    view.select_chapter("chapter-1")

    assert view.chapter_path_label.isHidden()


def test_the_chapter_column_takes_the_spare_width(qt_app):
    from PyQt6.QtWidgets import QHeaderView

    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    header = view.table.horizontalHeader()

    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert all(
        header.sectionResizeMode(column) == QHeaderView.ResizeMode.ResizeToContents
        for column in range(1, view.table.columnCount())
    )

