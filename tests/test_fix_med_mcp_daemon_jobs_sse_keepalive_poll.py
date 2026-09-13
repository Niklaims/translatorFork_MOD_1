"""Регресс для perf:cpu-idle-background/2-mcp-sse-keepalive-10hz-poll.

Дефект: обработчик GET /sse (Handler._serve_sse) читал очередь событий через
event_queue.get(timeout=0.1) — фиксированный таймаут 10 раз/с, хотя keepalive
реально нужен раз в SSE_KEEPALIVE_INTERVAL_SECONDS=15.0. Queue.get(timeout=X)
мгновенно просыпается, как только в очередь что-то кладут (event_queue.put) —
короткий фиксированный таймаут не нужен для доставки сообщений, только чтобы
периодически проверять «не пора ли keepalive». Из-за этого поток каждой
подключённой по SSE сессии просыпался 10 раз в секунду вместо ~1 раза в 15с
всё время, пока клиент подключён.

Тест проверяет алгоритмическое свойство — сколько раз реально был вызван
event_queue.get() до первой попытки отправить keepalive, а не секунды
настоящего времени: очередь и time.monotonic() подменены управляемыми
подставными объектами, которые продвигают виртуальные часы ровно на
переданный timeout при каждом вызове .get().

Патч часов сужен до пространства имён модуля daemon: подменяется САМ ОБЪЕКТ
`daemon_mod.time` (module-level имя внутри daemon.py) на прокси, который
форвардит всё, кроме monotonic, в настоящий модуль time — а не атрибут
настоящего стандартного модуля time.monotonic, который иначе оказался бы
подменён ПРОЦЕССНО и был бы виден любому другому потоку/таймеру, живущему
во время теста.
"""

from __future__ import annotations

import os
import tempfile
import time as real_time
import unittest
from queue import Empty

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gemini_translator.mcp import daemon as daemon_mod


class _ClockTimeProxy:
    """Прокси на месте daemon_mod.time: monotonic() берёт из теста,
    остальные атрибуты (не используемые daemon.py, но на всякий случай)
    форвардятся в настоящий модуль time. Не трогает сам объект стандартного
    модуля time — правится только имя `time` внутри daemon_mod."""

    def __init__(self, clock: list):
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock[0]

    def __getattr__(self, name):
        return getattr(real_time, name)


class _Headers:
    def get(self, key, default=None):
        return default


class _FakeWfile:
    """Собирает записи; выход из бесконечного SSE-цикла — по первой попытке
    отправить keepalive (данные содержат b"keepalive"), которую мы намеренно
    рвём OSError — ровно так же, как обрыв реального соединения клиентом."""

    def __init__(self):
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)
        if b"keepalive" in data:
            raise OSError("тестовый обрыв соединения на первом keepalive")

    def flush(self) -> None:
        pass


def _make_clock_queue(clock: list, calls: list):
    class _ClockQueue:
        def __init__(self) -> None:
            pass

        def get(self, timeout=None):
            calls.append(timeout)
            clock[0] += timeout
            raise Empty()

        def put(self, item) -> None:  # pragma: no cover - не используется в этом сценарии
            pass

    return _ClockQueue


class SseKeepalivePollFrequencyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_sse_loop_polls_queue_only_a_few_times_before_keepalive(self):
        clock = [0.0]
        calls: list[float] = []

        real_queue_cls = daemon_mod.Queue
        daemon_mod.Queue = _make_clock_queue(clock, calls)
        self.addCleanup(setattr, daemon_mod, "Queue", real_queue_cls)

        real_time_module = daemon_mod.time
        daemon_mod.time = _ClockTimeProxy(clock)
        self.addCleanup(setattr, daemon_mod, "time", real_time_module)

        daemon = daemon_mod.McpDaemon(self._tmp.name, host="127.0.0.1", port=0, concurrency=1)
        handler_cls = daemon._make_handler()
        handler = handler_cls.__new__(handler_cls)
        handler.headers = _Headers()
        handler.wfile = _FakeWfile()
        handler.requestline = "GET /sse HTTP/1.1"
        handler.request_version = "HTTP/1.1"

        # Метод сам ловит OSError из wfile.write (обрыв соединения) и не
        # поднимает исключение наружу — после него сессия должна быть снята.
        handler._serve_sse()

        self.assertGreaterEqual(clock[0], daemon_mod.SSE_KEEPALIVE_INTERVAL_SECONDS)
        # Раньше фиксированный таймаут 0.1с требовал ~150 вызовов get(), чтобы
        # виртуальные часы дошли до 15с. Динамический таймаут, рассчитанный
        # на оставшееся до keepalive время, должен обходиться единицами
        # вызовов независимо от длины периода ожидания.
        self.assertLessEqual(
            len(calls),
            3,
            f"event_queue.get() вызван {len(calls)} раз(а) до keepalive — таймаут не подстраивается",
        )
        self.assertEqual(daemon._sse_sessions, {})


if __name__ == "__main__":
    unittest.main()
