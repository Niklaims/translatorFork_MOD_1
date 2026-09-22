# -*- coding: utf-8 -*-
"""Общие мелкие хелперы для работы с Qt/PyQt6.

Канонический дом для проверок вида «жив ли ещё C++-объект Qt» — раньше
эта проверка была продублирована дословно в нескольких модулях
(``gemini_translator/ui/pages/qidian_creator_page.py`` и
``ranobelib/main_window.py``).
"""

from __future__ import annotations

from contextlib import contextmanager

from PyQt6 import sip
from PyQt6.QtWidgets import QHeaderView


def qt_object_is_alive(obj) -> bool:
    """Вернуть True, если ``obj`` не None и его C++-объект Qt ещё не удалён.

    ``sip.isdeleted`` бросает TypeError для объектов, которые вообще не
    являются обёрнутыми sip-объектами (например, обычный Python-объект) —
    в этом случае считаем объект «живым», как и обе исходные копии.
    """
    if obj is None:
        return False
    try:
        return not sip.isdeleted(obj)
    except TypeError:
        return True


@contextmanager
def deferred_column_autosize(table):
    """На время блока выключает ResizeToContents у столбцов ``table``.

    В этом режиме QHeaderView после каждой изменённой ячейки заново меряет
    столбец — до resizeContentsPrecision строк (по умолчанию 1000). Заполнить
    таблицу построчно так стоит O(N²): окно проверки на 514 главах тратило на
    это 4,7 с. После блока режим возвращается, и столбцы меряются один раз.
    Вложенный блок ничего не трогает: столбцы уже переключил внешний.
    """
    header = table.horizontalHeader()
    automatic = [
        section for section in range(header.count())
        if header.sectionResizeMode(section) == QHeaderView.ResizeMode.ResizeToContents
    ]
    for section in automatic:
        header.setSectionResizeMode(section, QHeaderView.ResizeMode.Interactive)
    try:
        yield
    finally:
        if qt_object_is_alive(header):
            for section in automatic:
                header.setSectionResizeMode(section, QHeaderView.ResizeMode.ResizeToContents)
