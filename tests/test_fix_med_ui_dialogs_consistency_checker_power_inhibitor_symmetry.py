"""Регресс на находку ui-dialogs-epub-consistency/bugs/6-consistency-power-inhibitor-sk.

Чекбокс «Не блокировать и не усыплять компьютер во время AI-сессии» описан как
действующий во время любой AI-сессии, а не только во время анализа. Но
_activate_power_inhibitor_for_config() вызывался только из run_analysis() —
run_fix() (одиночное исправление) и run_batch_fix() (массовое исправление),
запускающие такие же долгие AI-воркеры (SingleFixWorker/FixWorker), защиту от
сна не включали вовсе. Симметрично не было и release на успешном завершении
этих операций (_finish_single_fix_ui / on_batch_fix_finished).

Тесты бьют по боевым методам ConsistencyValidatorDialog (делегирует на
ConsistencyValidatorPage), привязанным к минимальному харнессу — без реальной
сети и без реального QThread-воркера (SingleFixWorker/FixWorker подменены
лёгким стабом, фиксирующим момент запуска).

Ревью нашло регрессию в первой версии фикса: безусловный release в
_finish_single_fix_ui()/on_batch_fix_finished() снимает защиту от сна даже
тогда, когда параллельно ещё идёт другая долгая AI-сессия (например, анализ
или массовое исправление, пока пользователь успел вручную создать одиночное
исправление по промежуточным результатам). Тесты
*_keeps_power_inhibitor_when_other_session_running ниже харнессы, у которых
_is_thread_running() возвращает True для конкретного другого потока, и
проверяют, что allow_sleep() в этом случае НЕ вызывается."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from gemini_translator.ui.dialogs.consistency_checker import ConsistencyValidatorDialog
from gemini_translator.utils.power_inhibitor import PREVENT_SLEEP_SETTING_KEY


class _ButtonStub:
    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self.text = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setText(self, value):
        self.text = value


class _ProgressBarStub:
    def __init__(self):
        self.visible = False
        self.range = (0, 1)

    def setVisible(self, value):
        self.visible = bool(value)

    def setRange(self, lo, hi):
        self.range = (lo, hi)

    def setMaximum(self, value):
        pass

    def setValue(self, value):
        pass


class _CheckItemStub:
    def checkState(self):
        return Qt.CheckState.Checked


class _ProblemsTableStub:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)

    def item(self, row, col):
        return _CheckItemStub()


class _PowerInhibitorSpy:
    """Фиксирует порядок и число вызовов prevent_sleep()/allow_sleep()."""

    def __init__(self):
        self.calls = []
        self.last_error = None

    def prevent_sleep(self):
        self.calls.append("prevent_sleep")
        return True

    def allow_sleep(self):
        self.calls.append("allow_sleep")


class _FakeSingleFixWorker:
    """Стаб SingleFixWorker: фиксирует момент start() без реального QThread."""

    instances = []

    def __init__(self, engine, chapter_content, problem, config, active_keys, chapter_meta, trace_file=None):
        self.config = config
        self.started = False
        self.result_ready = SimpleNamespace(connect=lambda *a, **k: None)
        self.error = SimpleNamespace(connect=lambda *a, **k: None)
        _FakeSingleFixWorker.instances.append(self)

    def start(self):
        self.started = True


class _FakeFixWorker:
    """Стаб FixWorker: фиксирует момент start() без реального QThread."""

    instances = []

    def __init__(self, engine, chapters, config, active_keys):
        self.config = config
        self.started = False
        self.results = {}
        self.finished = SimpleNamespace(connect=lambda *a, **k: None)
        self.error = SimpleNamespace(connect=lambda *a, **k: None)
        _FakeFixWorker.instances.append(self)

    def start(self):
        self.started = True


class _RunFixHarness:
    """Минимальный харнесс с боевыми методами ConsistencyValidatorDialog."""

    run_fix = ConsistencyValidatorDialog.run_fix
    _activate_power_inhibitor_for_config = ConsistencyValidatorDialog._activate_power_inhibitor_for_config
    _release_power_inhibitor = ConsistencyValidatorDialog._release_power_inhibitor
    _finish_single_fix_ui = ConsistencyValidatorDialog._finish_single_fix_ui

    def _update_batch_fix_button_state(self):
        pass

    def __init__(self, *, prevent_sleep_enabled=True, running_threads=()):
        self.power_inhibitor = _PowerInhibitorSpy()
        self.current_problem = {"id": "p1", "quote": "текст"}
        self.current_chapter = {"path": "ch1.xhtml", "name": "Глава 1", "content": "тело главы"}
        self.engine = SimpleNamespace()
        self.single_fix_thread = None
        self.single_fix_trace_file = None
        self._single_fix_in_progress = False
        self.fix_btn = _ButtonStub()
        self.manual_fix_btn = _ButtonStub()
        self.apply_btn = _ButtonStub()
        self.skip_btn = _ButtonStub()
        self.problems_table = _ProblemsTableStub()
        self.batch_fix_btn = _ButtonStub()
        self.start_btn = _ButtonStub()
        self.progress_bar = _ProgressBarStub()
        self.logs = []
        self._prevent_sleep_enabled = prevent_sleep_enabled
        # Имена потоков ('analysis_thread', 'fix_thread', ...), для которых
        # _is_thread_running() должен вернуть True — эмулирует параллельно
        # идущую другую долгую AI-сессию.
        self._running_threads = set(running_threads)

    def _log(self, message):
        self.logs.append(message)

    def _is_thread_running(self, attr):
        return attr in self._running_threads

    def _can_start_ai_session(self):
        return True

    def _get_active_keys(self):
        return ["key-1"]

    def _get_current_config(self):
        return {PREVENT_SLEEP_SETTING_KEY: self._prevent_sleep_enabled}

    def _delete_thread_later(self, worker):
        pass


class _RunBatchFixHarness:
    """Минимальный харнесс для run_batch_fix()/on_batch_fix_finished()."""

    run_batch_fix = ConsistencyValidatorDialog.run_batch_fix
    _activate_power_inhibitor_for_config = ConsistencyValidatorDialog._activate_power_inhibitor_for_config
    _release_power_inhibitor = ConsistencyValidatorDialog._release_power_inhibitor
    on_batch_fix_finished = ConsistencyValidatorDialog.on_batch_fix_finished
    _restore_batch_fix_problem_map = ConsistencyValidatorDialog._restore_batch_fix_problem_map
    _on_batch_fix_error = ConsistencyValidatorDialog._on_batch_fix_error
    on_error = ConsistencyValidatorDialog.on_error

    def _update_batch_fix_button_state(self):
        pass

    def __init__(self, *, prevent_sleep_enabled=True, running_threads=(), single_fix_in_progress=False):
        self.power_inhibitor = _PowerInhibitorSpy()
        self.chapters = [{"path": "ch1.xhtml", "name": "Глава 1", "content": "тело"}]
        self.engine = SimpleNamespace(chapter_problems_map={})
        self.fix_thread = None
        self.single_fix_thread = None
        self._single_fix_in_progress = single_fix_in_progress
        self.problems_table = _ProblemsTableStub()
        self.batch_fix_btn = _ButtonStub()
        self.start_btn = _ButtonStub()
        self.progress_bar = _ProgressBarStub()
        self.save_all_btn = _ButtonStub()
        self.pending_fixes = {}
        self.logs = []
        self._batch_fix_original_problems_map = None
        self._prevent_sleep_enabled = prevent_sleep_enabled
        # Имена потоков, для которых _is_thread_running() должен вернуть True —
        # эмулирует параллельно идущую другую долгую AI-сессию.
        self._running_threads = set(running_threads)

    def _log(self, message):
        self.logs.append(message)

    def _is_thread_running(self, attr):
        return attr in self._running_threads

    def _iter_visible_problem_rows(self):
        return [0]

    def _problem_for_row(self, row):
        return {"chapter": "Глава 1", "id": "p1"}

    def _is_problem_resolved(self, problem):
        return False

    def _can_start_ai_session(self):
        return True

    def _get_active_keys(self):
        return ["key-1"]

    def _get_current_config(self):
        return {PREVENT_SLEEP_SETTING_KEY: self._prevent_sleep_enabled}

    def _store_pending_fix(self, path, new_content):
        self.pending_fixes[path] = new_content


class ConsistencyPowerInhibitorSymmetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_run_fix_activates_power_inhibitor_before_starting_worker(self):
        harness = _RunFixHarness(prevent_sleep_enabled=True)
        _FakeSingleFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.SingleFixWorker",
            _FakeSingleFixWorker,
        ):
            harness.run_fix()

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep"],
            "run_fix() должен включать защиту от сна перед запуском SingleFixWorker, "
            "как это уже делает run_analysis()",
        )
        self.assertTrue(_FakeSingleFixWorker.instances[-1].started)

    def test_finish_single_fix_ui_releases_power_inhibitor(self):
        harness = _RunFixHarness(prevent_sleep_enabled=True)
        _FakeSingleFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.SingleFixWorker",
            _FakeSingleFixWorker,
        ):
            harness.run_fix()

        harness._finish_single_fix_ui()

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep", "allow_sleep"],
            "После завершения одиночного исправления защита от сна должна сниматься "
            "симметрично активации",
        )

    def test_run_batch_fix_activates_power_inhibitor_before_starting_worker(self):
        harness = _RunBatchFixHarness(prevent_sleep_enabled=True)
        _FakeFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.FixWorker",
            _FakeFixWorker,
        ), patch(
            "gemini_translator.ui.dialogs.consistency_checker.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            harness.run_batch_fix()

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep"],
            "run_batch_fix() должен включать защиту от сна перед запуском FixWorker, "
            "как это уже делает run_analysis()",
        )
        self.assertTrue(_FakeFixWorker.instances[-1].started)

    def test_on_batch_fix_finished_releases_power_inhibitor(self):
        harness = _RunBatchFixHarness(prevent_sleep_enabled=True)
        _FakeFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.FixWorker",
            _FakeFixWorker,
        ), patch(
            "gemini_translator.ui.dialogs.consistency_checker.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            harness.run_batch_fix()

        harness.on_batch_fix_finished({"ch1.xhtml": "исправленный текст"})

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep", "allow_sleep"],
            "После успешного завершения массового исправления защита от сна должна "
            "сниматься симметрично активации",
        )

    def test_finish_single_fix_ui_keeps_power_inhibitor_when_analysis_still_running(self):
        # Регресс на замечание ревью: пользователь мог кликнуть по проблеме из
        # промежуточных результатов и запустить одиночное исправление, пока
        # анализ (analysis_thread) ещё выполняется. Завершение одиночного
        # исправления не должно гасить защиту от сна, включённую анализом.
        harness = _RunFixHarness(prevent_sleep_enabled=True, running_threads=("analysis_thread",))
        _FakeSingleFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.SingleFixWorker",
            _FakeSingleFixWorker,
        ):
            harness.run_fix()

        harness._finish_single_fix_ui()

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep"],
            "Пока идёт анализ (analysis_thread), завершение одиночного исправления "
            "не должно вызывать allow_sleep()",
        )

    def test_finish_single_fix_ui_keeps_power_inhibitor_when_batch_fix_still_running(self):
        # Тот же сценарий, но параллельная долгая сессия — массовое исправление
        # (fix_thread), а не анализ.
        harness = _RunFixHarness(prevent_sleep_enabled=True, running_threads=("fix_thread",))
        _FakeSingleFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.SingleFixWorker",
            _FakeSingleFixWorker,
        ):
            harness.run_fix()

        harness._finish_single_fix_ui()

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep"],
            "Пока идёт массовое исправление (fix_thread), завершение одиночного "
            "исправления не должно вызывать allow_sleep()",
        )

    def test_on_batch_fix_finished_keeps_power_inhibitor_when_analysis_still_running(self):
        # Аналогичный регресс: массовое исправление завершилось, пока анализ
        # ещё выполняется в фоне.
        harness = _RunBatchFixHarness(prevent_sleep_enabled=True, running_threads=("analysis_thread",))
        _FakeFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.FixWorker",
            _FakeFixWorker,
        ), patch(
            "gemini_translator.ui.dialogs.consistency_checker.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            harness.run_batch_fix()

        harness.on_batch_fix_finished({"ch1.xhtml": "исправленный текст"})

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep"],
            "Пока идёт анализ (analysis_thread), завершение массового исправления "
            "не должно вызывать allow_sleep()",
        )

    def test_on_batch_fix_finished_keeps_power_inhibitor_when_single_fix_in_progress(self):
        # Параллельная долгая сессия — одиночное исправление, ещё не дошедшее
        # до _finish_single_fix_ui() (single_fix_in_progress=True).
        harness = _RunBatchFixHarness(prevent_sleep_enabled=True, single_fix_in_progress=True)
        _FakeFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.FixWorker",
            _FakeFixWorker,
        ), patch(
            "gemini_translator.ui.dialogs.consistency_checker.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            harness.run_batch_fix()

        harness.on_batch_fix_finished({"ch1.xhtml": "исправленный текст"})

        self.assertEqual(
            harness.power_inhibitor.calls,
            ["prevent_sleep"],
            "Пока идёт одиночное исправление (_single_fix_in_progress), завершение "
            "массового исправления не должно вызывать allow_sleep()",
        )

    def test_run_fix_activates_power_inhibitor_immediately_before_worker_start(self):
        # Минорное замечание ревью: активация должна стоять сразу перед
        # worker.start(), чтобы между ней и стартом не было операций, способных
        # бросить исключение (иначе run_fix() без try/except не освободит
        # инхибитор при ошибке). Проверяем порядок: конструирование воркера ->
        # prevent_sleep() -> start().
        harness = _RunFixHarness(prevent_sleep_enabled=True)
        order = []

        class _OrderTrackingWorker(_FakeSingleFixWorker):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                order.append("construct")

            def start(self):
                order.append("start")
                super().start()

        real_prevent_sleep = harness.power_inhibitor.prevent_sleep

        def _tracking_prevent_sleep():
            order.append("prevent_sleep")
            return real_prevent_sleep()

        harness.power_inhibitor.prevent_sleep = _tracking_prevent_sleep

        _FakeSingleFixWorker.instances.clear()
        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.SingleFixWorker",
            _OrderTrackingWorker,
        ):
            harness.run_fix()

        self.assertEqual(order, ["construct", "prevent_sleep", "start"])

    def test_run_fix_does_not_touch_power_inhibitor_when_setting_disabled(self):
        # Чекбокс выключен — активация не должна происходить (уже так работает
        # _activate_power_inhibitor_for_config, проверяем, что фикс это не ломает).
        harness = _RunFixHarness(prevent_sleep_enabled=False)
        _FakeSingleFixWorker.instances.clear()

        with patch(
            "gemini_translator.ui.dialogs.consistency_checker.SingleFixWorker",
            _FakeSingleFixWorker,
        ):
            harness.run_fix()

        self.assertEqual(harness.power_inhibitor.calls, [])


if __name__ == "__main__":
    unittest.main()
