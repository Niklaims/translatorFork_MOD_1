import logging
import threading
import unittest
from unittest import mock

from gemini_translator.core.worker import UniversalWorker


class _DummyWorker:
    """
    Минимальная боевая замена воркера для UniversalWorker.run — только
    атрибуты/методы, до которых код в run() реально дотягивается, когда
    get_worker_loop() падает сразу (без сети, без реального event loop'а).
    """

    def __init__(self, worker_id="worker-legacy-0001"):
        self.worker_id = worker_id
        self.provider_config = {}
        self.events = []

    def _post_event(self, name, data=None):
        self.events.append((name, data or {}))

    def cancel(self):
        # cancel() в реальном классе делает много всего (отписка от шины и
        # т.д.) — здесь это не нужно, важно лишь что finally его вызывает.
        pass


class AiohttpGlobalLoggersUntouchedByRunTests(unittest.TestCase):
    """
    Регресс на core-a/bugs/3-legacy-worker-global-debug-log.

    run() безусловно включал DEBUG для глобальных логгеров 'aiohttp' и
    'aiohttp_socks' и никогда не возвращал прежний уровень — один запуск
    legacy-воркера (browser/workascii) навсегда включал подробный лог
    aiohttp для всего процесса, включая обычные async-воркеры.

    Рецензент указал, что схема save/restore по каждому воркеру не
    работает для ПЕРЕКРЫВАЮЩИХСЯ legacy-воркеров (а именно так они и
    запускаются — по одному на ключ + до 32 браузерных профилей):
    A.start -> B.start -> A.end -> B.end оставляет глобальный уровень
    DEBUG навсегда, потому что B запоминает уровень, который уже
    выставил A. Поэтому корневая причина устранена по-другому: run()
    вообще больше не трогает уровни этих глобальных логгеров (в
    репозитории ничего не полагается на DEBUG именно для
    aiohttp/aiohttp_socks — см. grep в описании правки). Ниже это
    проверяется явно: и для одиночного запуска, и для двух
    перекрывающихся запусков уровни логгеров не меняются вовсе.
    """

    def setUp(self):
        self.aiohttp_logger = logging.getLogger('aiohttp')
        self.aiohttp_socks_logger = logging.getLogger('aiohttp_socks')
        self._orig_aiohttp_level = self.aiohttp_logger.level
        self._orig_aiohttp_socks_level = self.aiohttp_socks_logger.level
        # Сентинельные уровни, заведомо отличные от DEBUG — чтобы отличить
        # "не тронуто" от "случайно совпало с DEBUG".
        self.aiohttp_logger.setLevel(logging.WARNING)
        self.aiohttp_socks_logger.setLevel(logging.ERROR)

    def tearDown(self):
        self.aiohttp_logger.setLevel(self._orig_aiohttp_level)
        self.aiohttp_socks_logger.setLevel(self._orig_aiohttp_socks_level)

    def test_single_run_does_not_touch_aiohttp_log_levels(self):
        worker = _DummyWorker()

        # get_worker_loop() падает сразу же — run() должен уйти в
        # except/finally без сети и без реального asyncio event loop'а.
        with mock.patch(
            'gemini_translator.core.worker.get_worker_loop',
            side_effect=RuntimeError("boom: нет event loop'а в тесте"),
        ):
            UniversalWorker.run(worker)

        self.assertEqual(
            self.aiohttp_logger.level, logging.WARNING,
            "run() не должен трогать уровень логгера 'aiohttp'",
        )
        self.assertEqual(
            self.aiohttp_socks_logger.level, logging.ERROR,
            "run() не должен трогать уровень логгера 'aiohttp_socks'",
        )

    def test_overlapping_runs_do_not_leave_debug_level_globally(self):
        """
        Регресс именно на находку рецензента (major): два перекрывающихся
        legacy-воркера в порядке A.start -> B.start -> A.end -> B.end не
        должны оставить глобальный уровень логгера в DEBUG (или вообще
        каком-либо изменённом состоянии) после завершения обоих.
        """
        a_started = threading.Event()
        a_may_finish = threading.Event()
        b_started = threading.Event()
        b_may_finish = threading.Event()

        def fake_get_worker_loop():
            # Один общий side_effect на оба потока — mock.patch применяется
            # РОВНО ОДИН раз (снаружи обоих потоков), поэтому его вход/выход
            # не участвует в гонке между потоками. Различаем A/B по
            # нативному id вызывающего потока.
            current = threading.get_native_id()
            if current == a_thread_native_id[0]:
                a_started.set()
                # Дожидаемся, пока тест не разрешит A продолжить — к этому
                # моменту B уже должен был стартовать.
                a_may_finish.wait(timeout=5)
                raise RuntimeError("boom A: нет event loop'а в тесте")
            else:
                b_started.set()
                b_may_finish.wait(timeout=5)
                raise RuntimeError("boom B: нет event loop'а в тесте")

        a_thread_native_id = [None]

        worker_a = _DummyWorker("worker-legacy-A")
        worker_b = _DummyWorker("worker-legacy-B")

        def run_a():
            a_thread_native_id[0] = threading.get_native_id()
            UniversalWorker.run(worker_a)

        def run_b():
            UniversalWorker.run(worker_b)

        thread_a = threading.Thread(target=run_a)
        thread_b = threading.Thread(target=run_b)

        with mock.patch(
            'gemini_translator.core.worker.get_worker_loop',
            side_effect=fake_get_worker_loop,
        ):
            thread_a.start()
            self.assertTrue(a_started.wait(timeout=5), "A должен был стартовать")

            thread_b.start()
            self.assertTrue(b_started.wait(timeout=5), "B должен был стартовать во время работы A")

            # Порядок A.end -> B.end: сначала отпускаем A и дожидаемся его
            # завершения, затем отпускаем B.
            a_may_finish.set()
            thread_a.join(timeout=5)
            self.assertFalse(thread_a.is_alive(), "поток A должен был завершиться")

            b_may_finish.set()
            thread_b.join(timeout=5)
            self.assertFalse(thread_b.is_alive(), "поток B должен был завершиться")

        self.assertEqual(
            self.aiohttp_logger.level, logging.WARNING,
            "после перекрывающихся run() уровень 'aiohttp' должен остаться нетронутым",
        )
        self.assertEqual(
            self.aiohttp_socks_logger.level, logging.ERROR,
            "после перекрывающихся run() уровень 'aiohttp_socks' должен остаться нетронутым",
        )


if __name__ == '__main__':
    unittest.main()
