"""The validation page opens the window with a key counter and the book's name."""

from __future__ import annotations

import inspect
from types import SimpleNamespace


class _Manager:
    def load_key_statuses(self):
        return [
            {"provider": "gemini", "key": "g-1"},
            {"provider": "gemini", "key": "g-2"},
        ]

    def is_key_limit_active(self, key_info, model_id):
        return key_info.get("key") == "g-2"


def test_the_key_counter_counts_through_the_settings_manager():
    from gemini_translator.ui.dialogs import validation

    counter = validation.TranslationValidatorPage._quality_key_counter(_Manager())

    assert counter("gemini", "gemini-embedding-001") == (1, 2)


def test_the_book_title_is_the_project_folder_name():
    from gemini_translator.ui.dialogs import validation

    page = SimpleNamespace(project_manager=SimpleNamespace(project_folder="/books/Star Rail/"))

    assert validation.TranslationValidatorPage._quality_book_title(page) == "Star Rail"
    assert validation.TranslationValidatorPage._quality_book_title(SimpleNamespace()) == ""


def test_the_window_is_opened_without_a_list_of_keys():
    from gemini_translator.ui.dialogs import validation

    source = inspect.getsource(
        validation.TranslationValidatorPage.open_translation_quality_dialog
    )

    assert "api_keys" not in source
    assert "key_counter=self._quality_key_counter(settings_manager)" in source
    assert "book_title=self._quality_book_title()" in source
