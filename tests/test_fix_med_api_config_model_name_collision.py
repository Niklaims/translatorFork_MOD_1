# -*- coding: utf-8 -*-
"""Регресс на находку api/bugs/6-all-models-name-collision.

_build_all_models строит плоский словарь {display_name: {...}} по всем
провайдерам. Если у двух провайдеров совпадает отображаемое имя модели,
запись, обработанная позже, молча перезаписывает предыдущую — вторая модель
становится недостижимой по имени через all_models()/all_models_view(), без
единой строки в логе. Composite-ключ (provider_id, model_name) сломал бы
все внешние места, резолвящие модель по имени (вне зоны этого фикса), поэтому
минимальная безопасная правка — не менять формат ключа, но перестать
"молчать" о коллизии.
"""

import logging

from gemini_translator.api import config as api_config


def test_build_all_models_last_write_wins_silently_but_now_logged(caplog):
    api_config._MODEL_NAME_COLLISION_WARNED.clear()

    providers_config = {
        "local": {"models": {"My Model": {"id": "local-1"}}},
        "openrouter": {"models": {"My Model": {"id": "or-1"}}},
    }

    with caplog.at_level(logging.WARNING, logger="gemini_translator.api.config"):
        result = api_config._build_all_models(providers_config)

    # Поведение (last-write-wins) сознательно не меняем — composite-ключ
    # затронул бы резолв модели по имени за пределами этого модуля.
    assert result["My Model"]["provider"] == "openrouter"
    assert result["My Model"]["id"] == "or-1"

    collision_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING and "My Model" in record.getMessage()
    ]
    assert collision_warnings, "коллизия имён моделей между провайдерами должна попадать в лог"
    message = collision_warnings[0].getMessage()
    assert "local" in message and "openrouter" in message


def test_build_all_models_warns_only_once_per_name(caplog):
    api_config._MODEL_NAME_COLLISION_WARNED.clear()

    providers_config = {
        "local": {"models": {"My Model": {"id": "local-1"}}},
        "openrouter": {"models": {"My Model": {"id": "or-1"}}},
    }

    with caplog.at_level(logging.WARNING, logger="gemini_translator.api.config"):
        api_config._build_all_models(providers_config)
        caplog.clear()
        api_config._build_all_models(providers_config)

    collision_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING and "My Model" in record.getMessage()
    ]
    assert not collision_warnings, "повторные вызовы не должны спамить лог одной и той же коллизией"


def test_build_all_models_no_warning_without_collision():
    api_config._MODEL_NAME_COLLISION_WARNED.clear()

    providers_config = {
        "local": {"models": {"Model A": {"id": "a"}}},
        "openrouter": {"models": {"Model B": {"id": "b"}}},
    }

    result = api_config._build_all_models(providers_config)
    assert set(result.keys()) == {"Model A", "Model B"}


def test_build_all_models_warns_again_for_a_different_provider_pair(caplog):
    """Замечание ревью (minor): дедуп только по имени модели прятал бы
    вторую, независимую коллизию (с третьим провайдером) после того, как
    первая пара уже была залогирована. Дедуп должен учитывать саму пару
    провайдеров, а не только имя."""
    api_config._MODEL_NAME_COLLISION_WARNED.clear()

    with caplog.at_level(logging.WARNING, logger="gemini_translator.api.config"):
        api_config._build_all_models({
            "local": {"models": {"My Model": {"id": "local-1"}}},
            "openrouter": {"models": {"My Model": {"id": "or-1"}}},
        })
        caplog.clear()
        # То же имя, но третий провайдер — это НОВАЯ, ещё не залогированная коллизия.
        api_config._build_all_models({
            "openrouter": {"models": {"My Model": {"id": "or-1"}}},
            "custom": {"models": {"My Model": {"id": "custom-1"}}},
        })

    collision_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING and "My Model" in record.getMessage()
    ]
    assert collision_warnings, "коллизия с новым провайдером должна снова попасть в лог"
    message = collision_warnings[0].getMessage()
    assert "openrouter" in message and "custom" in message


def test_invalidate_composed_providers_resets_collision_warned_set():
    """Замечание ревью (minor): набор предупреждений не сбрасывался при
    переинициализации реестра провайдеров (там же, где инвалидируются
    _COMPOSED_PROVIDERS_CACHE/_ALL_MODELS_VIEW_CACHE), из-за чего коллизия,
    возникшая заново после правки конфигов, молчала бы навсегда."""
    api_config._MODEL_NAME_COLLISION_WARNED.clear()
    api_config._MODEL_NAME_COLLISION_WARNED.add(("some-marker", "a", "b"))

    api_config._invalidate_composed_providers()

    assert api_config._MODEL_NAME_COLLISION_WARNED == set()
