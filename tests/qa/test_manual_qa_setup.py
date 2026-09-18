"""Checking a book translated yesterday must be possible, and must say when it is not."""

from __future__ import annotations

import pytest

from gemini_translator.qa.assembly import (
    QaModelChoices,
    green_keys,
    qa_model_choices,
    resolve_manual_qa_model,
)
from gemini_translator.qa.settings import QaSettings


_PROVIDERS = {
    "gemini": {
        "models": {
            "Gemini 3.7 Flash": {"id": "gemini-3.7-flash"},
            "Gemini 3.6 Flash": {"id": "gemini-3.6-flash"},
        }
    },
    "nvidia": {"models": {"Llama 3.3": {"id": "meta/llama-3.3-70b-instruct"}}},
    "local": {"models": {}},
}


class _SettingsManager:
    def __init__(self, last_model: str = "", keys=(), blocked=()) -> None:
        self.last_model = last_model
        self.keys = list(keys)
        self.blocked = set(blocked)

    def get_last_settings(self):
        return {"model": self.last_model}

    def load_key_statuses(self):
        return [dict(item) for item in self.keys]

    def is_key_limit_active(self, key_info, model_id):
        return (key_info.get("key"), model_id) in self.blocked


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    import gemini_translator.api.config as api_config

    monkeypatch.setattr(api_config, "api_providers_view", lambda: _PROVIDERS)
    return _PROVIDERS


def _keys(*pairs):
    return [{"key": key, "provider": provider} for key, provider in pairs]


def test_a_chosen_qa_model_is_used_when_no_service_is_known():
    """Явный выбор пользователя не переспрашивается, когда сравнивать его не с чем."""
    settings = QaSettings(
        correction_model_mode="custom",
        correction_provider="openai",
        correction_model="gpt-qa",
    )

    assert resolve_manual_qa_model(_SettingsManager(), settings) == ("openai", "gpt-qa")


def test_a_chosen_qa_model_of_the_books_service_wins():
    """Выбранная модель важнее модели перевода, если это тот же сервис."""
    settings = QaSettings(
        correction_model_mode="custom",
        correction_provider="gemini",
        correction_model="gemini-3.6-flash",
    )
    manager = _SettingsManager(last_model="Gemini 3.7 Flash")

    assert resolve_manual_qa_model(manager, settings) == ("gemini", "gemini-3.6-flash")


def test_a_chosen_qa_model_of_another_service_is_not_used():
    """Книга проверяется ключами своего сервиса: чужой модели они не подойдут."""
    settings = QaSettings(
        correction_model_mode="custom",
        correction_provider="nvidia",
        correction_model="meta/llama-3.3-70b-instruct",
    )
    manager = _SettingsManager(last_model="Gemini 3.7 Flash")

    assert resolve_manual_qa_model(manager, settings) == ("gemini", "gemini-3.7-flash")


def test_the_models_offered_for_the_check_are_those_of_the_books_service():
    """Сменить модель проверки можно только в пределах сервиса, которым она идёт."""
    choices = qa_model_choices(_SettingsManager(last_model="Gemini 3.7 Flash"))

    assert choices == QaModelChoices(
        provider="gemini",
        translation_model="gemini-3.7-flash",
        models=(
            ("Gemini 3.7 Flash", "gemini-3.7-flash"),
            ("Gemini 3.6 Flash", "gemini-3.6-flash"),
        ),
    )


def test_no_service_to_check_with_offers_no_models():
    assert qa_model_choices(_SettingsManager()) is None


def test_the_last_translated_model_is_the_next_best_answer():
    """Проверять книгу разумнее той же моделью, которой её переводили."""
    manager = _SettingsManager(last_model="Gemini 3.6 Flash")

    assert resolve_manual_qa_model(manager, QaSettings()) == (
        "gemini",
        "gemini-3.6-flash",
    )


def test_a_model_saved_by_its_identifier_is_also_found():
    """В настройках может лежать и id, и отображаемое имя."""
    manager = _SettingsManager(last_model="gemini-3.7-flash")

    assert resolve_manual_qa_model(manager, QaSettings()) == (
        "gemini",
        "gemini-3.7-flash",
    )


def test_a_retired_model_falls_back_to_a_provider_the_user_works_with():
    """Настоящий случай: сохранённая модель исчезла из реестра за год."""
    manager = _SettingsManager(
        last_model="Gemini 2.5 Flash Preview",
        keys=_keys(
            ("nv-1", "nvidia"),
            ("g-1", "gemini"),
            ("g-2", "gemini"),
            ("g-3", "gemini"),
        ),
    )

    provider, model = resolve_manual_qa_model(manager, QaSettings())

    # Three Gemini keys against one NVIDIA key: the book is checked with the
    # provider the user evidently works with, not with the first row.
    assert (provider, model) == ("gemini", "gemini-3.7-flash")


def test_a_provider_without_models_is_never_chosen():
    manager = _SettingsManager(keys=_keys(("l-1", "local"), ("l-2", "local")))

    assert resolve_manual_qa_model(manager, QaSettings()) == ("", "")


def test_no_keys_at_all_is_an_honest_empty_answer():
    """Пустой ответ — сигнал сказать пользователю, а не начать невозможный проход."""
    assert resolve_manual_qa_model(_SettingsManager(), QaSettings()) == ("", "")


def test_unreadable_settings_never_raise():
    class _Broken:
        def get_last_settings(self):
            raise OSError("settings are locked")

        def load_key_statuses(self):
            raise OSError("settings are locked")

    assert resolve_manual_qa_model(_Broken(), QaSettings()) == ("", "")


# --- the key that runs it ---------------------------------------------------


def test_the_first_healthy_key_of_the_provider_is_used():
    manager = _SettingsManager(
        keys=_keys(("nv-1", "nvidia"), ("g-1", "gemini"), ("g-2", "gemini")),
        blocked=[("g-1", "gemini-3.7-flash")],
    )

    assert green_keys(manager, "gemini", "gemini-3.7-flash")[0] == "g-2"


def test_every_healthy_key_of_the_provider_is_offered_for_rotation():
    """Проверка книги в 600 глав на одном ключе умирает на третьей главе."""
    manager = _SettingsManager(
        keys=_keys(
            ("nv-1", "nvidia"), ("g-1", "gemini"), ("g-2", "gemini"), ("g-3", "gemini")
        ),
        blocked=[("g-1", "gemini-3.7-flash")],
    )

    assert green_keys(manager, "gemini", "gemini-3.7-flash") == ("g-2", "g-3")
    assert green_keys(None, "gemini", "gemini-3.7-flash") == ()
    assert green_keys(manager, "", "gemini-3.7-flash") == ()


def test_a_provider_with_only_exhausted_keys_offers_none():
    manager = _SettingsManager(
        keys=_keys(("g-1", "gemini")), blocked=[("g-1", "gemini-3.7-flash")]
    )

    assert green_keys(manager, "gemini", "gemini-3.7-flash") == ()
    assert green_keys(manager, "", "gemini-3.7-flash") == ()
    assert green_keys(None, "gemini", "gemini-3.7-flash") == ()


def test_an_unreadable_key_status_does_not_hide_the_key():
    class _Partial(_SettingsManager):
        def is_key_limit_active(self, key_info, model_id):
            raise OSError("status is unreadable")

    manager = _Partial(keys=_keys(("g-1", "gemini")))

    assert green_keys(manager, "gemini", "gemini-3.7-flash") == ("g-1",)
