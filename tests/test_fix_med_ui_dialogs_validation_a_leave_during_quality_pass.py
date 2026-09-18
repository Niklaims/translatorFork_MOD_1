"""Регресс для замечания major #4 к ui-dialogs-validation/runtime/17
(ui-dialogs-validation/runtime/17-qa-dialog-closed-mid-pass-call).

Контроллер ручной проверки качества переехал на страницу
(TranslationValidatorPage), а не на диалог — но саму страницу ShellNav.pop()
удаляет обычным «Назад» (page.deleteLater()), и can_leave() об этом ничего не
знал: он спрашивал пользователя только про analysis_thread. Если проход
качества ещё идёт, следующий callback из QA-потока обращается к уже
удалённому Qt-объекту и падает тем же RuntimeError, только уровнем выше.

Полноценная защита — try/except вокруг повторного on_done в
core/chapter_qa_coordinator.py (вне зоны правок этой группы). В пределах
validation.py минимум: can_leave() должен спросить пользователя, когда
проход ещё идёт, и по согласию попросить его остановиться, а не молча дать
себя удалить.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QMessageBox

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage


class _FakeQualityController:
    def __init__(self):
        self.cancel_calls = 0

    def cancel(self):
        self.cancel_calls += 1


class _CanLeaveHarness:
    """Минимальный стенд: боевой can_leave, привязанный к простому объекту."""

    can_leave = TranslationValidatorPage.can_leave

    def __init__(self, *, quality_pass_running=False, controller=None):
        self.analysis_thread = None
        self._awaiting_analysis_thread_stop = False
        self._quality_pass_running = quality_pass_running
        self._quality_controller = controller


class CanLeaveDuringQualityPassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_does_not_prompt_when_no_pass_is_running(self):
        harness = _CanLeaveHarness(quality_pass_running=False)
        with patch(
            "gemini_translator.ui.dialogs.validation.QMessageBox.question"
        ) as question:
            result = harness.can_leave()
        question.assert_not_called()
        self.assertTrue(result)

    def test_blocks_leaving_by_default_while_a_pass_is_running(self):
        controller = _FakeQualityController()
        harness = _CanLeaveHarness(quality_pass_running=True, controller=controller)
        with patch(
            "gemini_translator.ui.dialogs.validation.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ) as question:
            result = harness.can_leave()
        question.assert_called_once()
        self.assertFalse(
            result, "по умолчанию (Нет) страницу нельзя отдавать на удаление"
        )
        self.assertEqual(
            controller.cancel_calls, 0, "без согласия пользователя проход не трогаем"
        )

    def test_confirming_asks_the_running_pass_to_stop_and_allows_leaving(self):
        controller = _FakeQualityController()
        harness = _CanLeaveHarness(quality_pass_running=True, controller=controller)
        with patch(
            "gemini_translator.ui.dialogs.validation.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            result = harness.can_leave()
        self.assertTrue(result)
        self.assertEqual(
            controller.cancel_calls,
            1,
            "согласившись уйти, пользователь должен попросить проход остановиться",
        )

    def test_confirming_without_a_controller_still_allows_leaving(self):
        harness = _CanLeaveHarness(quality_pass_running=True, controller=None)
        with patch(
            "gemini_translator.ui.dialogs.validation.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            result = harness.can_leave()
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
