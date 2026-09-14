"""«Модель проверки»: the translation's model first, then the other models of its service."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.qa.assembly import QaModelChoices
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui.dialogs.validation_dialogs.quality_settings_view import (
    QualitySettingsView,
)

CHOICES = QaModelChoices(
    provider="gemini",
    translation_model="gemini-3.8-flash",
    models=(
        ("Gemini 3.8 Flash", "gemini-3.8-flash"),
        ("Gemini 3.5 Flash", "gemini-3.5-flash"),
    ),
)
CHOSEN = QaSettings(
    correction_model_mode="custom",
    correction_provider="gemini",
    correction_model="gemini-3.5-flash",
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    import gemini_translator.api.config as api_config

    monkeypatch.setattr(
        api_config,
        "api_providers_view",
        lambda: {"gemini": {"display_name": "Google Gemini Free"}},
    )


def _view(settings: QaSettings | None = None) -> QualitySettingsView:
    return QualitySettingsView(settings or QaSettings(), model_choices=CHOICES)


def _published(view: QualitySettingsView) -> list[QaSettings]:
    published: list[QaSettings] = []
    view.settings_changed.connect(published.append)
    return published


def _items(view: QualitySettingsView) -> list[str]:
    combo = view.check_model_combo
    return [combo.itemText(index) for index in range(combo.count())]


def _choice(settings: QaSettings) -> tuple[str, str, str]:
    return (
        settings.correction_model_mode,
        settings.correction_provider,
        settings.correction_model,
    )


def test_the_translation_model_comes_first_and_then_the_services_models(qt_app):
    view = _view()

    assert _items(view) == [
        "Как у перевода — Gemini 3.8 Flash",
        "Gemini 3.8 Flash",
        "Gemini 3.5 Flash",
    ]
    assert view.check_model_combo.currentIndex() == 0
    assert not view.check_model_row.isHidden()


def test_choosing_a_model_makes_it_the_check_model(qt_app):
    view = _view()
    published = _published(view)

    view.check_model_combo.setCurrentIndex(2)

    assert _choice(published[-1]) == ("custom", "gemini", "gemini-3.5-flash")


def test_going_back_to_the_translation_model_clears_the_choice(qt_app):
    view = _view(CHOSEN)
    published = _published(view)

    view.check_model_combo.setCurrentIndex(0)

    assert _choice(published[-1]) == ("translation_model", "", "")


def test_a_saved_check_model_is_shown_chosen(qt_app):
    assert _view(CHOSEN).check_model_combo.currentText() == "Gemini 3.5 Flash"


def test_a_saved_model_gone_from_the_list_is_still_shown(qt_app):
    """Модели нет в реестре, но проверка идёт именно на ней — так и показываем."""
    view = _view(
        QaSettings(
            correction_model_mode="custom",
            correction_provider="gemini",
            correction_model="gemini-2.0-old",
        )
    )

    assert view.check_model_combo.currentText() == "gemini-2.0-old"


def test_a_model_of_another_service_shows_the_translation_model_and_is_kept(qt_app):
    """Такая модель не применяется, но стирать её без действия пользователя незачем."""
    saved = QaSettings(
        correction_model_mode="custom",
        correction_provider="openai",
        correction_model="gpt-qa",
    )
    view = _view(saved)
    published = _published(view)

    view.final_pass_check.setChecked(False)

    assert view.check_model_combo.currentIndex() == 0
    assert _choice(published[-1]) == ("custom", "openai", "gpt-qa")


def test_loading_a_check_model_publishes_nothing(qt_app):
    view = _view()
    published = _published(view)

    view.apply_settings(CHOSEN)

    assert published == []
    assert view.check_model_combo.currentText() == "Gemini 3.5 Flash"


def test_without_a_service_the_row_is_hidden_and_the_choice_passes_through(qt_app):
    view = QualitySettingsView(CHOSEN)
    published = _published(view)

    view.final_pass_check.setChecked(False)

    assert view.check_model_row.isHidden()
    assert _choice(published[-1]) == ("custom", "gemini", "gemini-3.5-flash")


def test_the_window_hands_the_choices_to_its_settings_tab(qt_app):
    from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_dialog import (
        TranslationQualityDialog,
    )

    dialog = TranslationQualityDialog(settings=QaSettings(), model_choices=CHOICES)

    assert _items(dialog.settings_view) == _items(_view())


def test_the_validation_page_opens_the_window_with_the_services_models():
    import inspect

    from gemini_translator.ui.dialogs import validation

    source = inspect.getsource(
        validation.TranslationValidatorPage.open_translation_quality_dialog
    )

    assert "model_choices=self._quality_model_choices(settings_manager)" in source


def test_unreadable_settings_offer_no_models():
    from gemini_translator.ui.dialogs import validation

    class _Broken:
        def get_last_settings(self):
            raise OSError("settings are locked")

        def load_key_statuses(self):
            raise OSError("settings are locked")

    assert validation.TranslationValidatorPage._quality_model_choices(_Broken()) is None
