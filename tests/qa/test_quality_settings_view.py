"""The settings tab: four cards, provider-level keys, and every value round-trips."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QLineEdit

from gemini_translator.qa.capabilities import QaCapabilityKey, QaCapabilitySettings
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui.dialogs.validation_dialogs.quality_settings_view import (
    QualitySettingsView,
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
        lambda: {
            "gemini": {"display_name": "Google Gemini Free"},
            "openrouter": {"display_name": "OpenRouter"},
        },
    )


def _select(view: QualitySettingsView, provider: str) -> None:
    view.embedding_provider_combo.setCurrentIndex(
        view.embedding_provider_combo.findData(provider)
    )


def _published(view: QualitySettingsView) -> list[QaSettings]:
    published: list[QaSettings] = []
    view.settings_changed.connect(published.append)
    return published


def test_the_four_cards_come_in_order(qt_app):
    view = QualitySettingsView(QaSettings())

    titles = [
        label.text()
        for label in view.findChildren(QtWidgets.QLabel)
        if label.objectName() == "projectCardTitle"
    ]

    assert titles == [
        "После каждой главы",
        "Смысловое сравнение",
        "Оценка на ПК (CometKiwi)",
        "Дополнительные анализаторы",
    ]


def test_stage_switches_round_trip(qt_app):
    view = QualitySettingsView(
        QaSettings(
            check_completeness_after_chapter=False,
            auto_repair_confirmed_omissions=False,
            capabilities=QaCapabilitySettings(slovnet_enabled=True),
        )
    )

    assert view.completeness_check.isChecked() is False
    assert view.repair_omissions_check.isChecked() is False
    settings = view.qa_settings()
    assert settings.check_completeness_after_chapter is False
    assert settings.capabilities.slovnet_enabled is True
    assert settings.capabilities.razdel_enabled is True


def test_an_edit_is_published(qt_app):
    view = QualitySettingsView(QaSettings())
    published = _published(view)

    view.language_check.setChecked(False)

    assert published and published[-1].check_language_after_chapter is False


def test_loading_settings_publishes_nothing(qt_app):
    view = QualitySettingsView(QaSettings())
    published = _published(view)

    view.apply_settings(
        QaSettings(
            embedding_provider="openai_compatible",
            embedding_api_key="sk-1",
            embedding_base_url="https://example.test/v1",
        )
    )

    assert published == []
    assert view.embedding_key_edit.text() == "sk-1"


def test_the_gemini_key_chip_shows_what_the_counter_reports(qt_app):
    calls: list[tuple[str, str]] = []

    def counter(provider_id, model_id):
        calls.append((provider_id, model_id))
        return (5, 7)

    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini"),
        key_counter=counter,
    )

    assert view.embedding_keys_chip.text() == "5 из 7 работают"
    assert view.embedding_keys_chip.property("tone") == "success"
    assert not view.embedding_keys_chip.isHidden()
    assert view.embedding_keys_label.text() == "все рабочие ключи Gemini"
    assert calls[-1] == ("gemini", "gemini-embedding-001")


def test_no_working_gemini_key_turns_the_chip_red(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini"),
        key_counter=lambda provider_id, model_id: (0, 3),
    )

    assert view.embedding_keys_chip.text() == "0 из 3 работают"
    assert view.embedding_keys_chip.property("tone") == "danger"


def test_choosing_gemini_writes_the_provider_not_a_key(qt_app):
    view = QualitySettingsView(QaSettings(), key_counter=lambda provider_id, model_id: (1, 1))

    _select(view, "gemini")
    settings = view.qa_settings()

    assert (
        settings.embedding_provider,
        settings.embedding_key_provider,
        settings.embedding_api_key,
    ) == ("gemini", "gemini", "")
    assert settings.embedding_setup_problem() == ""


def test_openai_compatible_writes_its_own_key_and_address(qt_app):
    view = QualitySettingsView(QaSettings())

    _select(view, "openai_compatible")
    models = [
        view.embedding_model_combo.itemText(index)
        for index in range(view.embedding_model_combo.count())
    ]
    view.embedding_key_edit.setText("sk-own-key")
    view.embedding_base_url_edit.setText("https://api.openai.com/v1")
    view.embedding_model_combo.setEditText("text-embedding-3-large")
    settings = view.qa_settings()

    assert "text-embedding-3-small" in models
    assert not view.embedding_key_edit.isHidden()
    assert not view.embedding_base_url_edit.isHidden()
    assert settings.embedding_provider == "openai_compatible"
    assert settings.embedding_api_key == "sk-own-key"
    assert settings.embedding_key_provider == ""
    assert settings.embedding_base_url == "https://api.openai.com/v1"
    assert settings.embedding_model == "text-embedding-3-large"
    assert settings.embedding_setup_problem() == ""


def test_the_address_and_own_key_hide_for_other_providers(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini")
    )

    assert view.embedding_key_edit.isHidden()
    assert view.embedding_base_url_edit.isHidden()


def test_the_own_key_is_typed_hidden(qt_app):
    view = QualitySettingsView(QaSettings())

    assert view.embedding_key_edit.echoMode() == QLineEdit.EchoMode.Password


def test_a_legacy_key_provider_is_kept_until_the_user_chooses(qt_app):
    """Ранее выбранные ключи другого провайдера не пропадают молча."""
    view = QualitySettingsView(
        QaSettings(embedding_provider="auto", embedding_key_provider="openrouter")
    )

    assert view.embedding_keys_label.text() == "ключи провайдера OpenRouter, настроено ранее"
    assert not view.embedding_legacy_reset_button.isHidden()
    view.language_check.setChecked(False)
    assert view.qa_settings().embedding_key_provider == "openrouter"

    _select(view, "gemini")

    assert view.qa_settings().embedding_key_provider == "gemini"
    assert view.embedding_legacy_reset_button.isHidden()


def test_typing_an_own_key_replaces_a_legacy_key_provider(qt_app):
    view = QualitySettingsView(
        QaSettings(
            embedding_provider="openai_compatible",
            embedding_key_provider="openrouter",
            embedding_base_url="https://openrouter.ai/api/v1",
        )
    )
    assert view.qa_settings().embedding_key_provider == "openrouter"

    view.embedding_key_edit.setText("sk-own")
    settings = view.qa_settings()

    assert (settings.embedding_key_provider, settings.embedding_api_key) == ("", "sk-own")


def test_the_reset_button_forgets_a_legacy_key_provider(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="openrouter"),
        key_counter=lambda provider_id, model_id: (2, 2),
    )
    published = _published(view)

    view.embedding_legacy_reset_button.click()

    assert published[-1].embedding_key_provider == "gemini"
    assert view.embedding_keys_chip.text() == "2 из 2 работают"


def test_a_key_once_picked_for_gemini_is_replaced_on_the_first_edit(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_api_key="AIza-picked-from-a-list")
    )
    published = _published(view)

    view.language_check.setChecked(False)

    assert published[-1].embedding_api_key == ""
    assert published[-1].embedding_key_provider == "gemini"


def test_auto_says_the_session_keys_are_used(qt_app):
    view = QualitySettingsView(QaSettings())

    assert view.embedding_keys_label.text() == "ключи текущей сессии перевода"
    assert view.embedding_keys_chip.isHidden()


def test_an_incomplete_setup_is_explained_in_the_card(qt_app):
    view = QualitySettingsView(QaSettings())

    _select(view, "openai_compatible")

    assert "ключ" in view.embedding_result_label.text().lower()


def test_the_probe_asks_with_the_current_settings_and_its_answer_lands_in_the_card(qt_app):
    view = QualitySettingsView(QaSettings())
    asked: list[QaSettings] = []
    view.embedding_test_requested.connect(asked.append)

    view.embedding_test_button.click()
    view.set_embedding_result("Подключение работает: gemini, модель x, 3 измерений.")

    assert asked and asked[-1].embedding_provider == "auto"
    assert view.embedding_result_label.text().startswith("Подключение работает")


def test_cometkiwi_lives_in_its_own_card_and_round_trips(qt_app):
    view = QualitySettingsView(
        QaSettings(
            capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
            cometkiwi_endpoint="http://192.168.1.50:8765",
            cometkiwi_model="wmt22-cometkiwi-da",
            cometkiwi_license_accepted=True,
        )
    )

    assert view.cometkiwi_enabled_check.isChecked()
    assert QaCapabilityKey.COMETKIWI not in view.capability_checks

    view.cometkiwi_enabled_check.setChecked(False)

    assert view.qa_settings().capabilities.cometkiwi_enabled is False


def test_values_the_window_does_not_show_survive_an_edit(qt_app):
    """Старое окно сбрасывало эти два значения к умолчаниям при каждой правке."""
    view = QualitySettingsView(
        QaSettings(batch_concurrency=3, auto_fix_language_categories=("typo",))
    )
    published = _published(view)

    view.final_pass_check.setChecked(False)

    assert published[-1].batch_concurrency == 3
    assert published[-1].auto_fix_language_categories == ("typo",)


def test_the_result_line_says_the_connection_was_not_checked_yet(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini")
    )

    assert view.embedding_result_label.text() == "Подключение ещё не проверялось."


def test_an_unrelated_edit_keeps_the_probe_answer(qt_app):
    """Ответ проверки пропадал при любой правке, даже галочки в другой карточке."""
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini")
    )
    view.embedding_test_button.click()
    view.set_embedding_result("Подключение работает: gemini, модель x, 3 измерений.")

    view.final_pass_check.setChecked(False)

    assert view.embedding_result_label.text().startswith("Подключение работает")


def test_changing_the_embedding_setup_retires_the_old_answer(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini")
    )
    view.embedding_test_button.click()
    view.set_embedding_result("Подключение работает: gemini, модель x, 3 измерений.")

    view.embedding_model_combo.setEditText("text-embedding-004")

    assert view.embedding_result_label.text() == "Подключение ещё не проверялось."


def _configured_pc(**overrides) -> QaSettings:
    values = {
        "capabilities": QaCapabilitySettings(cometkiwi_enabled=True),
        "cometkiwi_endpoint": "http://192.168.1.50:8765",
        "cometkiwi_model": "wmt22-cometkiwi-da",
        "cometkiwi_license_accepted": True,
    }
    values.update(overrides)
    return QaSettings(**values)


def test_a_configured_pc_says_the_connection_was_not_checked_yet(qt_app):
    """Карточка CometKiwi молчала, пока не нажмёшь «Проверить связь»."""
    view = QualitySettingsView(_configured_pc())

    assert view.cometkiwi_status_label.text() == "Связь с ПК ещё не проверялась."


def test_a_connection_answer_survives_an_edit_in_another_card(qt_app):
    view = QualitySettingsView(_configured_pc(cometkiwi_endpoint="192.168.1.50:8765"))

    view.cometkiwi_check_button.click()
    answer = view.cometkiwi_status_label.text()
    view.final_pass_check.setChecked(False)

    assert answer == "Адрес не разобран: нужен вид http://host:port."
    assert view.cometkiwi_status_label.text() == answer


def test_changing_the_pc_settings_retires_the_old_answer(qt_app):
    view = QualitySettingsView(_configured_pc(cometkiwi_endpoint="192.168.1.50:8765"))
    view.cometkiwi_check_button.click()

    view.cometkiwi_endpoint_edit.setText("http://192.168.1.77:8765")

    assert view.cometkiwi_status_label.text() == "Связь с ПК ещё не проверялась."


def test_the_languagetool_address_sits_under_its_own_switch(qt_app):
    """Поле адреса стояло после Slovnet, оторванное от своего переключателя."""
    from PyQt6.QtCore import QPoint

    view = QualitySettingsView(QaSettings())
    view.resize(1100, 900)
    view.show()
    qt_app.processEvents()
    try:
        def origin(widget):
            return widget.mapTo(view, QPoint(0, 0))

        language_tool = view.capability_checks[QaCapabilityKey.LANGUAGE_TOOL]
        slovnet = view.capability_checks[QaCapabilityKey.SLOVNET]
        address = view.language_tool_endpoint_edit

        assert origin(language_tool).y() < origin(address).y() < origin(slovnet).y()
        assert origin(address).x() > origin(language_tool).x()
    finally:
        view.close()
        view.deleteLater()


def test_the_cometkiwi_card_says_what_it_scores(qt_app):
    """Без этой строки казалось, что CometKiwi оценивает главы и без проверки полноты."""
    view = QualitySettingsView(QaSettings())

    text = view.cometkiwi_scope_label.text()

    assert "проверкой полноты" in text


def test_the_cometkiwi_card_says_it_also_weighs_the_refused_fixes(qt_app):
    """CometKiwi подсказывает и по отклонённым правкам, в том числе без проверки полноты."""
    view = QualitySettingsView(QaSettings())

    text = view.cometkiwi_scope_label.text()

    assert "отклонённой правки" in text
    assert "орфографию и грамматику CometKiwi не судит" in text
