"""RPM-слот ключа занимает только взятая задача, а не пустой опрос очереди.

В последовательном режиме следующая глава недоступна, пока переводится
предыдущая, и опрос очереди почти всегда пуст. Если пустой опрос занимает
слот, к концу главы слот оказывается занят недавним опросом, и воркер ждёт
до целого интервала RPM (12 с при RPM 5) перед следующей главой.
"""

import asyncio
import types
import unittest

from gemini_translator.core.worker import UniversalWorker
from gemini_translator.core.worker_helpers.rpm_limiter import RPMLimiter


class _Queue:
    """Очередь, где задачи есть, но выдаётся только заданная последовательность."""

    def __init__(self, handouts, pending_checks):
        self._handouts = list(handouts)
        self._pending_checks = list(pending_checks)

    def has_pending_tasks(self):
        return self._pending_checks.pop(0) if self._pending_checks else False

    def get_next_task(self, worker_id):
        return self._handouts.pop(0) if self._handouts else None


def _worker(queue):
    worker = types.SimpleNamespace(
        worker_id="worker-1",
        api_key="key-1",
        brigade_size=10,
        is_cancelled=False,
        is_shutting_down=False,
        task_manager=queue,
        rpm_limiter=RPMLimiter(5),
        check_session=lambda: True,
        _post_event=lambda *args, **kwargs: None,
        _wake_event=asyncio.Event(),
    )

    async def process(task_info):
        return None

    worker._process_single_task_with_retries = process
    for name in ("_compute_idle_timeout", "_wait_for_next_cycle", "_async_processing_loop"):
        setattr(worker, name, types.MethodType(getattr(UniversalWorker, name), worker))
    return worker


class WorkerRpmSlotTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_empty_poll_leaves_the_rpm_slot_free(self):
        # Задачи в очереди есть, но ни одна ещё не доступна (цепочка ждёт главу).
        worker = _worker(_Queue(handouts=[None], pending_checks=[True, False]))

        await worker._async_processing_loop()

        self.assertEqual(worker.rpm_limiter.seconds_until_next_allowed(), 0.0)

    async def test_a_taken_task_occupies_the_rpm_slot(self):
        task = ("task-1", ("epub", "book.epub", "chapter-1.xhtml"))
        worker = _worker(_Queue(handouts=[task], pending_checks=[True, False, False]))

        await worker._async_processing_loop()

        self.assertGreater(worker.rpm_limiter.seconds_until_next_allowed(), 0.0)


if __name__ == "__main__":
    unittest.main()
