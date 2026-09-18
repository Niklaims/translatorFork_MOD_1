# -*- coding: utf-8 -*-
"""Регресс на находку qidian-tools/bugs/6-rulate-fill-worker-unstoppable.

`RulateFillWorker.run()`/`RulateLoginWorker.run()` входили в
`try: while True: page.wait_for_timeout(1000) except Exception: pass` и
выходили из цикла только когда пользователь сам закрывал окно браузера
(Playwright бросает исключение при обращении к закрытой странице) — флага
остановки не было (в отличие от AiPrepareWorker с `_cancel_event`), поэтому
уход со страницы Qidian Creator без закрытия браузера оставлял QThread и
процесс Chromium жить в памяти.

Цикл ожидания вынесен в отдельную функцию `_wait_until_browser_closed_or_interrupted`,
которую оба run() зовут с `self._cancel_event.is_set` (по образцу
`AiPrepareWorker._cancel_event`) — новый метод `cancel()` даёт
странице-хозяину способ остановить воркер программно. Сознательно НЕ
`QThread.isInterruptionRequested`/`requestInterruption()`: Qt делает
`requestInterruption()` no-op, пока поток не запущен через `.start()`, что
сделало бы этот путь непроверяемым синхронным вызовом run() в тесте.
Тесты проверяют и саму функцию, и реальную маршрутизацию run() через неё
(доводя run() до цикла ожидания на фейковом Playwright-окружении, без
настоящего браузера)."""

from types import SimpleNamespace

import playwright.sync_api as _real_playwright_sync_api

from qidian_rulate import workers


class _CountingPage:
    """Фейковая playwright-страница: считает вызовы wait_for_timeout и не
    падает сама по себе (реальная страница падает только когда пользователь
    закрывает окно браузера — здесь мы проверяем остановку ДО этого)."""

    def __init__(self, stop_after):
        self.calls = 0
        self._stop_after = stop_after

    def wait_for_timeout(self, ms):
        self.calls += 1
        # Предохранитель от зависания теста, если регрессия вернётся:
        # `while True` без проверки should_stop крутился бы здесь бесконечно.
        if self.calls > self._stop_after + 50:
            raise RuntimeError("wait loop did not stop — should_stop() ignored")


def test_wait_loop_stops_once_should_stop_returns_true():
    page = _CountingPage(stop_after=3)

    def should_stop():
        return page.calls >= 3

    workers._wait_until_browser_closed_or_interrupted(page, should_stop)

    assert page.calls == 3, (
        "Цикл ожидания должен останавливаться сразу, как только should_stop() "
        "вернул True, а не крутиться до закрытия страницы пользователем"
    )


def test_wait_loop_still_stops_on_page_exception_when_never_asked_to_stop():
    # Поведение по умолчанию (пользователь сам закрыл браузер) не должно
    # измениться: исключение от page по-прежнему тихо завершает ожидание.
    class _RaisingPage:
        def __init__(self):
            self.calls = 0

        def wait_for_timeout(self, ms):
            self.calls += 1
            if self.calls == 2:
                raise Exception("target page, context or browser has been closed")

    page = _RaisingPage()
    workers._wait_until_browser_closed_or_interrupted(page, lambda: False)

    assert page.calls == 2


class _FakeLocator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class _FakeBrowser:
    def __init__(self, page):
        self.pages = [page]


class _FakePlaywrightContextManager:
    def __enter__(self):
        return SimpleNamespace()

    def __exit__(self, *args):
        return False


def _patch_common_playwright_plumbing(monkeypatch, page):
    """Прогоняет run() до цикла ожидания на фейковом Playwright/форме, не
    поднимая настоящий браузер."""
    monkeypatch.setattr(workers.api_config, "configure_playwright_runtime", lambda: None)
    monkeypatch.setattr(_real_playwright_sync_api, "sync_playwright", lambda: _FakePlaywrightContextManager())
    monkeypatch.setattr(
        workers, "_launch_persistent_chromium_context", lambda *args, **kwargs: _FakeBrowser(page)
    )


def test_rulate_fill_worker_run_stops_on_interruption_instead_of_forever(monkeypatch):
    worker = workers.RulateFillWorker(draft=object())

    class _FillFormPage:
        def __init__(self):
            self.wait_calls = 0

        def locator(self, selector):
            return _FakeLocator(count=1)  # форма #form-edit уже найдена

        def wait_for_timeout(self, ms):
            self.wait_calls += 1
            if self.wait_calls == 3:
                worker.cancel()
            if self.wait_calls > 50:
                raise RuntimeError("run() wait loop did not stop on cancel()")

    page = _FillFormPage()
    _patch_common_playwright_plumbing(monkeypatch, page)
    monkeypatch.setattr(workers.RulateFillWorker, "_select_catalog_category", lambda self, p: True)
    monkeypatch.setattr(workers.RulateFillWorker, "_fill_general", lambda self, p: None)
    monkeypatch.setattr(workers.RulateFillWorker, "_upload_generated_cover", lambda self, p: None)
    monkeypatch.setattr(workers.RulateFillWorker, "_fill_description", lambda self, p: None)

    finished = []
    worker.finished_signal.connect(lambda: finished.append(True))
    error_logs = []
    worker.log_signal.connect(lambda level, msg: error_logs.append(msg) if level == "ERROR" else None)

    worker.run()

    assert finished == [True], "run() обязан дойти до finally и эмитировать finished_signal"
    assert not error_logs, f"run() не должен падать с ошибкой: {error_logs}"
    assert page.wait_calls == 3, (
        "RulateFillWorker.run() должен останавливать цикл ожидания сразу после "
        f"cancel(), а не крутиться дальше (звонков: {page.wait_calls})"
    )


def test_rulate_login_worker_run_stops_on_interruption_instead_of_forever(monkeypatch):
    worker = workers.RulateLoginWorker()

    class _LoginPage:
        def __init__(self):
            self.wait_calls = 0

        def goto(self, *args, **kwargs):
            pass

        def wait_for_timeout(self, ms):
            self.wait_calls += 1
            if self.wait_calls == 3:
                worker.cancel()
            if self.wait_calls > 50:
                raise RuntimeError("run() wait loop did not stop on cancel()")

    page = _LoginPage()
    _patch_common_playwright_plumbing(monkeypatch, page)

    finished = []
    worker.finished_signal.connect(lambda: finished.append(True))
    error_logs = []
    worker.log_signal.connect(lambda level, msg: error_logs.append(msg) if level == "ERROR" else None)

    worker.run()

    assert finished == [True]
    assert not error_logs, f"run() не должен падать с ошибкой: {error_logs}"
    assert page.wait_calls == 3, (
        "RulateLoginWorker.run() должен останавливать цикл ожидания сразу после "
        f"cancel(), а не крутиться дальше (звонков: {page.wait_calls})"
    )
