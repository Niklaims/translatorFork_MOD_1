"""После сетевой ошибки глава ждёт, а не уходит сразу на следующий ключ.

Пауза раньше была только у ключа: глава, упавшая на сетевой ошибке, через
0,1–5 с уходила другому ключу. На журналах одна глава дала 16 сетевых ошибок
подряд на десяти ключах, другая — 294 попытки за шесть часов. Сеть и перегрузка
сервиса — общие для всех ключей, повтор другим ключом их не лечит.
"""

import asyncio
import os
import sqlite3
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from gemini_translator.api import config as api_config
from gemini_translator.core.task_manager import ChapterQueueManager
from gemini_translator.core.worker import UniversalWorker
from gemini_translator.core.worker_helpers.error_analyzer import ErrorType, WorkerAction


class _Bus(QtCore.QObject):
    event_posted = QtCore.pyqtSignal(dict)


class QueueRetryPauseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.main_db_connection = sqlite3.connect(
            api_config.SHARED_DB_URI, uri=True, check_same_thread=False
        )
        cls.app.main_db_connection.row_factory = sqlite3.Row

    def setUp(self):
        self.bus = _Bus()
        self.app.event_bus = self.bus
        self.manager = ChapterQueueManager(event_bus=self.bus)
        self.manager.clear_all_queues()
        self.manager.session_id = "session-1"
        self.manager.set_pending_tasks([("epub", "book.epub", "chapter-1.xhtml")])
        self.task = self.manager.get_next_task("worker-1")
        self.assertIsNotNone(self.task)

    def test_a_paused_task_waits_out_its_pause(self):
        now = time.time()
        with mock.patch("gemini_translator.core.task_manager.time.time", return_value=now):
            self.manager.task_requeued_for_retry("worker-1", self.task, retry_after_seconds=60)
            self.assertIsNone(self.manager.get_next_task("worker-2"))
        with mock.patch("gemini_translator.core.task_manager.time.time", return_value=now + 61):
            again = self.manager.get_next_task("worker-2")
        self.assertIsNotNone(again)
        self.assertEqual(str(again[0]), str(self.task[0]))

    def test_a_task_requeued_without_a_pause_is_available_at_once(self):
        self.manager.task_requeued_for_retry("worker-1", self.task)

        self.assertIsNotNone(self.manager.get_next_task("worker-2"))


class _NetworkError(Exception):
    def __init__(self, delay_seconds=30):
        super().__init__("Сбой сети/SSL (ServerDisconnectedError): Server disconnected")
        self.delay_seconds = delay_seconds


def _worker(earlier_network_failures: int, error_type=ErrorType.NETWORK, delay_seconds=30):
    requeued = []
    task = ("task-1", ("epub", "book.epub", "chapter-1.xhtml"))
    error = _NetworkError(delay_seconds)
    worker = types.SimpleNamespace(
        worker_id="worker-1",
        is_shutting_down=False,
        task_manager=types.SimpleNamespace(
            get_failure_history=lambda info: {
                "errors": {"NETWORK": earlier_network_failures},
                "total_count": earlier_network_failures,
            },
            task_requeued_for_retry=lambda worker_id, info, retry_after_seconds=0: requeued.append(
                retry_after_seconds
            ),
            task_requeued=lambda worker_id, info: requeued.append("plain"),
            _get_task_display_name=lambda payload: "chapter-1.xhtml",
        ),
        error_analyzer=types.SimpleNamespace(
            analyze_and_act=lambda exc, info, history: (
                WorkerAction.RETRY_COUNTABLE,
                error_type,
                exc,
            )
        ),
        emerger=types.SimpleNamespace(
            _mutate_task_for_completion=lambda info, exc, history: info
        ),
        _split_batch_after_content_filter=lambda info, kind: False,
        _post_event=lambda *args, **kwargs: None,
    )

    async def execute(info):
        raise error

    worker._execute_task = execute
    for name in ("_process_single_task_with_retries", "_handle_task_result"):
        setattr(worker, name, types.MethodType(getattr(UniversalWorker, name), worker))
    return worker, task, requeued


class WorkerRetryPauseTests(unittest.TestCase):
    def _pause_after(self, earlier, **kwargs):
        worker, task, requeued = _worker(earlier, **kwargs)
        asyncio.run(worker._process_single_task_with_retries(task))
        return requeued

    def test_the_first_network_failure_pauses_the_task_for_what_the_service_asked(self):
        self.assertEqual(self._pause_after(0), [30])

    def test_earlier_network_failures_do_not_stretch_the_pause(self):
        """Сбой, после которого сервис просит паузу, лимит не тратит, а
        растянутая пауза только держала бы книгу, когда сервис уже ожил."""
        self.assertEqual(self._pause_after(5), [30])

    def test_a_pause_the_service_asks_for_is_kept_as_asked(self):
        self.assertEqual(self._pause_after(0, delay_seconds=60), [60])

    def test_an_absurd_pause_is_cut_to_ten_minutes(self):
        self.assertEqual(self._pause_after(0, delay_seconds=86400), [600])

    def test_a_retry_for_another_reason_is_not_paused(self):
        self.assertEqual(self._pause_after(3, error_type=ErrorType.VALIDATION), [0])


if __name__ == "__main__":
    unittest.main()
