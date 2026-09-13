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
    qt_app.setStyleSheet("")
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

