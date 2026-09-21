"""Массовое заполнение таблицы не должно мерить столбцы после каждой ячейки.

В режиме ResizeToContents QHeaderView заново меряет столбец после каждой
изменённой ячейки — до resizeContentsPrecision строк, по умолчанию 1000.
Заполнение N строк стоит O(N²): окно проверки на 514 главах тратило на это
4,7 с. deferred_column_autosize выключает режим на время блока и меряет
столбцы один раз в конце.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.utils.qt_utils import deferred_column_autosize

Mode = QtWidgets.QHeaderView.ResizeMode


_APP = None


def _app():
    # Ссылку держим: иначе только что созданное приложение тут же удалится,
    # и первый же виджет оборвёт процесс.
    global _APP
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _APP


def _table():
    table = QtWidgets.QTableWidget(0, 3)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, Mode.Stretch)
    header.setSectionResizeMode(1, Mode.ResizeToContents)
    header.setSectionResizeMode(2, Mode.ResizeToContents)
    table.resize(600, 300)
    table.show()
    # Пока цикл событий не показал таблицу, заголовок столбцы не меряет.
    _app().processEvents()
    return table


def _fill(table, rows):
    for row in range(rows):
        table.insertRow(row)
        for column in range(3):
            table.setItem(row, column, QtWidgets.QTableWidgetItem(f"cell {row}-{column}" + "x" * (row % 7)))


def test_resize_to_contents_is_restored_and_applied_once_at_the_end():
    _app()
    table = _table()
    header = table.horizontalHeader()

    with deferred_column_autosize(table):
        assert header.sectionResizeMode(1) == Mode.Interactive
        _fill(table, 40)
        table.setItem(3, 2, QtWidgets.QTableWidgetItem("a much longer cell than every other one"))

    assert header.sectionResizeMode(0) == Mode.Stretch
    assert header.sectionResizeMode(1) == Mode.ResizeToContents
    assert header.sectionResizeMode(2) == Mode.ResizeToContents
    assert header.sectionSize(2) >= table.sizeHintForColumn(2)
    table.close()


def test_nested_blocks_leave_the_outer_block_in_charge():
    _app()
    table = _table()
    header = table.horizontalHeader()

    with deferred_column_autosize(table):
        with deferred_column_autosize(table):
            _fill(table, 5)
        assert header.sectionResizeMode(1) == Mode.Interactive

    assert header.sectionResizeMode(1) == Mode.ResizeToContents
    table.close()
