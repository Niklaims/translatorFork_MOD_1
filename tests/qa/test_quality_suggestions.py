"""A refused fix is shown with its reason and both texts, and decided in one click."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.qa.language_validation import LANGUAGE_ISSUE_CATEGORIES
from gemini_translator.qa.models import QaSuggestion
from gemini_translator.qa.text_diff import REMOVED_STYLE
from gemini_translator.ui.dialogs.validation_dialogs.quality_suggestions_view import (
    QualitySuggestionsView,
)
from gemini_translator.ui.dialogs.validation_dialogs.quality_widgets import (
    SuggestionCard,
    category_label,
    pending_caption,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _suggestion(
    chapter_id="chapter-12",
    original="— Спросил он.",
    replacement="— спросил он.",
    category="punctuation",
    status="pending",
    reason="validation_declined",
    note="",
) -> QaSuggestion:
    return QaSuggestion(
        suggestion_id=QaSuggestion.identity(chapter_id, "n.1", original, replacement),
        chapter_id=chapter_id,
        block_id="n.1",
        category=category,
        original_text=original,
        replacement_text=replacement,
        reason=reason,
        status=status,
        status_note=note,
    )


def test_every_known_category_reads_in_russian_and_an_unknown_one_stays_as_is():
    for code in LANGUAGE_ISSUE_CATEGORIES:
        assert category_label(code) != code
    assert category_label("new_code") == "new_code"


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "1 правка ждёт решения"),
        (3, "3 правки ждут решения"),
        (5, "5 правок ждут решения"),
        (11, "11 правок ждут решения"),
        (21, "21 правка ждёт решения"),
        (37, "37 правок ждут решения"),
    ],
)
def test_the_counter_agrees_with_its_number(count, text):
    assert pending_caption(count) == text


def test_a_card_shows_where_what_why_and_both_texts(qt_app):
    card = SuggestionCard(_suggestion())

    texts = [label.text() for label in card.findChildren(QtWidgets.QLabel)]

    assert "chapter-12" in texts
    assert card.category_chip.text() == "пунктуация"
    assert card.reason_label.text() == "не принято: модель-проверщик не подтвердила правку"
    assert "Спросил" in card.before_label.text()
    assert "спросил" in card.after_label.text()
    assert card.dismiss_button.text() == "Отклонить"
    assert card.apply_button.text() == "Применить"


def test_a_card_names_a_chapter_by_its_file(qt_app):
    card = SuggestionCard(_suggestion(chapter_id="OEBPS/chapter12.xhtml"))

    texts = [label.text() for label in card.findChildren(QtWidgets.QLabel)]

    assert "chapter12" in texts


def test_card_buttons_ask_by_the_suggestions_id(qt_app):
    suggestion = _suggestion()
    card = SuggestionCard(suggestion)
    applied: list[str] = []
    dismissed: list[str] = []
    card.apply_requested.connect(applied.append)
    card.dismiss_requested.connect(dismissed.append)

    card.apply_button.click()
    card.dismiss_button.click()

    assert applied == [suggestion.suggestion_id]
    assert dismissed == [suggestion.suggestion_id]


def test_a_stale_card_only_offers_to_take_it_off_the_list(qt_app):
    card = SuggestionCard(
        _suggestion(status="stale", note="глава изменилась после проверки")
    )

    assert card.apply_button is None
    assert card.dismiss_button.text() == "Убрать из списка"
    assert card.note_label.text() == "Применить нельзя: глава изменилась после проверки."


def test_a_card_without_a_replacement_cannot_be_applied(qt_app):
    """Пустая замена у повтора значит «модель не предложила текст», а не «удалить»."""
    card = SuggestionCard(
        _suggestion(
            original="очень-очень", replacement="", category="repetition", reason="no_replacement"
        )
    )

    assert not card.apply_button.isEnabled()
    assert card.note_label.text() == "Такую правку вносят вручную."
    assert "замена не предложена" in card.after_label.text()
    assert "удалить" not in card.after_label.text()


def test_a_meta_comment_without_a_replacement_reads_as_a_deletion(qt_app):
    """Служебный комментарий исправляют удалением: заменять его нечем."""
    card = SuggestionCard(
        _suggestion(
            original="(прим. пер.: игра слов)",
            replacement="",
            category="meta_comment",
            reason="no_replacement",
        )
    )

    assert "удалить фрагмент" in card.after_label.text()
    assert REMOVED_STYLE in card.before_label.text()
    assert not card.apply_button.isEnabled()


@pytest.mark.parametrize("reason", ["ambiguous_span", "paragraph_break"])
def test_a_fix_the_text_cannot_take_offers_no_apply(qt_app, reason):
    card = SuggestionCard(_suggestion(reason=reason))

    assert not card.apply_button.isEnabled()
    assert card.note_label.text() == "Такую правку вносят вручную."


def test_model_text_is_never_rendered_as_markup(qt_app):
    """Текст модели попадает в подпись с разметкой подсветки, но сам разметкой не становится."""
    card = SuggestionCard(_suggestion(original="<b>x</b> и", replacement="<b>x</b> а"))

    assert "&lt;b&gt;x&lt;/b&gt;" in card.before_label.text()
    assert "<b>" not in card.before_label.text()
    assert "<b>" not in card.after_label.text()


def test_a_busy_window_locks_a_card(qt_app):
    card = SuggestionCard(_suggestion())

    card.set_busy(True)
    assert not card.apply_button.isEnabled()
    assert not card.dismiss_button.isEnabled()

    card.set_busy(False)
    assert card.apply_button.isEnabled()
    assert card.dismiss_button.isEnabled()


def test_a_card_of_a_chapter_being_checked_can_only_be_dismissed(qt_app):
    """Проверяемую главу нельзя править, но отклонить правку можно: файл не трогается."""
    card = SuggestionCard(_suggestion())

    card.set_locks(checking=True)

    assert not card.apply_button.isEnabled()
    assert card.dismiss_button.isEnabled()
    assert card.note_label.text() == "Глава сейчас проверяется."

    card.set_locks()

    assert card.apply_button.isEnabled()
    assert card.note_label.text() == ""


def _view(*suggestions) -> QualitySuggestionsView:
    view = QualitySuggestionsView()
    view.set_suggestions(suggestions)
    return view


def test_filters_narrow_the_cards_and_the_counter_counts_them_all(qt_app):
    view = _view(
        _suggestion("chapter-2", "a а", "b б", "punctuation"),
        _suggestion("chapter-2", "c в", "d г", "calque"),
        _suggestion("chapter-10", "e д", "f е", "punctuation"),
    )

    assert view.counter_label.text() == "3 правки ждут решения"
    assert [view.chapter_filter.itemText(i) for i in range(view.chapter_filter.count())] == [
        "Все главы",
        "chapter-2",
        "chapter-10",
    ]
    assert len(view.cards) == 3

    view.chapter_filter.setCurrentIndex(view.chapter_filter.findData("chapter-2"))
    assert [card.suggestion.chapter_id for card in view.cards] == ["chapter-2", "chapter-2"]

    view.category_filter.setCurrentIndex(view.category_filter.findData("calque"))
    assert [card.suggestion.category for card in view.cards] == ["calque"]
    assert view.counter_label.text() == "3 правки ждут решения"


def test_a_filter_survives_a_refresh_while_its_chapter_still_waits(qt_app):
    first = _suggestion("chapter-2", "a а", "b б")
    view = _view(first, _suggestion("chapter-10", "e д", "f е"))
    view.chapter_filter.setCurrentIndex(view.chapter_filter.findData("chapter-2"))

    view.set_suggestions(
        (first, _suggestion("chapter-2", "c в", "d г"), _suggestion("chapter-10", "e д", "f е"))
    )

    assert view.chapter_filter.currentData() == "chapter-2"
    assert len(view.cards) == 2


def test_no_suggestions_shows_the_empty_state(qt_app):
    view = _view()

    assert view.stack.currentWidget() is view.empty_state
    assert view.empty_state.title_label.text() == "Непринятых правок нет"


def test_a_long_list_is_shown_fifty_cards_at_a_time(qt_app):
    view = _view(*[_suggestion(f"chapter-{i}", f"a{i} а", f"b{i} б") for i in range(120)])

    assert len(view.cards) == 50
    assert view.more_button.text() == "Показать ещё 50 из 70"

    view.more_button.click()
    assert len(view.cards) == 100

    view.more_button.click()
    assert len(view.cards) == 120
    assert view.more_button.isHidden()


def test_the_tab_asks_for_decisions_by_id_and_locks_only_what_is_in_use(qt_app):
    first = _suggestion("chapter-1", "a а", "b б")
    second = _suggestion("chapter-2", "c в", "d г")
    view = _view(first, second)
    applied: list[str] = []
    view.apply_requested.connect(applied.append)

    view.cards[0].apply_button.click()

    assert applied == [first.suggestion_id]

    view.set_checking_chapters(frozenset({"chapter-2"}))
    view.set_deciding_suggestions(frozenset({first.suggestion_id}))

    assert not view.cards[0].dismiss_button.isEnabled()
    assert not view.cards[1].apply_button.isEnabled()
    assert view.cards[1].dismiss_button.isEnabled()

    view.set_suggestions((first, second, _suggestion("chapter-2", "e д", "f е")))

    assert not view.cards[2].apply_button.isEnabled()
