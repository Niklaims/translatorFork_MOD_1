# -*- coding: utf-8 -*-
"""Регресс на находку perf:memory-churn/2-api-providers-deepcopy-not-swe
(часть про qidian_rulate/workers.py).

Было: `_run_ai_request` брал провайдера/модель через
`api_config.api_providers()`/`api_config.all_models()` — обе функции гоняют
deepcopy ВСЕГО реестра провайдеров/моделей (см. config.py:
`def api_providers(): return deepcopy(api_providers_view())`, а
`all_models()` внутри снова зовёт `api_providers()`), хотя по факту нужна
ровно одна запись (`.get(provider_id)`/`.get(model_name)`). Сверху на
извлечённую (и без того уже независимую) запись накручивался ещё один
`deepcopy()` — двойное копирование без пользы.

Стало: `_run_ai_request` читает `api_config.api_providers_view()` и
`api_config.all_models_view()` — общий кэш БЕЗ копирования всего реестра
(мутация результата этих функций напрямую портит глобальный кэш) — и делает
ТОЧЕЧНЫЙ `copy.deepcopy()` только извлечённой записи, тем же паттерном, что
уже применён в gemini_translator/core/worker.py:259-261
(`copy.deepcopy(api_config.api_providers_view()[...])`).

Проверяем два алгоритмических свойства, а не identity извлечённой записи:
1. `_run_ai_request` не читает и не мутирует напрямую объекты из
   `_view()`-кэша — после вызова содержимое view-реестра, из которого
   извлекались provider_config/model_config, не меняется (setdefault на
   model_config не протекает в общий кэш).
2. Число вызовов `copy.deepcopy` внутри `_run_ai_request` минимально и не
   удваивается: одна запись — один deepcopy (провайдер + модель = 2 вызова
   на основном пути; в fallback-ветке через `provider_config['models']`
   деньги за deepcopy уже уплачены при копировании provider_config, второй
   deepcopy там был бы лишним дублированием, как раньше был лишним внешний
   deepcopy поверх api_providers()/all_models()).
"""

import copy

import pytest

from gemini_translator.api import config as api_config
from qidian_rulate import workers


def _fake_registry():
    return {
        "provider_a": {"models": {"model_a": {"id": "a"}}},  # без handler_class
    }


def _run_and_capture(monkeypatch, *, provider_id, model_name, api_providers_view, all_models_view):
    """Подменяет api_providers_view()/all_models_view() (общий кэш БЕЗ
    копирования) и _SingleRequestWorker, чтобы перехватить
    provider_config/model_config, с которыми _run_ai_request реально доходит
    до создания воркера (до сетевого обращения), и считает вызовы
    copy.deepcopy, сделанные САМИМ _run_ai_request по пути."""
    monkeypatch.setattr(api_config, "api_providers_view", api_providers_view)
    monkeypatch.setattr(api_config, "all_models_view", all_models_view)

    deepcopy_calls = []
    real_deepcopy = copy.deepcopy

    def counting_deepcopy(obj, *args, **kwargs):
        deepcopy_calls.append(obj)
        return real_deepcopy(obj, *args, **kwargs)

    # Патчим и сам модуль copy (workers.py зовёт copy.deepcopy(...)), и
    # workers.deepcopy на случай, если модуль когда-нибудь перейдёт на
    # `from copy import deepcopy`.
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


def test_run_ai_request_reads_view_cache_and_copies_each_record_once(monkeypatch):
    registry = _fake_registry()
    models = api_config._build_all_models(registry)

    captured, deepcopy_calls = _run_and_capture(
        monkeypatch,
        provider_id="provider_a",
        model_name="model_a",
        api_providers_view=lambda: registry,
        all_models_view=lambda: models,
    )

    # Один deepcopy на provider_config, один на model_config — не ноль (иначе
    # мутации записей портили бы общий view-кэш) и не два-на-запись (иначе
    # снова было бы то самое двойное копирование).
    assert len(deepcopy_calls) == 2, (
        "_run_ai_request должен копировать ровно по одному разу извлечённые "
        "provider_config и model_config, а не 0 (порча общего кэша) и не "
        "больше 2 (повторное копирование)"
    )
    # Содержимое совпадает (setdefault здесь — no-op: 'id'/'provider' уже
    # выставлены самой _build_all_models), но это НЕЗАВИСИМЫЕ копии, а не те
    # же объекты, что лежат в общем view-кэше.
    assert captured["provider_config"] == registry["provider_a"]
    assert captured["model_config"] == models["model_a"]
    assert captured["provider_config"] is not registry["provider_a"]
    assert captured["model_config"] is not models["model_a"]


def test_run_ai_request_fallback_via_provider_models_without_extra_copy(monkeypatch):
    """Модель отсутствует в глобальном all_models_view(), но есть у своего
    провайдера — резолв через provider_config['models'] не должен заводить
    ВТОРОЙ deepcopy: provider_config уже независимая копия (из первого
    deepcopy), так что её вложенный словарь моделей копировать повторно
    незачем."""
    registry = {
        "provider_a": {"models": {"only_local_model": {"id": "a"}}},
    }

    captured, deepcopy_calls = _run_and_capture(
        monkeypatch,
        provider_id="provider_a",
        model_name="only_local_model",
        api_providers_view=lambda: registry,
        all_models_view=lambda: {},  # глобальная карта "не видит" модель
    )

    # Один deepcopy — на provider_config (модель находится внутри неё же).
    # Плюс один deepcopy пустого {} на неудачный all_models_view().get(...).
    assert len(deepcopy_calls) == 2
    original_model = registry["provider_a"]["models"]["only_local_model"]
    assert captured["model_config"]["id"] == original_model["id"]
    assert captured["model_config"] is not original_model
    # Мутация setdefault (добавляет 'provider') не протекает в исходный реестр:
    # если бы provider_config не был независимой копией, эта запись
    # мутировалась бы прямо в общем view-кэше.
    assert "provider" not in original_model
    assert captured["model_config"]["provider"] == "provider_a"


def test_run_ai_request_still_raises_for_unknown_provider(monkeypatch):
    registry = _fake_registry()
    monkeypatch.setattr(api_config, "api_providers_view", lambda: registry)
    monkeypatch.setattr(api_config, "all_models_view", lambda: api_config._build_all_models(registry))

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
