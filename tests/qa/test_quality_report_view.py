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
    view.resize(1400, 700)
    view.show()
    qt_app.processEvents()
    header = view.table.horizontalHeader()

    try:
        assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
        assert all(
            header.sectionResizeMode(column) == QHeaderView.ResizeMode.ResizeToContents
            for column in range(1, view.table.columnCount())
        )
    finally:
        view.close()


def _completeness_snapshot() -> BookQaReportSnapshot:
    journal = QaJournal.empty(book_id="book-1")
    for index in range(1010, 1020):
        chapter_id = f"OEBPS/chapter{index}.xhtml"
        journal.record_chapter_state(
            QaChapterState(chapter_id=chapter_id, status="checked", updated_at="2026-09-14T10:05:00")
        )
        journal.upsert_metrics(
            ChapterMetrics(
                chapter_id=chapter_id,
                source_language="zh",
                target_language="ru",
                source_chars=1000,
                translated_chars=3300,
                possible_gaps=2,
            )
        )
    return BookQaReportSnapshot.from_journal(journal)


def _settle(qt_app) -> None:
    # Column widths settle a turn after the resize that changed them.
    for _ in range(3):
        qt_app.processEvents()


def test_a_list_just_wider_than_its_numbers_keeps_the_chapter_names(qt_app):
    """Растянутая колонка «Глава» получала остаток ширины и сжималась до 16 пикселей."""
    view = QualityReportView()
    view.set_report(_completeness_snapshot())
    view.resize(1100, 600)
    view.show()
    _settle(qt_app)
    table = view.table
    header = table.horizontalHeader()
    others = sum(header.sectionSize(column) for column in range(1, table.columnCount()))
    name_width = table.fontMetrics().horizontalAdvance("chapter1019")
    frame = table.width() - table.viewport().width()

    table.setFixedWidth(others + name_width // 2 + frame)
    _settle(qt_app)

    try:
        assert header.sectionSize(0) >= name_width
    finally:
        view.close()


def test_the_totals_match_the_snapshot(qt_app):
    """Итоги были протоколом: «отложено 1, блокирует 0», «В главах: 409.»."""
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.checked_card.value_label.text() == "1 из 3"
    assert view.checked_card.detail_label.text() == (
        "1 глава отложена. 1 глава блокирует перевод."
    )
    assert view.repaired_card.value_label.text() == "2"
    assert view.repaired_card.detail_label.text() == "В 1 главе. Откатываются по главе."
    assert view.pending_card.value_label.text() == "0"
    assert view.pending_card.detail_label.text() == "Непринятых правок нет."
    # Leads to an empty state that explains itself; greyed out it looked broken.
    assert view.pending_card.action_button.isEnabled()


def test_the_totals_agree_with_their_numbers(qt_app):
    journal = QaJournal.empty(book_id="book-1")
    for index in range(1, 8):
        journal.record_chapter_state(
            QaChapterState(
                chapter_id=f"chapter-{index}",
                status="deferred" if index <= 5 else "checked",
            )
        )
    for index in range(1, 3):
        journal.append_repair({"patch_id": f"p-{index}", "chapter_id": f"chapter-{index}"})
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert view.checked_card.detail_label.text() == "5 глав отложено."
    assert view.repaired_card.detail_label.text() == "В 2 главах. Откатываются по главе."


def test_a_book_with_nothing_held_back_says_so(qt_app):
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_state(QaChapterState(chapter_id="chapter-1", status="checked"))
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal), scoring_enabled=True)

    assert view.checked_card.detail_label.text() == "Отложенных и блокирующих глав нет."
    assert view.repaired_card.detail_label.text() == "Автоисправлений пока нет."
    assert view.score_card.detail_label.text() == "Оценок пока нет."


def test_only_chapters_that_need_attention_are_coloured(qt_app):
    """Зелёной была вся колонка — и единственная «Отложена» терялась среди 483 строк."""
    from PyQt6.QtCore import Qt

    from gemini_translator.ui import theme_manager

    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.table.item(0, 1).data(Qt.ItemDataRole.ForegroundRole) is None
    assert view.table.item(1, 1).foreground().color().name() == theme_manager.color(
        "warning_text"
    )
    assert view.table.item(2, 1).foreground().color().name() == theme_manager.color(
        "danger_text"
    )


def test_status_colours_follow_a_theme_switch(qt_app):
    """Цвет вшивался в ячейку: после смены темы на лету «Отложена» почти не читалась."""
    from gemini_translator.ui import theme_manager

    theme_manager.apply(qt_app, mode="light", manual_colors={"accent": "#d87a3a"})
    view = QualityReportView()
    try:
        view.set_report(BookQaReportSnapshot.from_journal(_journal()))
        view.show()
        qt_app.processEvents()
        light = view.table.item(1, 1).foreground().color().name()

        theme_manager.apply(qt_app, mode="dark", manual_colors={"accent": "#d87a3a"})
        qt_app.processEvents()

        dark = view.table.item(1, 1).foreground().color().name()
        assert dark != light
        assert dark == theme_manager.color("warning_text")
    finally:
        view.close()
        view.deleteLater()
        qt_app.setStyleSheet("")
        for name in ("_theme_palette", "_active_theme_mode", "_glass_active"):
            if hasattr(qt_app, name):
                delattr(qt_app, name)
        qt_app.processEvents()


def test_the_chapter_that_needs_attention_is_chosen_first(qt_app):
    """Сразу после открытия правая половина пустовала: «Глава не выбрана»."""
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.selected_chapter_id() == "chapter-3"


def test_a_book_without_trouble_opens_on_its_first_chapter(qt_app):
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id in ("chapter-1", "chapter-2"):
        journal.record_chapter_state(QaChapterState(chapter_id=chapter_id, status="checked"))
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert view.selected_chapter_id() == "chapter-1"


def test_a_later_report_keeps_the_users_choice(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    view.select_chapter("chapter-1")

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.selected_chapter_id() == "chapter-1"


def test_the_chapter_card_follows_the_selection(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.select_chapter("chapter-1") is True
    assert view.chapter_title_label.text() == "chapter-1"
    assert view.chapter_meta_label.text() == (
        "Проверена 9 сентября 2026, 10:05, риск низкий. Исправлено автоматически: 2."
    )

    view.select_chapter("chapter-2")

    assert view.chapter_title_label.text() == "chapter-2"
    assert view.chapter_meta_label.text().startswith("Отложена 9 сентября 2026, 10:05")
    assert view.select_chapter("chapter-404") is False


def test_a_blocked_chapter_says_why(qt_app):
    class _Gate:
        chapter_id = "chapter-3"
        reason = "подтверждённый пропуск"

    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal(), [_Gate()]))

    view.select_chapter("chapter-3")

    assert view.table.item(2, 1).text() == "⛔ Блокирует"
    assert not view.chapter_block_chip.isHidden()
    assert view.chapter_block_chip.text() == "Перевод остановлен"
    assert view.chapter_block_chip.property("tone") == "danger"
    assert "Причина: подтверждённый пропуск" in view.chapter_details_label.text()

    view.select_chapter("chapter-1")

    assert view.chapter_block_chip.isHidden()


def test_actions_follow_the_selection_and_the_busy_state(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

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


def test_a_chapter_without_a_score_says_why(qt_app):
    """Оценка не получилась, а карточка главы молчала, как будто её и не просили."""
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_state(
        QaChapterState(chapter_id="chapter-1", status="checked", updated_at="2026-09-14T10:05:00")
    )
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-1",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=3000,
            quality_score_status="unavailable:endpoint_unreachable",
        )
    )
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(journal))
    view.select_chapter("chapter-1")

    assert "Оценка CometKiwi не получена: ПК не отвечает." in view.chapter_details_label.text()


def _remarks_journal() -> QaJournal:
    """Five chapters: two clean, one deferred, one with a waiting fix, one with possible gaps."""
    from gemini_translator.qa.models import QaSuggestion

    journal = QaJournal.empty(book_id="book-1")
    for chapter_id, status in (
        ("chapter-1", "checked"),
        ("chapter-2", "checked"),
        ("chapter-3", "deferred"),
        ("chapter-4", "checked"),
        ("chapter-5", "checked"),
    ):
        journal.record_chapter_state(
            QaChapterState(chapter_id=chapter_id, status=status, updated_at="2026-09-14T10:05:00")
        )
    journal.suggestions.append(
        QaSuggestion(
            suggestion_id=QaSuggestion.identity("chapter-2", "n.1", "сразу ушёл", "тут же ушёл"),
            chapter_id="chapter-2",
            block_id="n.1",
            category="calque",
            original_text="сразу ушёл",
            replacement_text="тут же ушёл",
        )
    )
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-4",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=3000,
            possible_gaps=2,
        )
    )
    return journal


def _visible_chapters(view: QualityReportView) -> list[str]:
    from PyQt6.QtCore import Qt

    return [
        view.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(view.table.rowCount())
    ]


def test_the_remarks_toggle_leaves_only_the_chapters_that_want_a_look(qt_app):
    """Среди сотен чистых глав терялись те немногие, что требуют внимания."""
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_remarks_journal()))

    assert view.remarks_only_check.isChecked() is False
    assert view.remarks_only_check.text() == "Только с замечаниями (3)"
    assert _visible_chapters(view) == [
        "chapter-1",
        "chapter-2",
        "chapter-3",
        "chapter-4",
        "chapter-5",
    ]

    view.remarks_only_check.setChecked(True)

    assert _visible_chapters(view) == ["chapter-2", "chapter-3", "chapter-4"]

    view.remarks_only_check.setChecked(False)

    assert len(_visible_chapters(view)) == 5


def test_auto_fixes_and_a_held_translation_are_remarks_too(qt_app):
    class _Gate:
        chapter_id = "chapter-5"
        reason = "подтверждённый пропуск"

    journal = _remarks_journal()
    journal.append_repair({"patch_id": "lang-1", "chapter_id": "chapter-1"})
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(journal, [_Gate()]))

    view.remarks_only_check.setChecked(True)

    assert view.remarks_only_check.text() == "Только с замечаниями (5)"
    assert _visible_chapters(view) == [
        "chapter-1",
        "chapter-2",
        "chapter-3",
        "chapter-4",
        "chapter-5",
    ]


def test_a_hidden_selection_moves_to_the_first_visible_chapter(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_remarks_journal()))
    view.select_chapter("chapter-1")

    view.remarks_only_check.setChecked(True)

    assert view.selected_chapter_id() == "chapter-2"
    assert view.chapter_title_label.text() == "chapter-2"

    view.select_chapter("chapter-4")
    view.remarks_only_check.setChecked(False)
    view.remarks_only_check.setChecked(True)

    assert view.selected_chapter_id() == "chapter-4"


def test_a_book_without_remarks_says_so_instead_of_an_empty_list(qt_app):
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id in ("chapter-1", "chapter-2"):
        journal.record_chapter_state(QaChapterState(chapter_id=chapter_id, status="checked"))
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(journal))

    view.remarks_only_check.setChecked(True)

    assert view.remarks_only_check.text() == "Только с замечаниями (0)"
    assert view.table.isHidden()
    assert not view.no_remarks_state.isHidden()
    assert view.no_remarks_state.title_label.text() == "Замечаний нет"
    assert view.selected_chapter_id() == ""
    assert view.chapter_title_label.text() == "Глава не выбрана"

    view.remarks_only_check.setChecked(False)

    assert not view.table.isHidden()
    assert view.no_remarks_state.isHidden()
    assert view.selected_chapter_id() == "chapter-1"


def test_the_filter_stays_on_as_the_pass_reports_each_chapter(qt_app):
    """Отчёт обновляется после каждой главы, и переключатель не должен сбрасываться."""
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_remarks_journal()))
    view.remarks_only_check.setChecked(True)
    journal = _remarks_journal()
    journal.append_repair({"patch_id": "lang-9", "chapter_id": "chapter-5"})

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert view.remarks_only_check.isChecked() is True
    assert view.remarks_only_check.text() == "Только с замечаниями (4)"
    assert _visible_chapters(view) == ["chapter-2", "chapter-3", "chapter-4", "chapter-5"]


def test_status_colours_follow_a_theme_switch_in_a_filtered_list(qt_app):
    """С фильтром в таблице меньше строк, чем глав, и перекраска не должна на этом сдаваться."""
    from gemini_translator.ui import theme_manager

    theme_manager.apply(qt_app, mode="light", manual_colors={"accent": "#d87a3a"})
    view = QualityReportView()
    try:
        view.set_report(BookQaReportSnapshot.from_journal(_remarks_journal()))
        view.remarks_only_check.setChecked(True)
        view.show()
        qt_app.processEvents()
        deferred = _visible_chapters(view).index("chapter-3")
        light = view.table.item(deferred, 1).foreground().color().name()

        theme_manager.apply(qt_app, mode="dark", manual_colors={"accent": "#d87a3a"})
        qt_app.processEvents()

        dark = view.table.item(deferred, 1).foreground().color().name()
        assert dark != light
        assert dark == theme_manager.color("warning_text")
    finally:
        view.close()
        view.deleteLater()
        qt_app.setStyleSheet("")
        for name in ("_theme_palette", "_active_theme_mode", "_glass_active"):
            if hasattr(qt_app, name):
                delattr(qt_app, name)
        qt_app.processEvents()
