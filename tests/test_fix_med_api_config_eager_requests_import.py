# -*- coding: utf-8 -*-
"""Регресс на находку perf:startup/4-api-config-eager-requests-impo.

api/config.py импортировал requests на уровне модуля, хотя он используется
только в двух функциях discovery локальных LM Studio/Ollama-моделей.

Замечание ревью (blocker): первая версия этого теста удаляла
gemini_translator.api.config из sys.modules и импортировала его заново прямо
в текущем процессе. monkeypatch.delitem возвращает на место только запись в
sys.modules, но НЕ атрибут родительского пакета gemini_translator.api —
после теста этот атрибут продолжал указывать на ВТОРОЙ, дублирующий
экземпляр модуля, рассинхронизированный с тем, что видит боевой код и
остальные тесты (в частности test_libs_libs_pytz_reset_policy.py, чьи
подмены api_providers_view переставали действовать на настоящем модуле).
Поэтому проверка отсутствия эагерного импорта теперь выполняется в отдельном
подпроцессе — состояние текущего интерпретатора вообще не трогается.
"""

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_config_module_import_does_not_eagerly_import_requests():
    """Свежая загрузка gemini_translator.api.config в чистом процессе не
    должна тянуть requests."""
    code = (
        "import sys\n"
        "import gemini_translator.api.config\n"
        "sys.exit(1 if 'requests' in sys.modules else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        "api/config.py импортировал requests на уровне модуля, хотя он "
        "нужен только для discovery локальных моделей "
        f"(stdout={result.stdout!r} stderr={result.stderr!r})"
    )


def test_ensure_requests_module_imports_lazily_on_first_real_use(monkeypatch):
    """Ленивый загрузчик реально импортирует requests при первом обращении
    и переиспользует результат при повторных вызовах (не импортирует заново)."""
    import builtins

    from gemini_translator.api import config as api_config

    monkeypatch.setattr(api_config, "requests", None)
    monkeypatch.setattr(api_config, "_requests_import_attempted", False)

    imported_names = []
    real_import = builtins.__import__

    def spy_import(name, *args, **kwargs):
        imported_names.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", spy_import)

    module = api_config._ensure_requests_module()

    assert "requests" in imported_names
    assert module is not None
    assert module.__name__ == "requests"

    imported_names.clear()
    module_again = api_config._ensure_requests_module()
    assert "requests" not in imported_names, "повторный вызов не должен переимпортировать requests"
    assert module_again is module


def test_ensure_requests_module_respects_test_patch(monkeypatch):
    """Если тест подменил api_config.requests напрямую (как test_local_model_discovery.py),
    ленивый загрузчик обязан вернуть подмену, а не затирать её реальным импортом."""
    from types import SimpleNamespace

    from gemini_translator.api import config as api_config

    fake = SimpleNamespace(get=lambda *a, **k: None, post=lambda *a, **k: None)
    monkeypatch.setattr(api_config, "requests", fake)

    assert api_config._ensure_requests_module() is fake
