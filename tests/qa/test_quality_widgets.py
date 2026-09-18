"""The window's building blocks carry meaning in words and are styled by name only."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from gemini_translator.ui.dialogs.validation_dialogs.quality_widgets import (
    EmptyState,
    MetricCard,
    StatusChip,
    chapters_caption,
    format_checked_at,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_a_status_chip_keeps_only_known_tones(qt_app):
    chip = StatusChip("Готово к проверке", "success")

    assert chip.objectName() == "statusChip"
    assert chip.property("tone") == "success"

    chip.set_state("Идёт проверка", "warning")
    assert (chip.text(), chip.property("tone")) == ("Идёт проверка", "warning")

    chip.set_tone("purple")
    assert chip.property("tone") == "neutral"


def test_a_status_chip_never_renders_markup(qt_app):
    assert StatusChip("<b>x</b>").textFormat() == Qt.TextFormat.PlainText


def test_a_metric_card_shows_its_values_and_reports_its_action(qt_app):
    card = MetricCard("Ждут решения", "Открыть предложения")
    clicks: list[int] = []
    card.action_clicked.connect(lambda: clicks.append(1))

    card.set_values("37", "В главах: 19.")
    card.action_button.click()

    assert card.objectName() == "projectStatsCard"
    assert (card.value_label.text(), card.detail_label.text()) == ("37", "В главах: 19.")
    assert clicks == [1]


def test_a_metric_card_without_an_action_has_no_button(qt_app):
    assert MetricCard("Проверено").action_button is None


def test_the_empty_state_text_is_not_cut_to_one_line(qt_app):
    """Подпись с переносом, поставленная с флагом выравнивания, обрезалась до строки."""
    state = EmptyState(
        "Отчёт пока пуст",
        "Проверенные главы появятся здесь после первого прохода. Проверка идёт "
        "после каждой переведённой главы или по кнопке «Проверить все главы».",
    )
    state.resize(900, 500)
    state.show()
    qt_app.processEvents()
    try:
        label = state.text_label
        assert label.heightForWidth(label.width()) > label.fontMetrics().height()
        assert label.height() >= label.heightForWidth(label.width())
    finally:
        state.close()
        state.deleteLater()


@pytest.mark.parametrize("value", ["", "not a date"])
def test_an_unreadable_date_is_left_out(value):
    assert format_checked_at(value) == ""


def test_a_date_reads_the_way_it_does_in_a_russian_sentence():
    assert format_checked_at("2026-09-09T10:05:00") == "9 сентября 2026, 10:05"


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "1 глава"),
        (2, "2 главы"),
        (5, "5 глав"),
        (11, "11 глав"),
        (21, "21 глава"),
        (484, "484 главы"),
    ],
)
def test_chapters_are_counted_the_russian_way(count, text):
    """«484 глав(ы)» в журнале прохода."""
    assert chapters_caption(count) == text

