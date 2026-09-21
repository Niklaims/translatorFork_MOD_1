"""Фильтр колеса над вкладками ставится, только если стиль листает вкладки.

Фильтр висит на всём приложении: Qt зовёт Python на каждое событие, и пока
другой поток держит GIL, каждый вызов ждёт интерпретатор. Родной стиль macOS
колесом вкладки не листает, там фильтр — чистая потеря.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

import main as app_main


class _Style:
    def __init__(self, hint_value):
        self.hint_value = hint_value
        self.asked = []

    def styleHint(self, hint, *args):  # noqa: N802 - Qt API name
        self.asked.append(hint)
        return self.hint_value


def test_guard_is_needed_where_the_style_scrolls_tabs_with_the_wheel():
    style = _Style(1)

    assert app_main.tab_wheel_guard_needed(style) is True
    assert style.asked == [QtWidgets.QStyle.StyleHint.SH_TabBar_AllowWheelScrolling]


def test_guard_is_skipped_where_the_style_already_ignores_the_wheel():
    assert app_main.tab_wheel_guard_needed(_Style(0)) is False
