# -*- coding: utf-8 -*-
"""Регресс на находку perf:memory-churn/2-api-providers-deepcopy-not-swe
(часть про qidian_rulate/workers.py).

_run_ai_request делал `deepcopy(api_config.api_providers().get(provider_id) or {})`
и `deepcopy(api_config.all_models().get(model_name) or {})` — но
api_config.api_providers()/all_models() уже возвращают deepcopy ВСЕГО
реестра провайдеров/моделей (см. config.py: `def api_providers(): return
deepcopy(api_providers_view())`), так что извлечённая из них запись и без
дополнительной обёртки не делит память с общим кэшем. Внешний deepcopy()
поверх неё копировал уже независимую копию второй раз — двойное копирование
без какой-либо пользы. Этот внешний deepcopy() на извлечённой записи убран.

ВАЖНО (по замечанию ревью, major): убранный здесь deepcopy() — это НЕ весь
корень находки. api_config.api_providers() и api_config.all_models()
по-прежнему делают ПОЛНЫЙ deepcopy всего реестра провайдеров/моделей каждый
(причём all_models() внутри снова зовёт api_providers() — то есть на один
вызов _run_ai_request приходится ДВА полных deepcopy реестра). Настоящее
устранение корня — перейти на api_providers_view()/all_models_view() (без
копирования всего реестра) и делать точечный deepcopy() только извлечённой
записи, как в gemini_translator/core/worker.py:257
(`copy.deepcopy(api_config.api_providers_view()[...])`). Здесь это сознательно
НЕ сделано: tests/test_qidian_rulate_ai_retry.py подменяет именно
api_config.api_providers()/all_models() (не _view()-варианты), а этот файл
нельзя трогать в рамках данной задачи — переход сломал бы его без возможности
починить. См. отчёт исправителя: находка помечена blocked, а не fixed.

Проверяем алгоритмическое свойство, а не identity извлечённой записи: сам
_run_ai_request не должен добавлять НИКАКОГО дополнительного deepcopy() сверх
того, что (в этом тесте) делают сами api_providers()/all_models() — они здесь
подменены на функции без копирования, поэтому ожидаемое число deepcopy-вызовов
именно в _run_ai_request равно нулю. Identity извлечённой записи НЕ проверяем:
эта проверка ломала бы корректный будущий переход на _view() + точечный
deepcopy (там появление ровно одного "хорошего" deepcopy — ожидаемо), а
здесь важно только отсутствие ЛИШНЕГО копирования и совпадение содержимого.
"""

import copy

import pytest

from gemini_translator.api import config as api_config
from qidian_rulate import workers


def _fake_registry():
    return {
        "provider_a": {"models": {"model_a": {"id": "a"}}},  # без handler_class
    }


def _run_and_capture(monkeypatch, *, provider_id, model_name, api_providers, all_models):
    """Подменяет api_providers()/all_models() и _SingleRequestWorker, чтобы
    перехватить provider_config/model_config, с которыми _run_ai_request
    реально доходит до создания воркера (до сетевого обращения), и считает
    вызовы copy.deepcopy, сделанные САМИМ _run_ai_request по пути."""
    monkeypatch.setattr(api_config, "api_providers", api_providers)
    monkeypatch.setattr(api_config, "all_models", all_models)

    deepcopy_calls = []
    real_deepcopy = copy.deepcopy

    def counting_deepcopy(obj, *args, **kwargs):
        deepcopy_calls.append(obj)
        return real_deepcopy(obj, *args, **kwargs)

    # Патчим сам модуль copy: так ловим и `copy.deepcopy(...)`, и (для RED-
    # проверки со старой версией кода) `from copy import deepcopy` внутри
    # workers.py, если такой импорт там снова появится.
    monkeypatch.setattr(copy, "deepcopy", counting_deepcopy)
    if hasattr(workers, "deepcopy"):
        monkeypatch.setattr(workers, "deepcopy", counting_deepcopy)

    captured = {}
    original_worker_cls = workers._SingleRequestWorker

    class _RecordingWorker(original_worker_cls):
        def __init__(self, **kwargs):
            captured["provider_config"] = kwargs["provider_config"]
            captured["model_config"] = kwargs["model_config"]
            super().__init__(**kwargs)

    monkeypatch.setattr(workers, "_SingleRequestWorker", _RecordingWorker)

    with pytest.raises(ValueError, match="handler_class"):
        workers._run_ai_request(
            provider_id=provider_id,
            model_settings={"model": model_name},
            active_keys=["key"],
            settings_manager=None,
            prompt="hi",
            log_callback=lambda *a, **k: None,
            log_prefix="test",
        )
    return captured, deepcopy_calls


def test_run_ai_request_does_not_deepcopy_already_independent_provider_and_model(monkeypatch):
    registry = _fake_registry()
    models = api_config._build_all_models(registry)

    captured, deepcopy_calls = _run_and_capture(
        monkeypatch,
        provider_id="provider_a",
        model_name="model_a",
        api_providers=lambda: registry,
        all_models=lambda: models,
    )

    assert deepcopy_calls == [], (
        "_run_ai_request не должен сам копировать provider_config/model_config "
        "поверх того, что уже вернули api_providers()/all_models()"
    )
    assert captured["provider_config"] == registry["provider_a"]
    assert captured["model_config"] == models["model_a"]


def test_run_ai_request_fallback_via_provider_models_without_extra_copy(monkeypatch):
    """Модель отсутствует в глобальном all_models(), но есть у своего
    провайдера — резолв через provider_config['models'] тоже не должен
    заводить лишнюю копию извлечённой записи."""
    registry = {
        "provider_a": {"models": {"only_local_model": {"id": "a"}}},
    }

    captured, deepcopy_calls = _run_and_capture(
        monkeypatch,
        provider_id="provider_a",
        model_name="only_local_model",
        api_providers=lambda: registry,
        all_models=lambda: {},  # глобальная карта "не видит" модель
    )

    assert deepcopy_calls == []
    assert captured["model_config"] == registry["provider_a"]["models"]["only_local_model"]


def test_run_ai_request_still_raises_for_unknown_provider(monkeypatch):
    registry = _fake_registry()
    monkeypatch.setattr(api_config, "api_providers", lambda: registry)
    monkeypatch.setattr(api_config, "all_models", lambda: api_config._build_all_models(registry))

    with pytest.raises(ValueError, match="не найден в конфиге"):
        workers._run_ai_request(
            provider_id="does_not_exist",
            model_settings={"model": "model_a"},
            active_keys=["key"],
            settings_manager=None,
            prompt="hi",
            log_callback=lambda *a, **k: None,
            log_prefix="test",
        )
