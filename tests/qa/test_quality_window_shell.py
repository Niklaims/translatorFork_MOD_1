"""The window shell: a header, four tabs, one primary action, and a honest busy state."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QMessageBox

from gemini_translator.qa.capabilities import QaCapabilitySettings
from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, QaChapterState
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog
from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_dialog import (
    describe_checks,
)


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


def test_the_window_asks_for_more_room_than_its_minimum(qt_app):
    """Окно открывалось почти на минимуме: список глав и карточка правки теснились."""
    dialog = TranslationQualityDialog()

    hint = dialog.sizeHint()

    assert hint.width() >= 1400
    assert hint.height() >= 960
    assert hint.width() > dialog.minimumWidth()
    assert hint.height() > dialog.minimumHeight()


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


def test_the_log_starts_with_an_empty_state_and_then_shows_entries(qt_app):
    """Журнал в рамке в рамке забирал фокус и обводил всю вкладку оранжевым."""
    from PyQt6.QtCore import Qt

    dialog = TranslationQualityDialog()

    assert dialog.log_stack.currentWidget() is dialog.log_empty_state
    assert dialog.log_view.document().maximumBlockCount() == 4000
    assert dialog.log_view.focusPolicy() == Qt.FocusPolicy.ClickFocus

    dialog.append_log("<p><b>chapter-1</b> — без изменений.</p>")
    dialog.append_log("<p><b>chapter-2</b> — без изменений.</p>")

    assert dialog.log_stack.currentWidget() is dialog.log_view
    assert "<hr" not in dialog.log_view.toHtml()
    lines = [line for line in dialog.log_view.toPlainText().splitlines() if line.strip()]
    assert lines == ["chapter-1 — без изменений.", "chapter-2 — без изменений."]


def test_a_running_pass_reports_progress_in_the_status_line(qt_app):
    """Все часы прохода слева висело «Готово.», а числа прятались в узкой полосе."""
    dialog = _dialog()

    dialog.set_busy(True)
    dialog.set_progress(12, 484, "осталось ~40 мин · chapter13")

    assert dialog.status_label.text() == "Проход: 12 из 484 · осталось ~40 мин · chapter13"
    assert dialog.progress.isTextVisible() is False
    assert "Последний проход" not in dialog.subtitle_label.text()

    dialog.set_busy(False)

    assert "Последний проход" in dialog.subtitle_label.text()


def test_stopping_says_so_until_the_pass_ends(qt_app):
    dialog = _dialog()
    stops: list[int] = []
    dialog.cancel_requested.connect(lambda: stops.append(1))
    dialog.set_busy(True)

    dialog.cancel_button.click()

    assert stops == [1]
    assert dialog.cancel_button.text() == "Останавливаю…"
    assert not dialog.cancel_button.isEnabled()

    dialog.set_busy(False)
    dialog.set_busy(True)

    assert dialog.cancel_button.text() == "Остановить проверку"
    assert dialog.cancel_button.isEnabled()


def _snapshot_with_suggestions():
    from gemini_translator.qa.models import QaSuggestion

    journal = QaJournal.empty(book_id="book-1")
    suggestions = tuple(
        QaSuggestion(
            suggestion_id=QaSuggestion.identity("chapter-1", "n.1", before, after),
            chapter_id="chapter-1",
            block_id="n.1",
            category="punctuation",
            original_text=before,
            replacement_text=after,
            reason="validation_declined",
        )
        for before, after in (
            ("— Спросил он.", "— спросил он."),
            ("Он очень-очень устал.", "Он очень устал."),
        )
    )
    journal.record_chapter_result(
        state=QaChapterState(chapter_id="chapter-1", status="checked"),
        suggestions=suggestions,
    )
    journal.record_chapter_state(QaChapterState(chapter_id="chapter-2", status="checked"))
    return BookQaReportSnapshot.from_journal(journal), suggestions


def test_the_tab_counts_the_suggestions_waiting(qt_app):
    snapshot, _suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()

    dialog.set_report(snapshot)
    assert dialog.tabs.tabText(1) == "Предложения (2)"
    assert len(dialog.suggestions_view.cards) == 2

    dialog.set_report(BookQaReportSnapshot())
    assert dialog.tabs.tabText(1) == "Предложения"


def test_the_chapter_card_lists_that_chapters_suggestions(qt_app):
    snapshot, _suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()
    dialog.set_report(snapshot)

    dialog.select_chapter("chapter-1")
    assert dialog.report_view.pending_title_label.text() == "Ждут решения: 2"
    assert len(dialog.report_view.pending_carousel.cards) == 2

    dialog.select_chapter("chapter-2")
    assert dialog.report_view.pending_title_label.isHidden()
    assert dialog.report_view.pending_carousel.cards == []


def test_both_tabs_ask_the_window_to_apply_or_dismiss(qt_app):
    snapshot, suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()
    dialog.set_report(snapshot)
    applied: list[str] = []
    dismissed: list[str] = []
    dialog.apply_suggestion_requested.connect(applied.append)
    dialog.dismiss_suggestion_requested.connect(dismissed.append)

    dialog.suggestions_view.cards[0].apply_button.click()
    dialog.select_chapter("chapter-1")
    carousel = dialog.report_view.pending_carousel
    carousel.show_next()
    carousel.current_card().dismiss_button.click()

    assert applied == [dialog.suggestions_view.cards[0].suggestion.suggestion_id]
    assert dismissed == [carousel.current_suggestion_id()]
    assert set(applied + dismissed) <= {item.suggestion_id for item in suggestions}


def test_a_running_pass_locks_only_the_chapter_it_is_checking(qt_app):
    """Правки ждали конца многочасового прохода; теперь закрыта только проверяемая глава."""
    snapshot, _suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()
    dialog.set_report(snapshot)
    dialog.select_chapter("chapter-1")
    cards = dialog.suggestions_view.cards + dialog.report_view.pending_carousel.cards

    dialog.set_busy(True)
    dialog.set_checking_chapters(frozenset({"chapter-2"}))

    assert cards
    assert all(card.apply_button.isEnabled() and card.dismiss_button.isEnabled() for card in cards)

    dialog.set_checking_chapters(frozenset({"chapter-1"}))

    assert not any(card.apply_button.isEnabled() for card in cards)
    assert all(card.dismiss_button.isEnabled() for card in cards)


@pytest.mark.parametrize(
    ("completeness", "text"),
    [
        (False, "После каждой главы: язык."),
        (True, "После каждой главы: язык, полнота, оценка CometKiwi."),
    ],
)
def test_the_header_promises_cometkiwi_only_where_it_runs(completeness, text):
    """CometKiwi оценивает то, что сопоставила проверка полноты, и без неё не запускается."""
    settings = QaSettings(
        check_language_after_chapter=True,
        check_completeness_after_chapter=completeness,
        capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
    )

    assert describe_checks(settings) == text


def test_the_score_card_waits_for_the_completeness_check(qt_app):
    """Без проверки полноты «Оценок пока нет» висело бы в карточке вечно."""
    kiwi = QaCapabilitySettings(cometkiwi_enabled=True)
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_state(
        QaChapterState(chapter_id="chapter-1", status="checked", updated_at="2026-09-09T10:05:00")
    )
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-1",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=2900,
            quality_score=0.81,
            quality_score_status="scored",
        )
    )

    without_completeness = _dialog(
        settings=QaSettings(check_completeness_after_chapter=False, capabilities=kiwi)
    )
    with_completeness = _dialog(
        settings=QaSettings(check_completeness_after_chapter=True, capabilities=kiwi)
    )
    with_old_scores = TranslationQualityDialog(
        settings=QaSettings(check_completeness_after_chapter=False, capabilities=kiwi)
    )
    with_old_scores.set_report(BookQaReportSnapshot.from_journal(journal))

    assert without_completeness.report_view.score_card.isHidden()
    assert not with_completeness.report_view.score_card.isHidden()
    assert not with_old_scores.report_view.score_card.isHidden()
