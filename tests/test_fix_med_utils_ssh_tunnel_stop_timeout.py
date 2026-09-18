"""Регресс на utils-infra/bugs/3-ssh-tunnel-blocks-gui-thread.

SshTunnelManager.stop() вызывается синхронно из GUI-потока
(GlobalProxyController._sync_tunnel/shutdown при каждом отключении или
переконфигурации SSH-туннеля). Раньше stop() ждал `process.wait(timeout=3)`
после terminate(), а при таймауте — ещё раз `process.wait(timeout=3)` после
kill(), то есть до ~6 секунд блокировки GUI-потока, если ssh не реагирует на
SIGTERM мгновенно (недоступная сеть, зависший сервер).

Тест проверяет алгоритмическое свойство — фактические тайм-ауты, передаваемые
в process.wait(), должны быть короткими, а не секунды реального ожидания.

ВАЖНО (по итогам ревью): это подтверждает только смягчение симптома
(верхняя граница блокировки ~6с → ~1с), а не устранение корневой причины —
stop() всё ещё синхронный вызов из GUI-потока. Когда появится настоящий
неблокирующий фикс (terminate() → QTimer-поллинг → kill(), без
synchronous wait() вообще), этот тест на числовой бюджет утратит смысл и
должен быть заменён тестом на свойство «stop() не вызывает process.wait()
из основного потока» / «stop() возвращает управление немедленно». До тех
пор он остаётся страховкой от регресса к wait(timeout=3) x2.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.utils.ssh_tunnel import SshTunnelManager

# Общий бюджет на блокировку GUI-потока внутри stop(): сумма всех тайм-аутов
# wait() не должна превышать эту границу, иначе поток снова замирает заметно.
MAX_TOTAL_BLOCKING_SECONDS = 1.5


class _HangingProcess:
    """Процесс, который никогда не завершается сам (имитация зависшего ssh)."""

    def __init__(self):
        self.wait_timeouts = []
        self.terminated = False
        self.killed = False

    def poll(self):
        return None  # никогда не завершается сам по себе

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        import subprocess as subprocess_module
        raise subprocess_module.TimeoutExpired(cmd="ssh", timeout=timeout)


class SshTunnelStopTimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_manager(self, process):
        def popen_factory(args):
            return process

        return SshTunnelManager(popen_factory=popen_factory)

    def test_stop_bounds_total_wait_timeout_when_process_hangs(self):
        process = _HangingProcess()
        manager = self._make_manager(process)
        manager.start(
            ssh_host="h", ssh_port=22, ssh_user="root", ssh_key_path="/key", local_port=8080,
        )

        manager.stop()

        # terminate() и kill() всё ещё должны быть вызваны (поведение не меняется).
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)

        # Ключевая проверка: суммарный бюджет ожидания в wait() должен быть
        # маленьким, а не до ~6 секунд (2 x wait(timeout=3)).
        self.assertEqual(len(process.wait_timeouts), 2)
        total_timeout = sum(t or 0 for t in process.wait_timeouts)
        self.assertLessEqual(
            total_timeout,
            MAX_TOTAL_BLOCKING_SECONDS,
            "stop() должен ограничивать суммарное время блокировки GUI-потока",
        )


if __name__ == "__main__":
    unittest.main()
