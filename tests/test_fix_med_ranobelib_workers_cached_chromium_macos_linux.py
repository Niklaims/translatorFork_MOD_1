# -*- coding: utf-8 -*-
"""ranobelib/bugs/6-cached-chromium-finder-windows.

`_find_cached_chromium_executable` (ranobelib/workers.py) фолбэком ищет
кэшированный Chromium в playwright_runtime/ms-playwright. Базовый шаблон
(в qidian_rulate/playwright_launcher._BASE_CHROMIUM_GLOB) заточен под
Windows-раскладку каталогов Playwright ("chrome-win*/chrome.exe"), а
ranobelib-специфичный `_RANOBELIB_EXTRA_CHROMIUM_GLOBS` до фикса добавлял
только Windows-вариант chrome-headless-shell. На macOS и на Linux ни один
из шаблонов не совпадал, и фолбэк на реально существующий забандленный
кэш браузера никогда не срабатывал.

Раскладки каталогов/имён исполняемых файлов в тестах ниже - реальные,
подтверждённые по EXECUTABLE_PATHS установленного в .venv playwright
(driver/package/lib/coreBundle.js): headed-сборка Chromium на macOS
называется "Google Chrome for Testing.app", а не "Chromium.app" (это
раньше давало ложно-зелёный тест: раскладка в нём не встречается ни у
одного пользователя, поэтому реальный macOS-сценарий оставался
сломанным несмотря на "зелёный" тест).

Тест воспроизводит реальные тела функций (без моков логики поиска) на
временных каталогах, имитирующих раскладку кэша Playwright.
"""

import os
import sys

TESTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
RANOBELIB_DIR = os.path.join(PROJECT_ROOT, "ranobelib")

if RANOBELIB_DIR not in sys.path:
    sys.path.insert(0, RANOBELIB_DIR)

from workers import _find_cached_chromium_executable  # noqa: E402


def _patch_cache_roots(monkeypatch, root):
    # Реальные корни поиска (LOCALAPPDATA/CWD/PLAYWRIGHT_BROWSERS_PATH)
    # подменяются одним временным каталогом - сама логика сборки globs и
    # выбора самой свежей ревизии остаётся боевой (см. аналогичный приём в
    # tests/test_ranobelib_epub_parser.py::test_cached_chromium_prefers_newest_revision).
    monkeypatch.setattr(
        "qidian_rulate.playwright_launcher._candidate_browser_cache_roots",
        lambda extra_roots=(): [root],
    )


def test_find_cached_chromium_executable_matches_macos_chrome_cache(monkeypatch, tmp_path):
    # Реальная раскладка кэша Playwright на macOS (mac-arm64): каталог
    # "chrome-mac-arm64", приложение "Google Chrome for Testing.app" - НЕ
    # "Chromium.app".
    executable = (
        tmp_path
        / "chromium-1300"
        / "chrome-mac-arm64"
        / "Google Chrome for Testing.app"
        / "Contents"
        / "MacOS"
        / "Google Chrome for Testing"
    )
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    _patch_cache_roots(monkeypatch, tmp_path)

    assert _find_cached_chromium_executable() == executable


def test_find_cached_chromium_executable_matches_legacy_macos_chromium_app_cache(monkeypatch, tmp_path):
    # Легаси-раскладка (старый "Chromium.app") - шаблон оставлен в кортеже
    # для уже существующих у пользователей старых кэшей, продолжает работать.
    executable = tmp_path / "chromium-1300" / "chrome-mac-arm64" / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    _patch_cache_roots(monkeypatch, tmp_path)

    assert _find_cached_chromium_executable() == executable


def test_find_cached_chromium_executable_matches_linux_chrome_cache(monkeypatch, tmp_path):
    executable = tmp_path / "chromium-1300" / "chrome-linux64" / "chrome"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    _patch_cache_roots(monkeypatch, tmp_path)

    assert _find_cached_chromium_executable() == executable


def test_find_cached_chromium_executable_matches_macos_headless_shell_cache(monkeypatch, tmp_path):
    executable = (
        tmp_path / "chromium_headless_shell-1300" / "chrome-headless-shell-mac-x64" / "chrome-headless-shell"
    )
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    _patch_cache_roots(monkeypatch, tmp_path)

    assert _find_cached_chromium_executable() == executable


def test_find_cached_chromium_executable_matches_linux_headless_shell_cache(monkeypatch, tmp_path):
    executable = (
        tmp_path / "chromium_headless_shell-1300" / "chrome-headless-shell-linux64" / "headless_shell"
    )
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    _patch_cache_roots(monkeypatch, tmp_path)

    assert _find_cached_chromium_executable() == executable


def test_find_cached_chromium_executable_matches_linux_arm64_headless_shell_cache(monkeypatch, tmp_path):
    # non-cft сборка linux-arm64: каталог "chrome-linux" (без суффикса
    # "-headless-shell-linux*"), файл "headless_shell".
    executable = tmp_path / "chromium_headless_shell-1300" / "chrome-linux" / "headless_shell"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    _patch_cache_roots(monkeypatch, tmp_path)

    assert _find_cached_chromium_executable() == executable


def test_find_cached_chromium_executable_prefers_headed_over_headless_shell(monkeypatch, tmp_path):
    # Все вызовы _launch_persistent_chromium_context в ranobelib идут с
    # headless=False по умолчанию, поэтому при наличии в кэше и headed-, и
    # headless-only бинарника фолбэк обязан выбрать headed-вариант, иначе
    # окно логина показать будет нечем. _revision_from_path парсит ревизию
    # только из "chromium-<N>" (у "chromium_headless_shell-<N>" - подчёркивание,
    # ревизия = -1), поэтому headed-путь с положительной ревизией должен
    # выигрывать max() по ревизии независимо от того, какая из двух ревизий
    # "новее" по числу.
    headed = (
        tmp_path
        / "chromium-1300"
        / "chrome-mac-arm64"
        / "Google Chrome for Testing.app"
        / "Contents"
        / "MacOS"
        / "Google Chrome for Testing"
    )
    headed.parent.mkdir(parents=True)
    headed.write_text("", encoding="utf-8")

    headless = tmp_path / "chromium_headless_shell-9999" / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
    headless.parent.mkdir(parents=True)
    headless.write_text("", encoding="utf-8")

    _patch_cache_roots(monkeypatch, tmp_path)

    assert _find_cached_chromium_executable() == headed
