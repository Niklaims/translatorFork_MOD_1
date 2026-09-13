"""
Регресс на дефект ui-dialogs-glossary-a/bugs/4-hard-stop-missing-orchestrator.

_on_hard_stop_clicked проверял активность только по engine.session_id и
игнорировал работающий SequentialTaskProvider. SequentialTaskProvider.start()
выставляет _is_running=True синхронно, а engine.session_id появляется только
через ~100мс (QTimer.singleShot). Если в этом окне пользователь закрывает
диалог (reject() -> force_exit_on_interrupt=True -> _on_hard_stop_clicked()),
условие `self.engine and self.engine.session_id` ложно, и вся ветка экстренной
остановки (включая финализацию принудительного закрытия) не выполняется —
диалог не закрывается.
"""
import unittest
from types import SimpleNamespace

from PyQt6 import QtWidgets
from PyQt6.QtTest import QTest

from gemini_translator.ui.dialogs.glossary_dialogs.ai_generation import (
    GenerationSessionDialog,
    GenerationSessionPage,
    SequentialTaskProvider,
)


class _SignalStub:
    def __init__(self):
        self.emitted = []

    def connect(self, _callback):
        return None

    def emit(self, event):
        self.emitted.append(event)


class _EventBusStub:
    def __init__(self):
        self.event_posted = _SignalStub()
        self._data_store = {}

    def set_data(self, key, value):
        self._data_store[key] = value

    def get_data(self, key, default=None):
        return self._data_store.get(key, default)

    def pop_data(self, key, default=None):
        return self._data_store.pop(key, default)


class _RacingOrchestratorStub:
    """Имитирует SequentialTaskProvider в окне между start() и появлением session_id.

    stop() воспроизводит реальное поведение SequentialTaskProvider.stop() в части,
    важной для теста на минорное замечание рецензента: он снимает
    MANAGED_SESSION_FLAG_KEY с шины, поэтому если хард-стоп ошибочно вызовет
    orchestrator.stop() ещё и в ветке engine_running, диагностика снятия флага
    в этой ветке (bus.pop_data вернёт None) станет мёртвой — именно это и
    проверяет test_hard_stop_skips_orchestrator_stop_when_engine_session_already_active.
    """

    def __init__(self, bus=None):
        self._is_running = True
        self.MANAGED_SESSION_FLAG_KEY = "managed_session_active_test"
        self.stop_calls = 0
        self._bus = bus

    def stop(self):
        self.stop_calls += 1
        if self._bus is not None:
            self._bus.pop_data(self.MANAGED_SESSION_FLAG_KEY, None)


class _HardStopDuringOrchestratorStartHarness:
    """Боевые тела методов диалога на минимальном харнессе (без Qt-диалога целиком)."""

    _emit_to_bus = staticmethod(GenerationSessionDialog._emit_to_bus)
    _build_event = GenerationSessionDialog._build_event
    _on_hard_stop_clicked = GenerationSessionDialog._on_hard_stop_clicked
    _request_immediate_engine_cancel = GenerationSessionPage._request_immediate_engine_cancel
    _post_event_deferred = GenerationSessionDialog._post_event_deferred
    _finish_forced_interrupt_close = GenerationSessionPage._finish_forced_interrupt_close
    reject = GenerationSessionPage.reject
    _post_event = GenerationSessionDialog._post_event

    def __init__(self):
        self.bus = _EventBusStub()
        # Ключевой момент гонки: сессия ещё не стартовала на стороне движка.
        self.engine = SimpleNamespace(session_id=None)
        self.orchestrator = _RacingOrchestratorStub(self.bus)
        self._pipeline_stop_requested = False
        self.force_exit_on_interrupt = False
        self.hard_stop_btn = QtWidgets.QPushButton("❌ Прервать")
        self.soft_stop_btn = QtWidgets.QPushButton("Завершить плавно")
        self.apply_btn = QtWidgets.QPushButton("Применить")
        self.apply_btn.setVisible(False)
        self.ui_active_states = []
        self.saved_settings = 0
        self.cleanup_calls = []
        self.result_ready = _SignalStub()

    def _set_ui_active(self, active):
        self.ui_active_states.append(active)

    def _save_persistent_ui_settings(self):
        self.saved_settings += 1

    def _cleanup(self, keep_recovery_file=False):
        self.cleanup_calls.append(keep_recovery_file)


class HardStopOrchestratorRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_hard_stop_stops_running_orchestrator_even_without_session_id(self):
        harness = _HardStopDuringOrchestratorStartHarness()
        self.addCleanup(harness.soft_stop_btn.deleteLater)
        self.addCleanup(harness.hard_stop_btn.deleteLater)
        self.addCleanup(harness.apply_btn.deleteLater)

        harness._on_hard_stop_clicked()

        self.assertEqual(
            harness.orchestrator.stop_calls, 1,
            "хард-стоп обязан остановить работающий оркестратор, даже если "
            "engine.session_id ещё не выставлен движком",
        )
        self.assertEqual(harness.ui_active_states, [False])

    def test_forced_close_during_orchestrator_start_window_actually_closes_dialog(self):
        """
        Сценарий: reject() видит orchestrator._is_running=True (session_id ещё None),
        выставляет force_exit_on_interrupt=True и зовёт _on_hard_stop_clicked().
        Диалог обязан закрыться (cleanup + result_ready), а не повиснуть.
        """
        harness = _HardStopDuringOrchestratorStartHarness()
        self.addCleanup(harness.soft_stop_btn.deleteLater)
        self.addCleanup(harness.hard_stop_btn.deleteLater)
        self.addCleanup(harness.apply_btn.deleteLater)

        harness.force_exit_on_interrupt = True
        harness._on_hard_stop_clicked()

        self.assertEqual(
            harness.cleanup_calls, [False],
            "принудительное закрытие должно завершиться финализацией "
            "(_cleanup), иначе диалог остаётся открытым",
        )
        self.assertEqual(harness.result_ready.emitted, [False])

    def test_hard_stop_skips_orchestrator_stop_when_engine_session_already_active(self):
        """
        Регресс на minor-замечание рецензента (строка 2639 отчёта): когда
        engine.session_id уже выставлен (обычный, не гоночный путь), хард-стоп
        не должен звать orchestrator.stop() — эта ветка (ниже) сама снимает
        MANAGED_SESSION_FLAG_KEY и логирует это. Если orchestrator.stop()
        снимает флаг первым (как делает настоящий SequentialTaskProvider.stop()),
        диагностическое сообщение о принудительном снятии флага в ветке
        engine_running перестаёт появляться — bus.pop_data() там получает None.
        """
        harness = _HardStopDuringOrchestratorStartHarness()
        self.addCleanup(harness.soft_stop_btn.deleteLater)
        self.addCleanup(harness.hard_stop_btn.deleteLater)
        self.addCleanup(harness.apply_btn.deleteLater)

        # Обычный (не гоночный) путь: сессия движка уже идёт, оркестратор тоже
        # ещё активен (сессия управляемая), а флаг управляемой сессии выставлен.
        harness.engine = SimpleNamespace(session_id="real-session-id")
        harness.bus.set_data(harness.orchestrator.MANAGED_SESSION_FLAG_KEY, True)

        harness._on_hard_stop_clicked()

        self.assertEqual(
            harness.orchestrator.stop_calls, 0,
            "при уже активной сессии движка orchestrator.stop() вызывать не "
            "нужно — эту остановку и её диагностику берёт на себя ветка "
            "engine_running",
        )

        # Доводим отложенный _post_event_deferred (QTimer.singleShot(0, ...))
        # до срабатывания, чтобы увидеть итоговые события на шине.
        QTest.qWait(50)
        flag_removed_messages = [
            event
            for event in harness.bus.event_posted.emitted
            if event.get('event') == 'log_message'
            and 'Глобальный флаг управляемой сессии снят принудительно'
            in event.get('data', {}).get('message', '')
        ]
        self.assertEqual(
            len(flag_removed_messages), 1,
            "диагностическое сообщение о принудительном снятии флага должно "
            "появляться ровно один раз — если orchestrator.stop() снял флаг "
            "раньше, эта ветка молчит",
        )


class _FakeTaskManagerForDeferredStart:
    """Минимальный TaskManager для SequentialTaskProvider: держит и 'пробуждает' задачи."""

    def __init__(self, tasks):
        self._tasks = list(tasks)
        self._held = []

    def has_pending_tasks(self):
        return bool(self._tasks)

    def get_all_pending_tasks(self):
        return list(self._tasks)

    def hold_all_pending_tasks(self):
        self._held = list(self._tasks)
        self._tasks = []

    def has_held_tasks(self):
        return bool(self._held)

    def peek_next_held_task(self):
        return self._held[0] if self._held else None

    def promote_held_task(self, task_id, task_payload):
        self._held = [item for item in self._held if item[0] != task_id]


class DeferredSessionStartCancelledByStopTests(unittest.TestCase):
    """
    Регресс на major-замечание рецензента: правка хард-стопа закрывала диалог,
    но не отменяла уже запланированный QTimer.singleShot(100, ...), который
    отправляет 'start_session_requested' в шину независимо от того, был ли
    вызван stop(). В результате прерванная пользователем генерация всё равно
    стартовала в TranslationEngine ~100мс спустя — уже без диалога и без
    оркестратора (deleteLater разрывает его подписку на шину).

    Тест использует настоящий SequentialTaskProvider (не стаб) с фейковым
    bus и фейковым task_manager, чтобы честно воспроизвести гонку между
    start() -> stop() и срабатыванием отложенного таймера.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_stop_during_start_window_prevents_deferred_start_session_requested(self):
        bus = _EventBusStub()
        task_manager = _FakeTaskManagerForDeferredStart(
            [("task-1", ("glossary_batch_task", {}))]
        )
        engine = SimpleNamespace(session_id=None, task_manager=task_manager)
        provider = SequentialTaskProvider(
            settings_getter=lambda: {"rpm_limit": 10},
            event_bus=bus,
            translate_engine=engine,
        )

        provider.start()
        # Пользователь нажимает хард-стоп в те же ~100мс, до срабатывания таймера
        # (_task_in_flight уже выставлен _run_next_task(), поэтому stop() не
        # финализирует сессию синхронно, а лишь ставит _is_stopping=True —
        # ровно как описано в замечании рецензента).
        provider.stop()

        # Доводим отложенный QTimer.singleShot(100, ...) до срабатывания.
        QTest.qWait(200)

        start_events = [
            event
            for event in bus.event_posted.emitted
            if event.get('event') == 'start_session_requested'
        ]
        self.assertEqual(
            start_events, [],
            "остановленный оркестратор не должен запускать реальную сессию "
            "движка отложенным таймером — иначе прерванная генерация всё равно "
            "стартует через ~100мс уже без диалога и без оркестратора",
        )


if __name__ == "__main__":
    unittest.main()
