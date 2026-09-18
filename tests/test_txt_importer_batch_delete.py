"""
Пакетное удаление глав в мастере импорта TXT.

Таблица оглавления разрешала выделить только одну строку, и «Удалить главу»
снимало одну метку: лишние главы приходилось удалять по одной или вычищать
в текстовом редакторе. Тесты выделяют строки так же, как пользователь, —
щелчками с Shift и Ctrl — и проверяют, что удаляются ровно выделенные главы,
в том числе когда таблица отсортирована по размеру и номера строк не
совпадают с порядком глав в книге.
"""

from PyQt6.QtCore import Qt

from gemini_translator.utils.txt_importer import TxtImportWizardDialog


def _open_toc(tmp_path, qtbot, bodies):
    lines = []
    for number, body in enumerate(bodies, 1):
        lines += [f"Глава {number}", body]
    txt_path = tmp_path / "novel.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    dialog = TxtImportWizardDialog(str(txt_path), str(out_dir))
    qtbot.addWidget(dialog)
    dialog.regex_input.setText(r"^Глава\s*\d+")
    dialog.go_to_toc_editor()
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def _click_title(qtbot, table, title, modifier=Qt.KeyboardModifier.NoModifier):
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == title)
    center = table.visualItemRect(table.item(row, 0)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifier, center)


def _titles(dialog):
    return [chapter["title"] for chapter in dialog.structure_data]


def test_shift_click_range_is_deleted_in_one_go(tmp_path, qtbot):
    dialog = _open_toc(tmp_path, qtbot, ["один", "два", "три", "четыре", "пять"])
    table = dialog.toc_table

    _click_title(qtbot, table, "Глава 2")
    _click_title(qtbot, table, "Глава 4", Qt.KeyboardModifier.ShiftModifier)
    dialog.delete_selected_chapter()

    assert _titles(dialog) == ["Глава 1", "Глава 5"]
    assert table.rowCount() == 2


def test_ctrl_click_in_size_sorted_table_deletes_exactly_clicked_chapters(tmp_path, qtbot):
    # По возрастанию размера строки идут как Глава 2, 4, 3, 1 —
    # номер строки таблицы не равен индексу главы в structure_data.
    dialog = _open_toc(tmp_path, qtbot, ["x" * 40, "x" * 10, "x" * 30, "x" * 20])
    table = dialog.toc_table
    table.sortItems(1, Qt.SortOrder.AscendingOrder)

    _click_title(qtbot, table, "Глава 1")
    _click_title(qtbot, table, "Глава 3", Qt.KeyboardModifier.ControlModifier)
    dialog.delete_selected_chapter()

    assert _titles(dialog) == ["Глава 2", "Глава 4"]
