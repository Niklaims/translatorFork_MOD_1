"""«Отменить» в Менеджере глоссариев после правок, которые заменяют глоссарий
целиком: импорт файлов, Мастер импорта по текущим данным, массовая генерация
примечаний и групповая правка.

Такая правка — один шаг истории. Раньше она писала запись и сразу звала
set_glossary, а тот стирал историю и добавлял «Начальную загрузку» с пустым
old_state: первое «Отменить» ничего не меняло, второе очищало глоссарий."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GT_DISABLE_LOCAL_MODEL_DISCOVERY", "1")

from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QDialog, QMessageBox

from main import EventBus
from gemini_translator.ui.widgets.glossary_widget import GlossaryWidget  # noqa: F401
from gemini_translator.ui.dialogs import glossary as glossary_module
from gemini_translator.ui.dialogs.glossary import GlossaryManagerPage
from gemini_translator.ui.dialogs.glossary_dialogs.group_analyzer import GroupAnalysisPage
from gemini_translator.utils.settings import SettingsManager


GLOSSARY = [
    {"original": "林动", "rus": "Линь Дун", "note": "герой"},
    {"original": "武祖", "rus": "Боевой Предок", "note": ""},
]
NEW_TERM = {"original": "青阳镇", "rus": "Цинъян", "note": "город"}


def _triples(entries):
    return [(e["original"], e["rus"], e["note"]) for e in entries]


class GlossaryManagerWholesaleUndoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.app.event_bus = EventBus()
        self.settings_file = tempfile.NamedTemporaryFile(
            suffix=".json",
            delete=False,
        )
        self.settings_file.close()
        self.settings = SettingsManager(
            event_bus=self.app.event_bus,
            config_file=self.settings_file.name,
        )
        self.app.settings_manager = self.settings
        self.app.get_settings_manager = lambda: self.settings
        self.app.global_version = ""
        info = patch.object(QMessageBox, "information")
        info.start()
        self.addCleanup(info.stop)
        # Окно ошибки модальное и повесило бы прогон: пусть лучше роняет тест.
        critical = patch.object(QMessageBox, "critical", side_effect=AssertionError("окно ошибки"))
        critical.start()
        self.addCleanup(critical.stop)

    def tearDown(self):
        self.settings.flush()
        try:
            os.unlink(self.settings_file.name)
        except FileNotFoundError:
            pass

    def _manager(self):
        manager = GlossaryManagerPage(mode="child")
        self.addCleanup(manager.close)
        manager.set_glossary([dict(entry) for entry in GLOSSARY])
        return manager

    @staticmethod
    def _history_rows(manager):
        table = manager.history_table
        return [table.item(row, 0).text() for row in range(table.rowCount())]

    def _import(self, manager, entries, mode):
        manager._process_imported_data(entries, 1, mode)
        # Сама работа идёт в QTimer.singleShot(0) и в конце закрывает окно ожидания.
        for _ in range(100):
            if manager.wait_dialog is None:
                return
            self.app.processEvents()
        self.fail(f"импорт в режиме {mode!r} не завершился")

    def _assert_one_undo_rolls_back(self, manager, action_name, rows_before):
        """Правка изменила глоссарий и легла в историю одной строкой поверх
        прежних, а одно «Отменить» возвращает глоссарий к GLOSSARY."""
        self.assertNotEqual(_triples(manager.get_glossary()), _triples(GLOSSARY))
        rows_after_step = self._history_rows(manager)

        manager.undo_last_action()

        self.assertEqual(_triples(manager.get_glossary()), _triples(GLOSSARY))
        self.assertEqual(rows_after_step, [action_name, *rows_before])

    def test_each_import_mode_is_one_step_that_undo_rolls_back(self):
        action_names = {
            "replace": "Импорт (Замена)",
            "merge": "Импорт (Слияние)",
            "accumulate": "Импорт (Накопление)",
            "supplement": "Импорт (Дополнение)",
        }
        for mode, action_name in action_names.items():
            with self.subTest(mode=mode):
                manager = self._manager()
                rows_before = self._history_rows(manager)

                self._import(manager, [dict(NEW_TERM)], mode)

                self._assert_one_undo_rolls_back(manager, action_name, rows_before)

    def test_import_keeps_earlier_steps_undoable(self):
        manager = self._manager()
        self._import(manager, [dict(NEW_TERM)], "merge")
        self._import(manager, [{"original": "天", "rus": "Небо", "note": ""}], "supplement")

        manager.undo_last_action()
        manager.undo_last_action()

        self.assertEqual(_triples(manager.get_glossary()), _triples(GLOSSARY))

    def test_import_wizard_rebuild_is_one_step_that_undo_rolls_back(self):
        manager = self._manager()
        rows_before = self._history_rows(manager)
        rebuilt = [dict(GLOSSARY[0]), dict(NEW_TERM)]

        class _Wizard:
            """Мастер импорта, в котором пользователь пересобрал данные в rebuilt."""

            def __init__(self, *args, **kwargs):
                pass

            def get_glossary(self):
                return [dict(entry) for entry in rebuilt]

        with patch.object(glossary_module, "ImporterWizardDialog", _Wizard), patch.object(
            glossary_module, "exec_dialog", return_value=QDialog.DialogCode.Accepted
        ):
            manager.run_importer_on_current_data()

        self._assert_one_undo_rolls_back(manager, "Мастер импорта", rows_before)

    def test_bulk_note_generation_is_one_step_that_undo_rolls_back(self):
        manager = self._manager()
        rows_before = self._history_rows(manager)
        # Итог фоновой _do_generate_notes_work: примечание появилось у 武祖.
        manager.new_state_from_work = [dict(GLOSSARY[0]), {**GLOSSARY[1], "note": "сущ., м. р."}]
        manager.changed_terms_from_work = {"武祖"}

        manager._finish_generating_notes()

        self._assert_one_undo_rolls_back(manager, "Массовая генерация", rows_before)

    def test_group_edit_is_one_step_that_undo_rolls_back(self):
        manager = self._manager()
        page = GroupAnalysisPage(manager.get_glossary(), parent=manager)
        self.addCleanup(page.close)
        rows_before = self._history_rows(manager)

        # Первая строка вернулась из дочернего редактора с другим переводом.
        page._apply_changes_to_parent([{"original": "林动", "rus": "Лин Дун", "note": "герой"}], [0])

        self._assert_one_undo_rolls_back(manager, "Групповая правка", rows_before)

    def test_undo_brings_back_the_analysis_of_the_glossary_before_the_step(self):
        manager = self._manager()
        conflicts = manager.direct_conflict_button
        self.assertFalse(conflicts.isVisibleTo(manager))
        # Второй перевод для 林动 — прямой конфликт в новом глоссарии.
        self._import(manager, [{"original": "林动", "rus": "Лин Дун", "note": ""}], "accumulate")
        self.assertTrue(conflicts.isVisibleTo(manager))

        manager.undo_last_action()

        self.assertFalse(conflicts.isVisibleTo(manager))

    def test_loading_a_glossary_starts_the_history_anew(self):
        # Первичная загрузка (глоссарий проекта, открытие менеджера со вкладки)
        # идёт через set_glossary: прежние шаги к новому глоссарию не относятся.
        manager = self._manager()
        self._import(manager, [dict(NEW_TERM)], "merge")

        manager.set_glossary([dict(entry) for entry in GLOSSARY])

        self.assertEqual(self._history_rows(manager), self._history_rows(self._manager()))


if __name__ == "__main__":
    unittest.main()
