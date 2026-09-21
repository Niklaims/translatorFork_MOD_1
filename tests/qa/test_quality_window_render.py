"""The real window, drawn offscreen in both themes, never cuts a wrapped caption."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.qa.capabilities import QaCapabilitySettings
from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, QaChapterState
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui import theme_manager
from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog


_THEME_ATTRIBUTES = ("_theme_palette", "_active_theme_mode", "_glass_active")


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def themed(qt_app):
    """Apply a theme for one test and leave the application as it found it."""

    def apply(mode: str) -> None:
        theme_manager.apply(qt_app, mode=mode, manual_colors={"accent": "#d87a3a"})

    yield apply
    theme_manager.set_app_stylesheet(qt_app, "")
    for name in _THEME_ATTRIBUTES:
        if hasattr(qt_app, name):
            delattr(qt_app, name)


def _journal() -> QaJournal:
    journal = QaJournal.empty(book_id="book-1")
    for index in range(1, 13):
        journal.record_chapter_state(
            QaChapterState(
                chapter_id=f"chapter-{index}",
                status="deferred" if index == 3 else "checked",
                updated_at="2026-09-09T10:05:00",
            )
        )
    for index in range(1, 6):
        journal.append_repair({"patch_id": f"lang-{index}", "chapter_id": f"chapter-{index}"})
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-2",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=2900,
            quality_score=0.81,
            quality_score_status="scored",
        )
    )
    from gemini_translator.qa.models import QaSuggestion

    samples = (
        ("— Спросил он, глядя в окно.", "— спросил он, глядя в окно.", "pending", "validation_declined"),
        ("Он очень-очень устал после долгой дороги.", "", "pending", "no_replacement"),
        ("Трое из них был ранены.", "Трое из них были ранены.", "stale", "low_confidence (0.62 < 0.85)"),
    )
    journal.suggestions.extend(
        QaSuggestion(
            suggestion_id=QaSuggestion.identity("chapter-2", "n.1", before, after),
            chapter_id="chapter-2",
            block_id="n.1",
            category="punctuation",
            original_text=before,
            replacement_text=after,
            reason=reason,
            explanation="Модель считает правку спорной и оставляет решение человеку.",
            status=status,
            status_note="глава изменилась после проверки" if status == "stale" else "",
        )
        for before, after, status, reason in samples
    )
    return journal


def _cut_captions(dialog, qt_app) -> list[tuple]:
    cut = []
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        qt_app.processEvents()
        for label in dialog.findChildren(QtWidgets.QLabel):
            if not (label.wordWrap() and label.isVisible() and label.text()):
                continue
            needed = label.heightForWidth(label.width())
            if label.height() < needed:
                cut.append(
                    (dialog.tabs.tabText(index), label.objectName(), label.text()[:40], label.height(), needed)
                )
    return cut


def _show(dialog, qt_app) -> None:
    dialog.resize(1180, 860)
    dialog.show()
    qt_app.processEvents()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_no_wrapped_caption_is_cut_in_a_full_window(qt_app, themed, mode):
    themed(mode)
    dialog = TranslationQualityDialog(
        settings=QaSettings(
            embedding_provider="gemini",
            embedding_key_provider="gemini",
            capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
        ),
        key_counter=lambda provider_id, model_id: (5, 7),
        book_title="Выиграв счастливую звезду, я попал в мир Star Rail",
    )
    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    dialog.set_status(
        "Проверено глав: 12 из 12. Ключи для проверки больше недоступны — "
        "продолжите проверку, когда они восстановятся."
    )
    try:
        _show(dialog, qt_app)
        dialog.select_chapter("chapter-2")
        assert _cut_captions(dialog, qt_app) == []
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_no_wrapped_caption_is_cut_in_an_empty_window(qt_app, themed, mode):
    themed(mode)
    dialog = TranslationQualityDialog(book_title="AI")
    dialog.set_report(BookQaReportSnapshot())
    try:
        _show(dialog, qt_app)
        assert _cut_captions(dialog, qt_app) == []
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_the_action_bar_keeps_its_height_when_a_pass_starts(qt_app, themed):
    """«Остановить» без отступов главной кнопки сдвигало всё окно на 4 px при каждом старте."""
    themed("light")
    dialog = TranslationQualityDialog()
    try:
        _show(dialog, qt_app)
        bar = dialog.cancel_button.parentWidget()
        idle = bar.height()

        dialog.set_busy(True)
        qt_app.processEvents()

        assert bar.height() == idle
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_waiting_fixes_are_shown_one_at_a_time(qt_app, themed):
    """Правки главы листаются по одной, а не прокручиваются столбиком в узком окне."""
    themed("light")
    dialog = TranslationQualityDialog(book_title="AI")
    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    try:
        _show(dialog, qt_app)
        dialog.select_chapter("chapter-2")
        qt_app.processEvents()
        view = dialog.report_view
        carousel = view.pending_carousel

        assert carousel.isVisible()
        assert carousel.counter_label.text() == "1 из 3"
        assert carousel.geometry().bottom() < view.check_chapter_button.geometry().top()
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_a_chapter_with_nothing_waiting_keeps_its_text_together(qt_app, themed):
    """Пока списка правок нет, распорка держит кнопки внизу, а подписи не расползаются по карточке."""
    themed("light")
    dialog = TranslationQualityDialog(book_title="AI")
    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    try:
        _show(dialog, qt_app)
        dialog.select_chapter("chapter-1")
        qt_app.processEvents()
        view = dialog.report_view

        stretched = [
            (label.text()[:20], label.height(), label.heightForWidth(label.width()))
            for label in (view.chapter_title_label, view.chapter_meta_label)
            if label.height() > label.heightForWidth(label.width()) + 1
        ]

        assert not view.pending_carousel.isVisible()
        assert stretched == []
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_the_chapter_card_scrolls_rather_than_squeezes_in_a_short_window(qt_app, themed):
    """В окне минимального размера строки нормы наезжали друг на друга, а правка сжималась в пустую рамку."""
    themed("light")
    dialog = TranslationQualityDialog(book_title="AI")
    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    try:
        dialog.resize(dialog.minimumSize())
        dialog.show()
        dialog.select_chapter("chapter-2")
        # Heights settle a turn after the resize that changed them.
        for _ in range(3):
            qt_app.processEvents()
        view = dialog.report_view
        cut = [
            (label.text()[:30], label.height(), label.heightForWidth(label.width()))
            for label in view.chapter_card.findChildren(QtWidgets.QLabel)
            if label.wordWrap()
            and label.isVisible()
            and label.text()
            and label.height() < label.heightForWidth(label.width())
        ]
        card = view.pending_carousel.current_card()
        needed = (
            card.heightForWidth(card.width()) if card.hasHeightForWidth() else card.sizeHint().height()
        )

        assert cut == []
        assert card.height() >= needed
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_the_chapter_list_takes_the_wider_share_of_the_window(qt_app, themed):
    """С оценками у всех глав колонка «Оценка» уезжала под прокрутку: таблице отдана большая доля.

    Share, not pixels: the columns are as wide as the platform's font makes them,
    and on Windows CI the same seven measured 943 px against 726 on macOS.
    """
    themed("light")
    journal = QaJournal.empty(book_id="book-1")
    for index in range(1000, 1030):
        chapter_id = f"OEBPS/chapter{index}.xhtml"
        journal.record_chapter_state(
            QaChapterState(chapter_id=chapter_id, status="checked", updated_at="2026-09-14T13:31:00")
        )
        journal.upsert_metrics(
            ChapterMetrics(
                chapter_id=chapter_id,
                source_language="zh",
                target_language="ru",
                source_chars=1400,
                translated_chars=4400,
                possible_gaps=index % 5,
                quality_estimator="cometkiwi",
                quality_score=0.74,
                quality_score_status="completed",
            )
        )
    settings = QaSettings(
        check_language_after_chapter=True,
        check_completeness_after_chapter=True,
        capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
    )
    dialog = TranslationQualityDialog(settings=settings, book_title="Король Демонов")
    dialog.set_report(BookQaReportSnapshot.from_journal(journal))
    try:
        dialog.resize(dialog.sizeHint())
        dialog.show()
        dialog.select_chapter("OEBPS/chapter1006.xhtml")
        # Column widths settle a turn after the resize that changed them.
        for _ in range(3):
            qt_app.processEvents()
        table = dialog.report_view.table

        assert table.columnCount() == 7
        assert table.parentWidget().width() > dialog.report_view.chapter_card.width()
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()
