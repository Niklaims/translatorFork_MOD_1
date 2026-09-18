"""Регресс для ui-dialogs-validation/runtime/17-qa-dialog-closed-mid-pass-call.

open_translation_quality_dialog раньше создавал TranslationQualityController
как Qt-ребёнка САМОГО ДИАЛОГА (parent=dialog). Проход по книге продолжается
в фоне и после закрытия окна (это норма), но callback QA-потока обращается к
методам контроллера — а тот уже уничтожен вместе с диалогом, и первое же
обращение валится RuntimeError "wrapped C/C++ object has been deleted".

Ревью указало, что первая версия этого теста не воспроизводила дефект: она
дёргала только новый хелпер ``_quality_controller_instance()`` напрямую, а не
дефектный путь ``open_translation_quality_dialog`` — на неисправленном коде
(``TranslationQualityController(..., parent=dialog)``) тест падал бы с
AttributeError («нет такого метода»), а не разоблачал RuntimeError. Тесты
ниже идут именно через ``open_translation_quality_dialog`` (с подменённым
``exec_dialog``, чтобы не крутить модальный цикл), достают РЕАЛЬНО созданный
им контроллер, уничтожают диалог так же, как overlay-хост при закрытии
карточки, и проверяют, что контроллер остаётся живым Qt-объектом.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QDialog

from gemini_translator.ui.dialogs.validation import TranslationValidatorPage
from gemini_translator.qa.settings import QaSettings


class _FakeSettingsManager:
    """Достаточно настроек, чтобы открыть окно «Качество перевода» без проекта."""

    def __init__(self):
        self._qa_settings = QaSettings()
        self.saved = []

    def get_qa_settings(self):
        return self._qa_settings

    def save_qa_settings(self, settings):
        self.saved.append(settings)
        self._qa_settings = settings


def _quiesce_page(page):
    """Гасит отложенную работу, которую конструктор страницы ставит на таймер.

    TranslationValidatorPage.__init__ запускает одноразовый QTimer (150 мс) на
    _populate_initial_table; в тесте страница живёт без реального проекта, и
    таймер сработал бы уже в чужом тесте того же процесса, уронив его
    исключением из Qt-слота (pytest-qt ловит их на любом тесте).
    """
    timer = getattr(page, "_populate_initial_table_timer", None)
    if timer is not None:
        timer.stop()


def _dispose_page(page):
    """deleteLater + доставка DeferredDelete: без этого QObject доживает до
    следующего оборота цикла событий уже в чужом тесте."""
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class QualityControllerOutlivesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.global_version = ""

    def _build_page(self):
        with patch.object(TranslationValidatorPage, "_perform_initial_cjk_scan"):
            page = TranslationValidatorPage(
                "/tmp/nonexistent-translations",
                "/tmp/nonexistent-book.epub",
                project_manager=None,
            )
        _quiesce_page(page)
        self.addCleanup(_dispose_page, page)
        return page

    def _open_dialog_capturing_it(self, page):
        """Вызывает НАСТОЯЩИЙ open_translation_quality_dialog, ловит созданный
        им диалог вместо запуска модального цикла (exec_dialog подменён)."""
        captured = {}

        def _fake_exec_dialog(context, dialog):
            captured["dialog"] = dialog
            return int(QDialog.DialogCode.Accepted)

        with patch.object(
            TranslationValidatorPage,
            "_quality_settings_manager",
            return_value=self._settings_manager,
        ), patch(
            "gemini_translator.ui.dialogs.validation.exec_dialog",
            side_effect=_fake_exec_dialog,
        ):
            page.open_translation_quality_dialog()
        dialog = captured["dialog"]
        self.addCleanup(lambda: None if sip.isdeleted(dialog) else dialog.deleteLater())
        return dialog

    def setUp(self):
        self._settings_manager = _FakeSettingsManager()

    def test_controller_survives_dialog_closed_mid_pass_through_the_real_open_path(self):
        page = self._build_page()

        dialog = self._open_dialog_capturing_it(page)
        controller = page._quality_controller
        self.assertIsNotNone(
            controller, "open_translation_quality_dialog должен был построить контроллер"
        )

        # Overlay-хост закрывает карточку именно так: setParent(None) + deleteLater()
        # (см. overlay_host.py:_dismiss). deleteLater() лишь ПЛАНИРУЕТ удаление
        # C++-объекта на следующий проход цикла событий — в offscreen-тесте
        # без него нет гарантии, что оно правда произойдёт за пару
        # processEvents(), поэтому уничтожаем объект детерминированно тем же
        # способом, каким это в итоге сделал бы Qt.
        dialog.setParent(None)
        sip.delete(dialog)

        self.assertTrue(sip.isdeleted(dialog), "диалог должен быть реально уничтожен")
        self.assertFalse(
            sip.isdeleted(controller),
            "контроллер прохода не должен умирать вместе с закрытым диалогом",
        )

        # Ровно это раньше падало: QA-поток вызывает on_done уже после
        # закрытия окна, и первое же обращение к методам/сигналам
        # контроллера обращалось к удалённому C++ объекту.
        try:
            controller.status_changed.emit("проход продолжается в фоне")
            controller.progress_changed.emit(3, 10, "chapter-3")
            controller.refresh_report()
        except RuntimeError as error:
            self.fail(f"контроллер не должен падать после закрытия диалога: {error}")

    def test_reopening_after_the_dialog_was_closed_reuses_the_same_controller(self):
        """Повторное открытие окна не должно плодить новый Qt-child страницы.

        Если бы контроллер строился заново при каждом открытии, старые уже
        ненужные контроллеры копились бы как дети страницы, и работающий в
        фоне проход отслеживал бы только тот контроллер, что был у ЗАКРЫТОГО
        диалога, а не тот, что видит заново открытое окно.
        """
        page = self._build_page()

        first_dialog = self._open_dialog_capturing_it(page)
        first_controller = page._quality_controller
        first_dialog.setParent(None)
        sip.delete(first_dialog)

        second_dialog = self._open_dialog_capturing_it(page)
        second_controller = page._quality_controller

        self.assertIs(first_controller, second_controller)
        self.assertIs(second_controller.parent(), page)
        self.assertFalse(sip.isdeleted(second_dialog))

    def test_busy_state_survives_reopen_after_the_dialog_was_closed_mid_pass(self):
        """«Остановить» должна быть активна в заново открытом окне.

        До фикса новый TranslationQualityController строился при каждом
        открытии окна и стартовал с busy=False, даже если проход, начатый до
        закрытия прошлого диалога, продолжает идти в фоне — пользователь не
        мог остановить то, что объективно выполняется.
        """
        page = self._build_page()

        dialog = self._open_dialog_capturing_it(page)
        controller = page._quality_controller
        controller.busy_changed.emit(True)
        self.assertTrue(page._quality_pass_running)

        dialog.setParent(None)
        sip.delete(dialog)

        reopened = self._open_dialog_capturing_it(page)

        self.assertTrue(
            reopened._busy,
            "заново открытое окно должно сразу показывать, что проход ещё идёт",
        )


if __name__ == "__main__":
    unittest.main()
