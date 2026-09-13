"""The window shell: a header, four tabs, one primary action, and a honest busy state."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QMessageBox

from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import QaChapterState
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _snapshot() -> BookQaReportSnapshot:
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id in ("chapter-1", "chapter-2"):
        journal.record_chapter_state(
            QaChapterState(
                chapter_id=chapter_id, status="checked", updated_at="2026-09-09T10:05:00"
            )
        )
    journal.append_repair({"patch_id": "lang-1", "chapter_id": "chapter-1"})
    return BookQaReportSnapshot.from_journal(journal)


def _dialog(**kwargs) -> TranslationQualityDialog:
    dialog = TranslationQualityDialog(**kwargs)
    dialog.set_report(_snapshot())
    return dialog


def test_the_window_offers_its_actions_and_tabs_by_name(qt_app):
    dialog = TranslationQualityDialog()

    assert dialog.check_all_button.text() == "Проверить все главы"
    assert dialog.resume_button.text() == "Продолжить проверку"
    assert dialog.export_button.text() == "Экспорт отчёта"
    assert dialog.cancel_button.text() == "Остановить проверку"
    assert dialog.close_button.text() == "Закрыть"
    assert dialog.report_view.check_chapter_button.text() == "Проверить главу"
    assert dialog.report_view.undo_chapter_button.text() == "Отменить исправления главы"
    assert dialog.report_view.undo_all_button.text() == "Отменить все автоисправления книги"
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "Отчёт",
        "Предложения",
        "Журнал правок",
        "Настройки",
    ]


def test_there_is_exactly_one_primary_action(qt_app):
    dialog = _dialog()

    primary = [
        button
        for button in dialog.findChildren(QtWidgets.QPushButton)
        if button.objectName() == "primaryActionButton"
    ]

    assert primary == [dialog.resume_button]


def test_a_running_pass_swaps_resume_for_stop_and_locks_the_rest(qt_app):
    dialog = _dialog()
    dialog.select_chapter("chapter-1")

    dialog.set_busy(True)

    assert dialog.resume_button.isHidden()
    assert not dialog.cancel_button.isHidden()
    assert dialog.cancel_button.isEnabled()
    assert not dialog.check_all_button.isEnabled()
    assert not dialog.export_button.isEnabled()
    assert not dialog.report_view.check_chapter_button.isEnabled()
    assert not dialog.report_view.undo_all_button.isEnabled()
    assert dialog.state_chip.text() == "Идёт проверка"
    assert dialog.state_chip.property("tone") == "warning"

    dialog.set_busy(False)

    assert not dialog.resume_button.isHidden()
    assert dialog.cancel_button.isHidden()
    assert dialog.report_view.check_chapter_button.isEnabled()
    assert dialog.state_chip.text() == "Готово к проверке"


def test_the_header_names_the_book_the_checks_and_the_last_pass(qt_app):
    dialog = _dialog(
        settings=QaSettings(check_completeness_after_chapter=False),
        book_title="Star Rail",
    )

    assert dialog.title_label.text() == "Star Rail"
    assert dialog.subtitle_label.text() == (
        "После каждой главы: язык. Последний проход: 9 сентября 2026, 10:05."
    )


def test_the_status_line_and_the_probe_answer_land_where_they_belong(qt_app):
    dialog = TranslationQualityDialog()

    dialog.set_status("Отчёт сохранён.")
    dialog.set_embedding_result("Подключение работает.")

    assert dialog.status_label.text() == "Отчёт сохранён."
    assert dialog.settings_view.embedding_result_label.text() == "Подключение работает."


def test_open_suggestions_switches_the_tab(qt_app):
    dialog = _dialog()

    dialog.report_view.open_suggestions_requested.emit()

    assert dialog.tabs.currentWidget() is dialog.suggestions_view


def test_an_edit_in_the_settings_tab_is_published_by_the_window(qt_app):
    dialog = TranslationQualityDialog(settings=QaSettings())
    published: list[QaSettings] = []
    dialog.settings_changed.connect(published.append)

    dialog.settings_view.language_check.setChecked(False)

    assert published[-1].check_language_after_chapter is False
    assert dialog.qa_settings().check_language_after_chapter is False
    assert dialog.subtitle_label.text().startswith("После каждой главы: полнота")


def test_turning_scoring_on_shows_the_score_card(qt_app):
    dialog = _dialog()
    assert dialog.report_view.score_card.isHidden()

    dialog.settings_view.cometkiwi_enabled_check.setChecked(True)

    assert not dialog.report_view.score_card.isHidden()


def test_undo_asks_before_it_restores(qt_app, monkeypatch):
    dialog = _dialog()
    dialog.select_chapter("chapter-1")
    undone: list[str] = []
    dialog.undo_chapter_requested.connect(undone.append)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    dialog.report_view.undo_chapter_button.click()
    assert undone == []

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    dialog.report_view.undo_chapter_button.click()
    assert undone == ["chapter-1"]


def test_the_suggestions_tab_says_why_it_is_empty(qt_app):
    dialog = TranslationQualityDialog()

    assert dialog.suggestions_view.empty_state.title_label.text() == "Непринятых правок нет"


def test_the_log_sits_in_a_card_and_stays_bounded(qt_app):
    dialog = TranslationQualityDialog()

    assert dialog.log_view.parentWidget().objectName() == "projectPathCard"
    assert dialog.log_view.document().maximumBlockCount() == 4000
