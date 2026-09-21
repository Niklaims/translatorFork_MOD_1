"""Фон строк таблиц и списков под таблицей стилей темы.

Правило темы ``QTableWidget::item, QListWidget::item { border-radius; margin; ... }``
заставляет QStyleSheetStyle рисовать элемент самому, мимо кисти из модели:
``setBackground`` у элементов молча пропадает. Тесты рисуют окна offscreen
под настоящей темой и читают пиксели.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GT_DISABLE_LOCAL_MODEL_DISCOVERY", "1")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from main import EventBus
from gemini_translator.ui.widgets.glossary_widget import GlossaryWidget  # noqa: F401
from gemini_translator.ui.dialogs import chapter_editor
from gemini_translator.ui.dialogs.consistency_checker import ConsistencyValidatorPage
from gemini_translator.ui.dialogs.epub import EpubHtmlSelectorDialog
from gemini_translator.ui.dialogs.glossary import GlossaryManagerPage
from gemini_translator.ui.dialogs.glossary_dialogs.ai_correction import CorrectionPreviewDialog
from gemini_translator.ui.dialogs.glossary_dialogs.conflict_resolvers import (
    ComplexOverlapResolverPage,
    ReverseConflictResolverPage,
)
from gemini_translator.ui.dialogs.glossary_dialogs.core_term_dialog import CoreTermAnalyzerPage
from gemini_translator.ui.dialogs.glossary_dialogs.term_frequency_analyzer import (
    TermFrequencyAnalyzerPage,
)
from gemini_translator.ui.dialogs.glossary_dialogs.versioning import ChapterSelectorWidget
from gemini_translator.ui.dialogs.validation import (
    AIRepairReviewPage,
    TranslationValidatorPage,
    build_line_review_segments,
)
from gemini_translator.ui.dialogs.validation_dialogs.untranslated_fixer_dialog import (
    UntranslatedFixerPage,
)
from gemini_translator.ui import theme_manager
from gemini_translator.ui.item_background import ItemBackgroundDelegate
from gemini_translator.ui.themes import ITEM_MARGIN_X, ITEM_MARGIN_Y, _contrast_ratio
from gemini_translator.utils.settings import SettingsManager


_THEME_ATTRIBUTES = ("_theme_palette", "_active_theme_mode", "_glass_active")

# Таблица стилей различается у macOS и остальных систем (блоки
# «macOS Table Overrides» и «Windows/Linux Table Overrides» в themes.py).
STYLE_VARIANTS = ("darwin", "win32")
SCHEMES = ("light", "dark")
THEMES = [
    pytest.param(variant, scheme, id=f"{variant}-{scheme}")
    for variant in STYLE_VARIANTS
    for scheme in SCHEMES
]

MARKER = "#ff0000"


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def themed(qt_app, monkeypatch):
    """Ставит тему на один тест и возвращает приложение как было.

    Вариант стиля выбирается по sys.platform в момент сборки таблицы стилей.
    """

    def apply(scheme: str, variant: str = sys.platform) -> None:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "platform", variant)
            theme_manager.apply(qt_app, mode=scheme)

    yield apply
    qt_app.setStyleSheet("")
    for name in _THEME_ATTRIBUTES:
        if hasattr(qt_app, name):
            delattr(qt_app, name)


@pytest.fixture()
def app_settings(qt_app, tmp_path):
    """Окружение Менеджера глоссариев, как в test_glossary_conflict_identity."""
    qt_app.event_bus = EventBus()
    settings = SettingsManager(
        event_bus=qt_app.event_bus,
        config_file=str(tmp_path / "settings.json"),
    )
    qt_app.settings_manager = settings
    qt_app.get_settings_manager = lambda: settings
    qt_app.global_version = ""
    yield settings
    settings.flush()


def _wait_until(qt_app, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("не дождались условия")
        qt_app.processEvents()
        time.sleep(0.005)


def _show(qt_app, root) -> None:
    root.resize(1200, 800)
    # Курсор offscreen стоит в (0, 0); строка под ним рисовалась бы наведённой.
    root.move(400, 300)
    root.show()
    qt_app.processEvents()


def _pixel(view, x: int, y: int) -> str:
    image = view.viewport().grab().toImage()
    ratio = image.devicePixelRatio()
    return image.pixelColor(QtCore.QPoint(round(x * ratio), round(y * ratio))).name()


def _cell_background(view, index) -> str:
    """Цвет ячейки у правого края: там нет ни текста, ни скруглённых углов."""
    rect = view.visualRect(index)
    return _pixel(view, rect.right() - 12, rect.center().y())


def _deselect(qt_app, view) -> None:
    view.clearSelection()
    view.setCurrentIndex(QtCore.QModelIndex())
    qt_app.processEvents()


def _text_contrast(background: str) -> float:
    return _contrast_ratio(theme_manager.color("text_primary"), background)


# --- Менеджер глоссариев ---------------------------------------------------


def _show_manager(qt_app, glossary):
    manager = GlossaryManagerPage(mode="child")
    manager.set_glossary(glossary)
    _show(qt_app, manager)
    _wait_until(qt_app, lambda: manager._highlight_timer is None)
    _deselect(qt_app, manager.table)
    return manager


def _conflict_and_plain_rows(manager):
    """Строка с конфликтом и обычная строка одной чётности.

    У таблицы включено чередование строк, и строки разной чётности
    различались бы и без подсветки.
    """
    table = manager.table
    flagged = {
        row: bool(table.item(row, 0).data(manager.ConflictTypeRole))
        for row in range(table.rowCount())
    }
    for conflict_row, is_conflict in flagged.items():
        if not is_conflict:
            continue
        for plain_row, plain_is_conflict in flagged.items():
            if not plain_is_conflict and plain_row % 2 == conflict_row % 2:
                return conflict_row, plain_row
    raise AssertionError(f"нет пары строк одной чётности: {flagged}")


GLOSSARY_WITH_DIRECT_CONFLICT = [
    {"original": "Alpha", "rus": "Альфа", "note": ""},
    {"original": "Alpha", "rus": "Бета", "note": ""},
    {"original": "Gamma", "rus": "Гамма", "note": ""},
]


@pytest.mark.parametrize(("variant", "scheme"), THEMES)
def test_manager_conflict_row_background_differs_from_plain_row(
    qt_app, themed, app_settings, variant, scheme
):
    themed(scheme, variant)
    manager = _show_manager(qt_app, GLOSSARY_WITH_DIRECT_CONFLICT)
    try:
        conflict_row, plain_row = _conflict_and_plain_rows(manager)
        model = manager.table.model()

        conflict = _cell_background(manager.table, model.index(conflict_row, 1))
        plain = _cell_background(manager.table, model.index(plain_row, 1))

        assert conflict != plain
    finally:
        manager.close()


@pytest.mark.parametrize(("variant", "scheme"), THEMES)
def test_manager_conflict_row_keeps_text_readable(
    qt_app, themed, app_settings, variant, scheme
):
    themed(scheme, variant)
    manager = _show_manager(qt_app, GLOSSARY_WITH_DIRECT_CONFLICT)
    try:
        conflict_row, _plain_row = _conflict_and_plain_rows(manager)
        model = manager.table.model()

        background = _cell_background(manager.table, model.index(conflict_row, 1))

        # WCAG AA для обычного текста.
        assert _text_contrast(background) >= 4.5
    finally:
        manager.close()


# --- Форма плашки -----------------------------------------------------------


def _plain_table():
    view = QtWidgets.QTableWidget(3, 2)
    for row in range(3):
        for column in range(2):
            view.setItem(row, column, QtWidgets.QTableWidgetItem(""))
    view.horizontalHeader().setStretchLastSection(True)
    return view


def _plain_list():
    view = QtWidgets.QListWidget()
    for _ in range(3):
        view.addItem("")
    return view


@pytest.mark.parametrize(("variant", "scheme"), THEMES)
@pytest.mark.parametrize("make_view", [_plain_table, _plain_list], ids=["table", "list"])
def test_delegate_fills_the_theme_plate_and_keeps_margins_and_corners(
    qt_app, themed, variant, scheme, make_view
):
    themed(scheme, variant)
    view = make_view()
    view.setItemDelegate(ItemBackgroundDelegate(view))
    model = view.model()
    marked, plain = model.index(0, 0), model.index(2, 0)
    model.setData(marked, QtGui.QBrush(QtGui.QColor(MARKER)), Qt.ItemDataRole.BackgroundRole)
    _show(qt_app, view)
    try:
        _deselect(qt_app, view)
        rect = view.visualRect(marked)
        bare = _cell_background(view, plain)

        assert _cell_background(view, marked) == MARKER
        # Поле слева от плашки и срезанный скруглением угол — фон списка.
        assert _pixel(view, rect.left() + 1, rect.center().y()) == bare
        assert _pixel(view, rect.left() + ITEM_MARGIN_X, rect.top() + ITEM_MARGIN_Y) == bare
    finally:
        view.close()


# --- Редактор главы ---------------------------------------------------------


def _show_editor_with_changed_block(qt_app, tmp_path):
    translated_path = tmp_path / "chapter.html"
    translated_path.write_text("<p>Раз.</p><p>Два.</p><p>Три.</p>", encoding="utf-8")
    dialog = chapter_editor.ChapterEditorDialog(
        str(translated_path),
        original_epub_path=None,
        original_internal_path=None,
        project_manager=None,
    )
    dialog.mode_tabs.setCurrentWidget(dialog.block_table)
    _show(qt_app, dialog)
    dialog.translated_document.setPlainText("<p>Раз, но иначе.</p><p>Два.</p><p>Три.</p>")
    _wait_until(
        qt_app,
        lambda: dialog._analysis_thread is None and not dialog.analysis_timer.isActive(),
    )
    dialog._refresh_block_table()
    _deselect(qt_app, dialog.block_table)
    return dialog


@pytest.mark.parametrize(("variant", "scheme"), THEMES)
def test_editor_changed_block_is_visible_and_readable(
    qt_app, themed, app_settings, tmp_path, variant, scheme
):
    themed(scheme, variant)
    dialog = _show_editor_with_changed_block(qt_app, tmp_path)
    try:
        table = dialog.block_table
        assert table.item(0, 4).text(), "первый блок должен считаться изменённым"
        model = table.model()

        # Строки 0 и 2 одной чётности; перевод — колонка 3.
        changed = _cell_background(table, model.index(0, 3))
        plain = _cell_background(table, model.index(2, 3))

        assert changed != plain
        assert _text_contrast(changed) >= 4.5
    finally:
        # Иначе closeEvent спросит про несохранённые изменения модальным окном.
        dialog.translated_document.setModified(False)
        dialog.close()
        _wait_until(qt_app, lambda: dialog._analysis_thread is None)


# --- Проверка перевода ------------------------------------------------------


def _text_inset(view, index, plate: str) -> int:
    """Расстояние от левого края ячейки до первого пикселя текста на плашке."""
    rect = view.visualRect(index)
    image = view.viewport().grab().toImage()
    ratio = image.devicePixelRatio()
    backgrounds = {plate, _pixel(view, rect.left() + 1, rect.center().y())}
    # Середина строки: без скруглённых углов плашки.
    band = range(rect.center().y() - 4, rect.center().y() + 5)
    for x in range(rect.left(), rect.right()):
        for y in band:
            color = image.pixelColor(QtCore.QPoint(round(x * ratio), round(y * ratio))).name()
            if color not in backgrounds:
                return x - rect.left()
    raise AssertionError("в ячейке нет текста")


@pytest.mark.parametrize(("variant", "scheme"), THEMES)
def test_validator_chapter_column_text_keeps_theme_padding(
    qt_app, themed, app_settings, tmp_path, monkeypatch, variant, scheme
):
    themed(scheme, variant)
    page, table, _cells = _validator_results(tmp_path, monkeypatch)
    try:
        table.item(0, 0).setText("chapter_001.xhtml")
        table.item(0, 3).setText("chapter_001.xhtml")
        _show(qt_app, page)
        for column in (0, 3):
            table.item(0, column).setBackground(QtGui.QColor(MARKER))
        _deselect(qt_app, table)
        model = table.model()

        # Колонку 0 рисует ChapterStatusDelegate, колонку 3 — стиль темы.
        chapter = _text_inset(table, model.index(0, 0), MARKER)
        status = _text_inset(table, model.index(0, 3), MARKER)

        assert abs(chapter - status) <= 1
    finally:
        page.close()
        page.deleteLater()


# --- Остальные окна с подсветкой строк ---------------------------------------
# Каждая фабрика строит окно и отдаёт (окно, вид, ячейки), где фон из модели
# должен быть виден: по одной ячейке на каждый делегат вида.


def _versioning_chapters(tmp_path, monkeypatch):
    widget = ChapterSelectorWidget(epub_path=str(tmp_path / "missing.epub"))
    return widget, widget.list_widget, [(0, 0)]


def _reverse_conflicts(tmp_path, monkeypatch):
    entry = {"original": "小丑", "rus": "[Клоун]", "note": "Путь Шута"}
    page = ReverseConflictResolverPage(
        {"[Клоун]": {"complete": [entry], "orphans": []}},
        [entry],
        morph=False,
    )
    return page, page.translations_list, [(0, 0)]


def _overlap_conflicts(tmp_path, monkeypatch):
    glossary = {
        "赤井明": {"rus": "Восточный Балам", "note": "Локация"},
        "赤井明船坞": {"rus": "Верфь Восточного Балама", "note": "Локация"},
    }
    page = ComplexOverlapResolverPage(
        {"赤井明": ["赤井明船坞"]},
        {"赤井明船坞": ["赤井明"]},
        glossary,
        False,
    )
    return page, page.left_list, [(0, 0)]


def _correction_preview(tmp_path, monkeypatch):
    dialog = CorrectionPreviewDialog(
        original_glossary_list=[{"original": "Wei", "rus": "Vey", "note": "Character"}],
        patch_dict={"Wei": {"rus": "Senior Vey", "note": "Character"}},
        direct_conflicts={},
    )
    return dialog, dialog.table, [(0, 1)]


def _frequency_analysis(tmp_path, monkeypatch):
    # Без EPUB анализ открыл бы модальный выбор файла.
    monkeypatch.setattr(TermFrequencyAnalyzerPage, "_start_analysis_flow", lambda self: None)
    page = TermFrequencyAnalyzerPage([{"original": "Alpha", "rus": "Альфа", "note": ""}])
    page.tabs.setCurrentWidget(page.freq_tab)
    page.freq_table.setRowCount(1)
    page._create_row(page.freq_table, 0, "Alpha", 3, True)
    # Колонки 1–2 — ExpandingTextEditDelegate, остальные — делегат вида.
    return page, page.freq_table, [(0, 1), (0, 3)]


def _ai_repair_review(tmp_path, monkeypatch):
    old_html = "<body>\n<p>Bad.</p>\n</body>\n"
    repaired_html = "<body>\n<p>Good.</p>\n</body>\n"
    segments, changes = build_line_review_segments(old_html, repaired_html)
    page = AIRepairReviewPage([{
        "row": 1,
        "chapter": "chapter.xhtml",
        "original_html": old_html,
        "repaired_html": repaired_html,
        "segments": segments,
        "changes": changes,
        "warning": "",
    }])
    return page, page.table, [(0, 1)]


def _validator_results(tmp_path, monkeypatch):
    monkeypatch.setattr(TranslationValidatorPage, "_perform_initial_cjk_scan", lambda self: None)
    page = TranslationValidatorPage(
        str(tmp_path / "translations"),
        str(tmp_path / "book.epub"),
        project_manager=None,
    )
    page._populate_initial_table_timer.stop()
    table = page.table_results
    table.setRowCount(1)
    for column in range(table.columnCount()):
        table.setItem(0, column, QtWidgets.QTableWidgetItem(""))
    # Колонка 0 — ChapterStatusDelegate, остальные — делегат вида.
    return page, table, [(0, 0), (0, 3)]


def _untranslated_fixer(tmp_path, monkeypatch):
    class _Host(QtWidgets.QWidget):
        settings_manager = object()

    page = UntranslatedFixerPage(
        [{"term": "Level", "context": "<p>Level</p>", "location_info": "ch1"}],
        _Host(),
    )
    # Страница — отдельным окном; хозяин живёт в page._validator_host.
    page.setParent(None)
    # Колонка 2 — ExpandingTextEditDelegate, остальные — делегат вида.
    return page, page.table, [(0, 1), (0, 2)]


def _core_term_members(tmp_path, monkeypatch):
    page = CoreTermAnalyzerPage(
        [{"original": "one term", "rus": "один", "note": ""}],
        None,
        {"one": ["one term"]},
        False,
    )
    # Правую панель обычно строит первый показ, отложенно.
    page._is_loaded = True
    page._async_prepare_data_and_populate()
    table = page.members_table
    table.setRowCount(1)
    table.setItem(0, 0, QtWidgets.QTableWidgetItem(""))
    return page, table, [(0, 0)]


def _consistency_problems(tmp_path, monkeypatch):
    monkeypatch.setattr(ConsistencyValidatorPage, "_check_for_previous_session", lambda self: None)
    page = ConsistencyValidatorPage(
        [{"name": "Chapter 1", "content": "text", "path": "chapter.xhtml"}],
        QtWidgets.QApplication.instance().settings_manager,
    )
    table = page.problems_table
    table.setRowCount(1)
    for column in range(table.columnCount()):
        table.setItem(0, column, QtWidgets.QTableWidgetItem(""))
    # Колонка 0 — CenteredCheckboxDelegate, остальные — делегат вида.
    return page, table, [(0, 0), (0, 2)]


def _epub_chapters(tmp_path, monkeypatch):
    dialog = EpubHtmlSelectorDialog(str(tmp_path / "book.epub"))
    # Сборку интерфейса обычно запускает первый показ вместе с чтением EPUB.
    dialog._is_loaded = True
    dialog._populate_full_ui()
    dialog._ui_is_built = True
    dialog.loading_label.setVisible(False)
    dialog.main_content_widget.setVisible(True)
    dialog.list_widget.addItem("chapter.xhtml")
    return dialog, dialog.list_widget, [(0, 0)]


VIEW_FACTORIES = [
    pytest.param(_versioning_chapters, id="versioning-chapters"),
    pytest.param(_reverse_conflicts, id="reverse-conflicts"),
    pytest.param(_overlap_conflicts, id="overlap-conflicts"),
    pytest.param(_correction_preview, id="ai-correction-preview"),
    pytest.param(_frequency_analysis, id="frequency-analysis"),
    pytest.param(_ai_repair_review, id="ai-repair-review"),
    pytest.param(_validator_results, id="validator-results"),
    pytest.param(_untranslated_fixer, id="untranslated-fixer"),
    pytest.param(_core_term_members, id="core-term-members"),
    pytest.param(_consistency_problems, id="consistency-problems"),
    pytest.param(_epub_chapters, id="epub-chapters"),
]


@pytest.mark.parametrize("factory", VIEW_FACTORIES)
def test_view_shows_item_background_under_theme(
    qt_app, themed, app_settings, tmp_path, monkeypatch, factory
):
    themed("light")
    root, view, cells = factory(tmp_path, monkeypatch)
    try:
        _show(qt_app, root)
        model = view.model()
        # Обработчики itemChanged (например, у выбора глав версий) сами
        # пересчитывают фон по статусу и стёрли бы маркер.
        signals_were_blocked = view.blockSignals(True)
        try:
            for row, column in cells:
                model.setData(
                    model.index(row, column),
                    QtGui.QBrush(QtGui.QColor(MARKER)),
                    Qt.ItemDataRole.BackgroundRole,
                )
        finally:
            view.blockSignals(signals_were_blocked)
        _deselect(qt_app, view)

        painted = {
            (row, column): _cell_background(view, model.index(row, column))
            for row, column in cells
        }

        assert painted == {cell: MARKER for cell in cells}
    finally:
        root.close()
        root.deleteLater()
