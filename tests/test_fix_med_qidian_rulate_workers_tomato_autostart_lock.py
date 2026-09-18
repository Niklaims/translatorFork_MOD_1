# -*- coding: utf-8 -*-
"""Регресс на находку qidian-tools/bugs/5-tomato-autostart-process-race.

`_start_tomato_web_server` читал/писал модульные глобалы
`_TOMATO_AUTOSTART_PROCESS`/`_TOMATO_AUTOSTART_CLEANUP_REGISTERED` без
блокировки. Два параллельных воркера (например, AiPrepareWorker и
CoverPromptWorker для источника Fanqie), увидев `_TOMATO_AUTOSTART_PROCESS
is None` одновременно, могли оба запустить `subprocess.Popen(...)` —
получаем два процесса Tomato Web UI вместо одного.

Тест воспроизводит гонку на реальном коде: два потока параллельно зовут
`_start_tomato_web_server` с фейковым `_find_tomato_executable`, который
искусственно расширяет окно между чтением глобала и `subprocess.Popen` —
если блокировки нет, оба потока успевают попасть в это окно почти
одновременно (они стартуют вместе) и оба доходят до поиска исполняемого
файла и запуска процесса. Если правильная блокировка есть, второй поток
блокируется на входе в критическую секцию и, войдя туда после первого,
видит уже присвоенный `_TOMATO_AUTOSTART_PROCESS` и не зовёт
`_find_tomato_executable`/`subprocess.Popen` вовсе."""

import threading
import time
from pathlib import Path

import pytest

from qidian_rulate import workers


class _FakePopen:
    """Достаточно похож на subprocess.Popen, чтобы пройти check-then-act:
    poll() всегда возвращает None (процесс "жив"), реальный процесс не
    стартует."""

    instances = []

    def __init__(self, *args, **kwargs):
        _FakePopen.instances.append(self)

    def poll(self):
        return None

    def terminate(self):
        pass


@pytest.fixture(autouse=True)
def _reset_tomato_globals(monkeypatch):
    monkeypatch.setattr(workers, "_TOMATO_AUTOSTART_PROCESS", None)
    monkeypatch.setattr(workers, "_TOMATO_AUTOSTART_CLEANUP_REGISTERED", False)
    monkeypatch.setattr(workers.atexit, "register", lambda *a, **k: None)
    _FakePopen.instances = []
    yield


def test_two_concurrent_callers_start_tomato_only_once(monkeypatch):
    def slow_find_executable():
        # Оба потока (без блокировки) стартуют почти одновременно и попадают
        # сюда в одном и том же узком окне между чтением
        # _TOMATO_AUTOSTART_PROCESS и его присвоением — расширяем окно
        # небольшой паузой, чтобы воспроизвести гонку детерминированно, а не
        # по случайности шедулера. С правильной блокировкой сюда попадает
        # только один поток - второй ждёт снаружи критической секции и уже
        # видит присвоенный процесс.
        time.sleep(0.05)
        return Path("fake-tomato.exe")

    monkeypatch.setattr(workers, "_find_tomato_executable", slow_find_executable)
    monkeypatch.setattr(workers, "_tomato_auto_start_enabled", lambda: True)
    monkeypatch.setattr(workers, "_tomato_web_is_local", lambda base_url: True)
    monkeypatch.setattr(workers.subprocess, "Popen", _FakePopen)
    # Оба потока сразу же "видят" сервер готовым - дальше нас интересует
    # только сколько раз был запущен subprocess.Popen.
    monkeypatch.setattr(
        workers,
        "TOMATO_STARTUP_TIMEOUT_SECONDS",
        0.01,
    )

    class _FakeSession:
        def get(self, *args, **kwargs):
            raise workers.requests.RequestException("no network in test")

    results = []

    def call():
        results.append(
            workers._start_tomato_web_server(
                _FakeSession(), "http://127.0.0.1:9999", {}, log_callback=None,
            )
        )

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(_FakePopen.instances) == 1, (
        "Два параллельных вызова _start_tomato_web_server запустили "
        f"{len(_FakePopen.instances)} процессов Tomato вместо одного — "
        "гонка за чтением/записью _TOMATO_AUTOSTART_PROCESS не устранена"
    )
