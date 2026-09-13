# -*- coding: utf-8 -*-
"""The «Предложения» tab: language fixes the check proposed but did not apply."""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .quality_widgets import EmptyState


SUGGESTIONS_EMPTY_TITLE = "Непринятых правок нет"
SUGGESTIONS_EMPTY_TEXT = (
    "Правки, которые проверка не приняла, появятся здесь после следующего прохода. "
    "Прошлые проходы их не сохраняли."
)


class QualitySuggestionsView(QWidget):
    """Until suggestions are recorded, the tab says why it is empty."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        self.empty_state = EmptyState(SUGGESTIONS_EMPTY_TITLE, SUGGESTIONS_EMPTY_TEXT, self)
        layout.addWidget(self.empty_state)
