"""Регресс для perf:cpu-idle-background/1-mcp-daemon-idle-poll-10hz.

Дефект: McpDaemon.serve_forever() вызывал
self._server.serve_forever(poll_interval=0.1) — accept-loop демона
просыпался 10 раз в секунду ВСЁ время жизни процесса (демон живёт днями),
независимо от того, есть ли подключённые клиенты или задачи. select()
внутри socketserver использует poll_interval только как верхнюю границу
ожидания перед проверкой флага shutdown, поэтому короткий таймаут не нужен
для отзывчивости обработки запросов (они обслуживаются немедленно через
handle_request()) — он лишь плодит бесполезные пробуждения простаивающего
демона.

Тест проверяет алгоритмическое свойство: с каким poll_interval реально
вызывается server.serve_forever(), не дожидаясь секунд реального времени —
serve_forever() ThreadingHTTPServer подменён рекордером, который сразу
возвращает управление.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gemini_translator.mcp import daemon as daemon_mod


class DaemonIdlePollIntervalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_serve_forever_uses_slow_idle_poll_interval(self):
        captured: dict = {}
        captured_event = threading.Event()
        real_serve_forever = daemon_mod._DaemonHTTPServer.serve_forever

        def fake_serve_forever(self, poll_interval=0.5):
            # Запоминаем, что реально попросил боевой код, а сам цикл
            # прогоняем с маленьким внутренним интервалом — иначе shutdown()
            # (ждёт threading.Event, который выставляет только сам
            # serve_forever при выходе) завис бы на всё время теста.
            captured["poll_interval"] = poll_interval
            captured_event.set()
            return real_serve_forever(self, poll_interval=0.01)

        daemon_mod._DaemonHTTPServer.serve_forever = fake_serve_forever
        self.addCleanup(setattr, daemon_mod._DaemonHTTPServer, "serve_forever", real_serve_forever)

        daemon = daemon_mod.McpDaemon(self._tmp.name, host="127.0.0.1", port=0, concurrency=1)
        daemon.start_in_thread()
        self.addCleanup(daemon.stop)

        self.assertTrue(captured_event.wait(timeout=5), "serve_forever ни разу не был вызван")

        # Прежнее значение 0.1 давало 10 пробуждений/с бессрочно на простое.
        # Секунда+ верхней границы ожидания перед проверкой shutdown не
        # ухудшает отзывчивость обработки запросов и команды stop().
        self.assertGreaterEqual(captured["poll_interval"], 1.0)


if __name__ == "__main__":
    unittest.main()
