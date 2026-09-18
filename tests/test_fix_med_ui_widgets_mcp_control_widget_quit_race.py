"""Регрессия для ui-widgets-b/bugs/3-mcp-daemon-leak-on-quit-race.

Гонка: пользователь запускает MCP-демон (toggle → старт) и почти сразу
закрывает приложение, до того как главный поток успел обработать сигнал
`worker.finished`/`thread.finished` завершившегося воркера. `_stop_on_app_quit`
выставляется в True только внутри `_update_stop_on_quit_policy`, которая
вызывается из `_finish_worker_action` — то есть только ПОСЛЕ обработки этих
сигналов. Если `_on_app_about_to_quit` в момент вызова видит флаг ещё False,
она обязана дождаться воркера сама и учесть его реальный результат, а не
просто выйти — иначе демон, который к тому моменту уже реально поднялся,
остаётся сиротой.
"""

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from gemini_translator.ui.widgets.mcp_control_widget import (
    McpControlWidget,
    McpStatusSnapshot,
)


class _StatefulBlockingBackend:
    """Бэкенд с реальным (пусть и фейковым) состоянием демона: в отличие от
    статичных фейков в test_mcp_control_widget.py, его status() отражает,
    поднят ли демон на самом деле — это нужно, чтобы проверить, что виджет
    после гонки честно спрашивает состояние, а не доверяет устаревшему кэшу.
    start() блокируется до явного release(), чтобы детерминированно
    воспроизвести «воркер ещё выполняется, когда пришёл сигнал о закрытии».
    status() умеет блокироваться так же (через block_status/status_release) —
    это нужно для проверки, что фоновый опрос статуса НЕ дожидается при
    закрытии приложения (в отличие от toggle)."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.started = 0
        self.stopped = 0
        self.status_calls = 0
        self.block_status = False
        self.status_entered = threading.Event()
        self.status_release = threading.Event()
        self._running = False

    def status(self):
        self.status_calls += 1
        if self.block_status:
            self.status_entered.set()
            self.status_release.wait(2)
        if self._running:
            return McpStatusSnapshot(running=True, detail="127.0.0.1:4567")
        return McpStatusSnapshot(running=False, detail="stdio + local daemon")

    def start(self):
        self.started += 1
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError("timed out waiting for release")
        self._running = True
        return McpStatusSnapshot(running=True, detail="127.0.0.1:4567")

    def stop(self):
        self.stopped += 1
        self._running = False
        return McpStatusSnapshot(running=False, detail="stdio + local daemon")

    def codex_config(self):
        return "x"


class McpDaemonQuitRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _process_events_until(self, condition, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        self.app.processEvents()
        return condition()

    def test_app_quit_race_does_not_leak_daemon_started_just_before_close(self):
        backend = _StatefulBlockingBackend()
        widget = McpControlWidget(backend=backend)
        self.addCleanup(widget.close)

        # Дожидаемся, пока уляжется возможный boot-probe виджета.
        self.assertTrue(self._process_events_until(lambda: widget._worker_thread is None))

        # Пользователь жмёт «Запустить»: воркер уходит в фоновый поток и
        # входит в backend.start(), но ещё не завершился.
        widget.action_button.click()
        self.assertTrue(backend.entered.wait(1))
        thread = widget._worker_thread
        self.assertIsNotNone(thread)

        # Главный поток ещё не обработал очередь событий этого воркера —
        # колбэк _finish_worker_action не отработал, флаг ещё не выставлен.
        self.assertFalse(widget._stop_on_app_quit)

        # Приложение почти сразу закрывается: aboutToQuit долетает до
        # виджета, пока воркер ещё выполняет реальный backend.start().
        # Освобождаем backend.start() через 50мс — воркер должен успеть
        # реально «поднять демон» до того, как _on_app_about_to_quit
        # закончит работу.
        release_timer = threading.Timer(0.05, backend.release.set)
        release_timer.start()
        try:
            widget._on_app_about_to_quit()
        finally:
            release_timer.cancel()
            backend.release.set()

        # closeEvent следом безусловно зовёт _wait_for_worker() как
        # подстраховку — воспроизводим и это; после исправления это уже
        # не должно ничего доделывать (всё улажено выше).
        widget._wait_for_worker()

        self.assertTrue(self._process_events_until(lambda: widget._worker_thread is None))
        self.assertEqual(backend.started, 1)
        self.assertEqual(
            backend.stopped,
            1,
            "демон, поднятый прямо перед закрытием приложения, не должен оставаться сиротой",
        )
        self.assertFalse(widget._stop_on_app_quit)

    def test_app_quit_race_uses_pending_result_without_extra_status_call(self):
        """Второй вариант той же гонки: результат toggle уже доставлен в
        _pending_worker_result через _on_worker_finished, но thread.finished
        ещё не обработан — widget._worker_thread ещё не сброшен в None.
        _on_worker_finished выставляет _pending_worker_result и зовёт
        thread.quit(), но НЕ трогает self._worker_thread — это делает только
        _finish_worker_action по сигналу thread.finished, который ещё не
        долетел. Такое промежуточное состояние воспроизводим напрямую
        (не запущенный QThread), чтобы не гоняться за микросекундным окном
        между двумя сигналами через реальные потоки."""
        backend = _StatefulBlockingBackend()
        widget = McpControlWidget(backend=backend)
        self.addCleanup(widget.close)
        self.assertTrue(self._process_events_until(lambda: widget._worker_thread is None))
        # boot_probe виджета мог сам дёрнуть backend.status() (если на
        # машине реально есть daemon-info файл от постороннего MCP-демона) —
        # сбрасываем счётчик, чтобы проверять только вызовы из-под гонки.
        backend.status_calls = 0

        fake_thread = QtCore.QThread()
        self.addCleanup(fake_thread.deleteLater)
        self.assertFalse(fake_thread.isRunning())
        widget._worker_thread = fake_thread
        widget._worker = None
        widget._worker_action = "toggle"
        widget._worker_was_running = False
        snapshot = McpStatusSnapshot(running=True, detail="127.0.0.1:4567")
        widget._pending_worker_result = ("toggle", False, snapshot)
        backend._running = True

        widget._on_app_about_to_quit()

        self.assertEqual(
            backend.status_calls,
            0,
            "результат уже был доставлен в _pending_worker_result — лишний backend.status() не нужен",
        )
        self.assertEqual(backend.stopped, 1)
        self.assertFalse(widget._stop_on_app_quit)

    def test_status_action_in_flight_does_not_block_app_quit(self):
        """Регрессия: фоновый опрос статуса (action == "status", тикает
        каждые 2.5с, пока карточка видима) не имеет отношения к гонке
        toggle/quit и не должен дожидаться при закрытии — иначе aboutToQuit
        блокируется на время сетевого backend.status() (до 5с в проде)."""
        backend = _StatefulBlockingBackend()
        widget = McpControlWidget(backend=backend)
        self.addCleanup(widget.close)
        self.assertTrue(self._process_events_until(lambda: widget._worker_thread is None))

        backend.block_status = True
        widget.refresh_status()
        self.assertTrue(backend.status_entered.wait(1))
        self.assertIsNotNone(widget._worker_thread)
        self.assertEqual(widget._worker_action, "status")

        # Подстраховка: если баг всё же вернётся (aboutToQuit дожидается
        # "status"), тест не подвиснет навсегда — отпускаем воркер через
        # 300мс и сравниваем с этим порогом по времени.
        safety_release = threading.Timer(0.3, backend.status_release.set)
        safety_release.start()
        try:
            started_at = time.monotonic()
            widget._on_app_about_to_quit()
            elapsed = time.monotonic() - started_at
        finally:
            safety_release.cancel()
            backend.status_release.set()

        self.assertLess(
            elapsed,
            0.15,
            "aboutToQuit не должен ждать фоновый опрос статуса (action == 'status')",
        )
        self.assertTrue(self._process_events_until(lambda: widget._worker_thread is None))


if __name__ == "__main__":
    unittest.main()
