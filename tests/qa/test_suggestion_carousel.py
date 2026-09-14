"""Waiting fixes in the chapter card: one at a time, with arrows and a two-finger swipe."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication

from gemini_translator.qa.models import QaSuggestion
from gemini_translator.ui.dialogs.validation_dialogs.quality_widgets import (
    SuggestionCarousel,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _suggestion(index: int, *, explanation: str = "") -> QaSuggestion:
    original = f"фраза {index} было"
    replacement = f"фраза {index} стало"
    return QaSuggestion(
        suggestion_id=QaSuggestion.identity("chapter-1", "n.1", original, replacement),
        chapter_id="chapter-1",
        block_id="n.1",
        category="calque",
        original_text=original,
        replacement_text=replacement,
        reason="validation_declined",
        explanation=explanation,
    )


def _carousel(*suggestions: QaSuggestion) -> SuggestionCarousel:
    carousel = SuggestionCarousel()
    carousel.set_suggestions(suggestions)
    return carousel


def _wheel(
    carousel: SuggestionCarousel,
    *,
    x: int = 0,
    y: int = 0,
    phase: Qt.ScrollPhase = Qt.ScrollPhase.NoScrollPhase,
    trackpad: bool = False,
) -> bool:
    """Send one wheel event the way the platform does; say whether it was taken."""
    delta = QPoint(x, y)
    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        delta if trackpad else QPoint(0, 0),
        delta,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        phase,
        False,
    )
    QApplication.sendEvent(carousel, event)
    return event.isAccepted()


def _press(carousel: SuggestionCarousel, key: Qt.Key) -> None:
    QApplication.sendEvent(
        carousel, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    )


def test_one_fix_is_shown_at_a_time_with_a_count(qt_app):
    carousel = _carousel(_suggestion(1), _suggestion(2), _suggestion(3))

    assert carousel.current_card() is carousel.cards[0]
    assert [card.isHidden() for card in carousel.cards] == [False, True, True]
    assert carousel.counter_label.text() == "1 из 3"
    assert not carousel.previous_button.isEnabled()
    assert carousel.next_button.isEnabled()


def test_the_arrows_turn_the_cards_and_stop_at_the_ends(qt_app):
    carousel = _carousel(_suggestion(1), _suggestion(2), _suggestion(3))

    carousel.next_button.click()
    carousel.next_button.click()

    assert carousel.counter_label.text() == "3 из 3"
    assert not carousel.next_button.isEnabled()

    carousel.previous_button.click()

    assert carousel.current_card() is carousel.cards[1]
    assert carousel.previous_button.isEnabled()


def test_a_two_finger_swipe_turns_one_card_per_gesture(qt_app):
    """Трекпад шлёт десятки событий за жест, а перелистнуться карточка должна один раз."""
    carousel = _carousel(_suggestion(1), _suggestion(2), _suggestion(3))

    _wheel(carousel, phase=Qt.ScrollPhase.ScrollBegin, trackpad=True)
    _wheel(carousel, x=-30, phase=Qt.ScrollPhase.ScrollUpdate, trackpad=True)
    _wheel(carousel, x=-45, phase=Qt.ScrollPhase.ScrollUpdate, trackpad=True)
    _wheel(carousel, x=-90, phase=Qt.ScrollPhase.ScrollUpdate, trackpad=True)
    _wheel(carousel, phase=Qt.ScrollPhase.ScrollEnd, trackpad=True)
    _wheel(carousel, x=-60, phase=Qt.ScrollPhase.ScrollMomentum, trackpad=True)

    assert carousel.counter_label.text() == "2 из 3"

    _wheel(carousel, phase=Qt.ScrollPhase.ScrollBegin, trackpad=True)
    _wheel(carousel, x=80, phase=Qt.ScrollPhase.ScrollUpdate, trackpad=True)

    assert carousel.counter_label.text() == "1 из 3"


def test_a_horizontal_wheel_notch_turns_a_card(qt_app):
    carousel = _carousel(_suggestion(1), _suggestion(2))

    _wheel(carousel, x=-120)

    assert carousel.counter_label.text() == "2 из 2"


def test_a_vertical_scroll_is_left_to_the_page(qt_app):
    carousel = _carousel(_suggestion(1), _suggestion(2))

    taken = _wheel(carousel, y=-120)

    assert not taken
    assert carousel.counter_label.text() == "1 из 2"


def test_the_arrow_keys_turn_the_cards(qt_app):
    carousel = _carousel(_suggestion(1), _suggestion(2))

    _press(carousel, Qt.Key.Key_Right)
    assert carousel.counter_label.text() == "2 из 2"

    _press(carousel, Qt.Key.Key_Left)
    assert carousel.counter_label.text() == "1 из 2"


def test_a_single_fix_needs_no_arrows_or_count(qt_app):
    carousel = _carousel(_suggestion(1))

    assert carousel.previous_button.isHidden()
    assert carousel.next_button.isHidden()
    assert carousel.counter_label.isHidden()


def test_a_refresh_keeps_the_fix_that_was_shown(qt_app):
    first, second, third = _suggestion(1), _suggestion(2), _suggestion(3)
    carousel = _carousel(first, second, third)
    carousel.next_button.click()

    carousel.set_suggestions((first, second, third, _suggestion(4)))

    assert carousel.current_suggestion_id() == second.suggestion_id
    assert carousel.counter_label.text() == "2 из 4"

    carousel.set_suggestions((first, third))

    assert carousel.current_suggestion_id() == third.suggestion_id
    assert carousel.counter_label.text() == "2 из 2"


def test_the_shown_card_asks_for_decisions_by_id(qt_app):
    first, second = _suggestion(1), _suggestion(2)
    carousel = _carousel(first, second)
    applied: list[str] = []
    dismissed: list[str] = []
    carousel.apply_requested.connect(applied.append)
    carousel.dismiss_requested.connect(dismissed.append)

    carousel.next_button.click()
    carousel.current_card().apply_button.click()
    carousel.current_card().dismiss_button.click()

    assert applied == [second.suggestion_id]
    assert dismissed == [second.suggestion_id]


def test_the_carousel_is_as_tall_as_the_card_it_shows(qt_app):
    """Высота бралась по самой длинной правке, и под короткой оставалась пустота."""
    carousel = _carousel(
        _suggestion(1), _suggestion(2, explanation="Очень длинное объяснение правки. " * 30)
    )
    carousel.resize(520, 600)
    carousel.show()
    qt_app.processEvents()
    short = carousel.cards_box.sizeHint().height()

    carousel.next_button.click()
    qt_app.processEvents()
    tall = carousel.cards_box.sizeHint().height()
    carousel.close()

    assert short < tall


def test_the_carousel_locks_only_what_is_in_use(qt_app):
    first, second = _suggestion(1), _suggestion(2)
    carousel = _carousel(first, second)

    carousel.set_checking_chapters(frozenset({"chapter-1"}))

    assert not any(card.apply_button.isEnabled() for card in carousel.cards)
    assert all(card.dismiss_button.isEnabled() for card in carousel.cards)

    carousel.set_checking_chapters(frozenset())
    carousel.set_deciding_suggestions(frozenset({second.suggestion_id}))
    carousel.set_suggestions((first, second, _suggestion(3)))

    assert carousel.cards[0].apply_button.isEnabled()
    assert not carousel.cards[1].dismiss_button.isEnabled()
    assert carousel.cards[2].dismiss_button.isEnabled()
