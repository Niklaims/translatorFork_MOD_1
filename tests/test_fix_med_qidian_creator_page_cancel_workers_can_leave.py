# -*- coding: utf-8 -*-
"""Регресс на qidian-tools/bugs/6-rulate-fill-worker-unstoppable.

RulateFillWorker/RulateLoginWorker (qidian_rulate/workers.py) в волне 1 уже
получили cancel()+_wait_until_browser_closed_or_interrupted, но
QidianCreatorPage.can_leave() ими не пользовался: при уходе со страницы с
запущенным Rulate-воркером пользователь просто видел "Подождите" и был
вынужден закрывать видимый Chromium руками, чтобы вообще смочь уйти —
cancel() никогда не вызывался, и QThread/процесс браузера могли до этого
момента жить сколь угодно долго.

Тест гоняет боевые QThread-тела (не моки): воркер с cancel() должен
отменяться и дожидаться завершения при подтверждении выхода, воркер без
cancel() — по-прежнему блокировать уход предупреждением, как раньше.

Ревью после первой волны правки нашло дыру: финальная проверка ходила по
снимку self._workers, снятому в начале can_leave(), а не по живому списку —
во время вложенного QEventLoop страница интерактивна, и новый воркер,
запущенный пользователем в этот момент, не был бы замечен. Отдельный тест
ниже (test_can_leave_final_check_rereads_workers_started_during_wait)
воспроизводит именно это. Заодно исходные тесты не отличали "cancel() и
реальное ожидание остановки" от "cancel() и сразу True" — воркеры теперь
останавливаются заведомо не мгновенно, а тест на happy path проверяет
isRunning() сразу по возврату can_leave(), без собственного предварительного
wait().
"""

import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from gemini_translator.ui.pages.qidian_creator_page import QidianCreatorPage


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _StoppableWorker(QThread):
    """Форма RulateFillWorker/RulateLoginWorker после волны 1: получив
    cancel(), не останавливается мгновенно — run() ещё ``stop_delay`` секунд
    имитирует неотменяемый хвост работы (например, закрытие
    persistent-контекста Chromium). Это отличает "can_leave реально дождался
    остановки" от "can_leave дёрнул cancel() и сразу отпустил управление"."""

    def __init__(self, stop_delay: float = 0.3):
        super().__init__()
        self._cancel_event = threading.Event()
        self._stop_delay = stop_delay

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        self._cancel_event.wait()
        time.sleep(self._stop_delay)


class _UnstoppableWorker(QThread):
    """Форма QidianFetchWorker/CoverPromptWorker и т.п. — cancel() нет,
    can_leave должен по-прежнему их дожидаться (старое поведение)."""

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.wait(0.02):
            pass

    def finish_for_test(self) -> None:
        self._stop.set()


class _CanLeaveHarness:
    """Минимальный харнесс: реальные can_leave/_prepare_for_close и _log,
    без тяжёлого _build_ui(). _prepare_for_close лишь переиспользует
    can_leave(), отдельного хелпера в проде больше нет — совместимость с
    другими харнессами (tests/test_fix_g26_qidian_can_leave.py), которые
    биндят только can_leave."""

    can_leave = QidianCreatorPage.can_leave
    _prepare_for_close = QidianCreatorPage._prepare_for_close
    _log = QidianCreatorPage._log

    def __init__(self, workers):
        self._workers = workers


def _wait_started(worker: QThread) -> None:
    for _ in range(200):
        if worker.isRunning():
            return
        time.sleep(0.01)
    raise AssertionError("worker did not start in time")


class QidianCreatorPageCanLeaveCancelsWorkersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _ensure_app()

    def test_can_leave_cancels_stoppable_worker_and_returns_true_on_confirm(self):
        # stop_delay заметно меньше wait(2000) в проде, но не нулевой —
        # реальная остановка требует времени, и мы проверяем её сразу по
        # возврату can_leave(), без собственного predварительного wait().
        worker = _StoppableWorker(stop_delay=0.3)
        worker.start()
        self.addCleanup(lambda: (worker.cancel(), worker.wait(2000)))
        _wait_started(worker)

        page = _CanLeaveHarness([worker])
        with patch(
            "gemini_translator.ui.pages.qidian_creator_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question:
            result = page.can_leave()

        question.assert_called_once()
        self.assertTrue(result)
        # can_leave обязан реально дождаться остановки, а не просто выставить
        # флаг и уйти дальше: проверяем сразу, без собственного wait() —
        # реализация, которая зовёт cancel() и сразу возвращает True, здесь
        # бы провалилась.
        self.assertFalse(worker.isRunning())
        self.assertFalse(getattr(page, "_awaiting_worker_cancel", False))

    def test_can_leave_waits_through_nested_event_loop_on_slow_stop(self):
        """Самая рискованная ветка: worker.wait(2000) не успевает, can_leave
        обязан провалиться во вложенный QEventLoop и дождаться finished, а
        не вернуть True раньше реальной остановки."""
        worker = _StoppableWorker(stop_delay=2.5)  # > wait(2000) в проде
        worker.start()
        self.addCleanup(lambda: (worker.cancel(), worker.wait(5000)))
        _wait_started(worker)

        page = _CanLeaveHarness([worker])
        with patch(
            "gemini_translator.ui.pages.qidian_creator_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            result = page.can_leave()

        self.assertTrue(result)
        self.assertFalse(worker.isRunning())
        self.assertFalse(getattr(page, "_awaiting_worker_cancel", False))

    def test_can_leave_final_check_rereads_workers_started_during_wait(self):
        """Дыра со снимком: пока крутится вложенный QEventLoop ожидания
        первого воркера, страница остаётся интерактивной — пользователь
        может успеть запустить новый воркер. Финальная проверка обязана
        увидеть его по свежему self._workers, а не по снимку, снятому в
        начале can_leave()."""
        slow_worker = _StoppableWorker(stop_delay=2.5)  # уйдёт во вложенный цикл
        slow_worker.start()
        self.addCleanup(lambda: (slow_worker.cancel(), slow_worker.wait(5000)))
        _wait_started(slow_worker)

        new_worker = _UnstoppableWorker()
        self.addCleanup(lambda: (new_worker.finish_for_test(), new_worker.wait(2000)))

        page = _CanLeaveHarness([slow_worker])

        def _inject_new_worker_mid_wait():
            # Имитирует пользователя, успевшего нажать "Войти в Rulate" (или
            # аналог) прямо во время ожидания остановки первого воркера.
            new_worker.start()
            _wait_started(new_worker)
            page._workers.append(new_worker)

        QTimer.singleShot(300, _inject_new_worker_mid_wait)

        with patch(
            "gemini_translator.ui.pages.qidian_creator_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), patch(
            "gemini_translator.ui.pages.qidian_creator_page.QMessageBox.warning"
        ) as warning:
            result = page.can_leave()

        # Старая реализация со снимком вернула бы True здесь (slow_worker уже
        # остановился, а new_worker в снимок не попал) — именно эта дыра и
        # была найдена ревью.
        self.assertFalse(result)
        warning.assert_called_once()
        self.assertTrue(new_worker.isRunning())
        self.assertFalse(getattr(page, "_awaiting_worker_cancel", False))

    def test_can_leave_does_not_cancel_when_user_declines(self):
        worker = _StoppableWorker(stop_delay=0.3)
        worker.start()
        self.addCleanup(lambda: (worker.cancel(), worker.wait(2000)))
        _wait_started(worker)

        page = _CanLeaveHarness([worker])
        with patch(
            "gemini_translator.ui.pages.qidian_creator_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            result = page.can_leave()

        self.assertFalse(result)
        self.assertTrue(worker.isRunning())

    def test_can_leave_still_blocks_on_non_cancelable_worker(self):
        worker = _UnstoppableWorker()
        worker.start()
        self.addCleanup(lambda: (worker.finish_for_test(), worker.wait(2000)))
        _wait_started(worker)

        page = _CanLeaveHarness([worker])
        with patch(
            "gemini_translator.ui.pages.qidian_creator_page.QMessageBox.warning"
        ) as warning:
            result = page.can_leave()

        self.assertFalse(result)
        warning.assert_called_once()

    def test_prepare_for_close_delegates_to_same_stop_logic(self):
        """MainShell.closeEvent (gemini_translator/ui/shell.py) зовёт
        page._prepare_for_close() по hasattr в обход can_leave() — без этого
        хука закрытие всего приложения с открытым Rulate-браузером уничтожало
        QThread на ходу, не дав ему шанса на cancel()."""
        worker = _StoppableWorker(stop_delay=0.3)
        worker.start()
        self.addCleanup(lambda: (worker.cancel(), worker.wait(2000)))
        _wait_started(worker)

        page = _CanLeaveHarness([worker])
        with patch(
            "gemini_translator.ui.pages.qidian_creator_page.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question:
            result = page._prepare_for_close()

        question.assert_called_once()
        self.assertTrue(result)
        self.assertFalse(worker.isRunning())


if __name__ == "__main__":
    unittest.main()
