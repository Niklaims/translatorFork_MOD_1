"""Glossary conflict pages must fit a Windows work area below 800 px tall."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

# Settle the package's existing glossary circular import the same way the app
# and the nested-page tests do before importing the concrete resolver pages.
from gemini_translator.ui.widgets.glossary_widget import GlossaryWidget  # noqa: F401
from gemini_translator.ui.dialogs.glossary_dialogs.conflict_resolvers import (
    ComplexOverlapResolverPage,
    ReverseConflictResolverPage,
)


def _complex_page():
    glossary = {
        "赤井明": {"rus": "Восточный Балам", "note": "Локация"},
        "赤井明船坞": {"rus": "Верфь Восточного Балама", "note": "Локация"},
    }
    return ComplexOverlapResolverPage(
        {"赤井明": ["赤井明船坞"]},
        {"赤井明船坞": ["赤井明"]},
        glossary,
        False,
    )


def _reverse_page():
    entry = {"original": "小丑", "rus": "[Клоун]", "note": "Путь Шута"}
    return ReverseConflictResolverPage(
        {"[Клоун]": {"complete": [entry], "orphans": []}},
        [entry],
        morph=False,
    )


@pytest.mark.parametrize("page_factory", [_complex_page, _reverse_page])
def test_conflict_page_can_shrink_to_a_640px_windows_work_area(qtbot, page_factory):
    page = page_factory()
    qtbot.addWidget(page)
    page.show()
    page.resize(1200, 640)
    QtWidgets.QApplication.processEvents()

    assert page.height() <= 640
    buttons = page.findChildren(QtWidgets.QDialogButtonBox)
    assert len(buttons) == 1
    assert page.rect().contains(buttons[0].geometry().bottomRight())
