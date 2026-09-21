"""Массовая вставка терминов в глоссарий: карточки ввода и подтверждения
замены (glossary_dialogs/paste_terms.py) и весь сценарий во вкладке
«Глоссарий» и в Менеджере глоссариев."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GT_DISABLE_LOCAL_MODEL_DISCOVERY", "1")

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QMessageBox

from main import EventBus
from gemini_translator.ui.widgets.glossary_widget import GlossaryWidget
from gemini_translator.ui.dialogs.glossary import GlossaryManagerPage
from gemini_translator.ui.dialogs.glossary_dialogs import paste_terms
from gemini_translator.ui.dialogs.glossary_dialogs.import_master import ImporterWizardDialog
from gemini_translator.ui.dialogs.glossary_dialogs.paste_terms import (
    PasteConflictsDialog,
    PasteTermsInputDialog,
    wizard_input_for_pasted_text,
)
from gemini_translator.utils.glossary_tools import plan_glossary_paste
from gemini_translator.utils.settings import SettingsManager


GLOSSARY = [
    {"original": "林动", "rus": "Линь Дун", "note": "герой"},
    {"original": "武祖", "rus": "Боевой Предок", "note": ""},
]
# Два расхождения с GLOSSARY и один новый термин; столбцы — через табуляцию,
# как при копировании из электронной таблицы.
PASTE_WITH_CONFLICTS = "林动\tЛин Дун\n武祖\tПредок Войны\n青阳镇\tЦинъян\tгород"


class _PasteSession:
    """Подменяет exec_dialog сценария вставки: «пользователь» вводит текст,
    принимает разбор Мастера импорта и нажимает кнопку карточки подтверждения
    (по умолчанию «Заменить отмеченные»), сняв галочки с ``uncheck``."""

    def __init__(self, text, answer="replace", uncheck=()):
        self.text = text
        self.answer = answer
        self.uncheck = set(uncheck)
        self.shown = []

    def __call__(self, parent, dialog):
        self.shown.append(type(dialog))
        if isinstance(dialog, PasteTermsInputDialog):
            dialog.text_edit.setPlainText(self.text)
            dialog.next_button.click()
        elif isinstance(dialog, ImporterWizardDialog):
            dialog.process_and_accept()
        elif isinstance(dialog, PasteConflictsDialog):
            for row in range(dialog.table.rowCount()):
                item = dialog.table.item(row, 0)
                if item.text() in self.uncheck:
                    item.setCheckState(Qt.CheckState.Unchecked)
            {
                "replace": dialog.replace_button,
                "keep": dialog.keep_button,
                "cancel": dialog.cancel_button,
            }[self.answer].click()
        else:
            raise AssertionError(f"неожиданная карточка {type(dialog).__name__}")
        return dialog.result()


def _triples(entries):
    return [(e["original"], e["rus"], e["note"]) for e in entries]


class _QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class WizardInputTests(_QtTestCase):
    def test_spreadsheet_columns_reach_the_wizard_already_split(self):
        data, from_table = wizard_input_for_pasted_text("A\tБ\tзаметка\n\nC\tД\n")
        wizard = ImporterWizardDialog(initial_data=data, is_from_table=from_table)
        self.addCleanup(wizard.deleteLater)

        wizard.process_and_accept()

        self.assertEqual(
            wizard.get_glossary(),
            [
                {"original": "A", "rus": "Б", "note": "заметка"},
                {"original": "C", "rus": "Д", "note": ""},
            ],
        )

    def test_plain_lines_open_without_the_json_error_box(self):
        data, from_table = wizard_input_for_pasted_text("A = Б\nC = Д")
        with patch.object(QMessageBox, "exec", side_effect=AssertionError("окно ошибки JSON")):
            wizard = ImporterWizardDialog(initial_data=data, is_from_table=from_table)
        self.addCleanup(wizard.deleteLater)

        self.assertEqual(wizard.original_data_as_rows, [["A = Б"], ["C = Д"]])

    def test_program_json_is_recognised_as_is(self):
        data, from_table = wizard_input_for_pasted_text(
            '[{"original": "A", "rus": "Б", "note": "заметка"}]'
        )
        wizard = ImporterWizardDialog(initial_data=data, is_from_table=from_table)
        self.addCleanup(wizard.deleteLater)

        self.assertEqual(
            wizard.get_glossary(),
            [{"original": "A", "rus": "Б", "note": "заметка"}],
        )


class PasteTermsInputDialogTests(_QtTestCase):
    def test_next_is_available_only_with_some_text(self):
        dialog = PasteTermsInputDialog()
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.next_button.isEnabled())

        dialog.text_edit.setPlainText("  \n ")
        self.assertFalse(dialog.next_button.isEnabled())

        dialog.text_edit.setPlainText("A = Б")
        self.assertTrue(dialog.next_button.isEnabled())


class PasteConflictsDialogTests(_QtTestCase):
    def _dialog(self, pasted):
        plan = plan_glossary_paste(GLOSSARY, pasted)
        dialog = PasteConflictsDialog(plan.conflicts)
        self.addCleanup(dialog.deleteLater)
        return plan, dialog

    def test_table_shows_current_and_new_values_and_marks_only_changes(self):
        _, dialog = self._dialog([{"original": "林动", "rus": "Лин Дун", "note": ""}])

        row = [dialog.table.item(0, column) for column in range(5)]
        self.assertEqual(
            [item.text() for item in row],
            ["林动", "Линь Дун", "Лин Дун", "герой", "герой"],
        )
        self.assertTrue(row[2].font().bold())
        self.assertFalse(row[4].font().bold())
        # Фон ячеек тема программы не рисует — новое значение помечено цветом
        # текста, отличным от приглушённого цвета неизменного поля.
        self.assertEqual(row[2].foreground().style(), Qt.BrushStyle.SolidPattern)
        self.assertTrue(row[2].foreground().color().isValid())
        self.assertNotEqual(row[2].foreground().color(), row[4].foreground().color())

    def test_only_checked_rows_are_replaced(self):
        plan, dialog = self._dialog([
            {"original": "林动", "rus": "Лин Дун", "note": ""},
            {"original": "武祖", "rus": "Предок Войны", "note": ""},
        ])

        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        dialog.replace_button.click()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.accepted_conflicts, [plan.conflicts[1]])

    def test_replace_is_unavailable_with_nothing_checked(self):
        _, dialog = self._dialog([{"original": "林动", "rus": "Лин Дун", "note": ""}])

        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(dialog.replace_button.isEnabled())

        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(dialog.replace_button.isEnabled())


class GlossaryWidgetPasteTests(_QtTestCase):
    def setUp(self):
        self.widget = GlossaryWidget()
        self.addCleanup(self.widget.close)
        self.widget.set_glossary([dict(entry) for entry in GLOSSARY])
        info = patch.object(QMessageBox, "information")
        info.start()
        self.addCleanup(info.stop)

    def _paste(self, session):
        with patch.object(paste_terms, "exec_dialog", session):
            self.widget.paste_btn.click()
        return {e["original"]: (e["rus"], e["note"]) for e in self.widget.get_glossary()}

    def test_replaces_checked_terms_and_adds_new_ones(self):
        glossary = self._paste(_PasteSession(PASTE_WITH_CONFLICTS, uncheck={"武祖"}))

        self.assertEqual(
            glossary,
            {
                "林动": ("Лин Дун", "герой"),
                "武祖": ("Боевой Предок", ""),
                "青阳镇": ("Цинъян", "город"),
            },
        )

    def test_keeping_existing_terms_still_adds_new_ones(self):
        glossary = self._paste(_PasteSession(PASTE_WITH_CONFLICTS, answer="keep"))

        self.assertEqual(
            glossary,
            {
                "林动": ("Линь Дун", "герой"),
                "武祖": ("Боевой Предок", ""),
                "青阳镇": ("Цинъян", "город"),
            },
        )

    def test_cancel_on_the_confirmation_changes_nothing(self):
        glossary = self._paste(_PasteSession(PASTE_WITH_CONFLICTS, answer="cancel"))

        self.assertEqual(
            glossary,
            {"林动": ("Линь Дун", "герой"), "武祖": ("Боевой Предок", "")},
        )

    def test_new_terms_alone_skip_the_confirmation(self):
        session = _PasteSession("青阳镇\tЦинъян")

        glossary = self._paste(session)

        self.assertEqual(session.shown, [PasteTermsInputDialog, ImporterWizardDialog])
        self.assertEqual(glossary["青阳镇"], ("Цинъян", ""))

    def test_paste_of_known_terms_does_not_touch_the_glossary(self):
        changes = []
        self.widget.glossary_changed.connect(lambda: changes.append(True))

        self._paste(_PasteSession("林动\tЛинь Дун"))

        self.assertEqual(changes, [])


class GlossaryManagerPasteTests(_QtTestCase):
    def setUp(self):
        self.app.event_bus = EventBus()
        settings_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        settings_file.close()
        self.addCleanup(os.unlink, settings_file.name)
        self.settings = SettingsManager(
            event_bus=self.app.event_bus,
            config_file=settings_file.name,
        )
        self.addCleanup(self.settings.flush)
        self.app.settings_manager = self.settings
        self.app.get_settings_manager = lambda: self.settings
        self.app.global_version = ""
        info = patch.object(QMessageBox, "information")
        info.start()
        self.addCleanup(info.stop)

        self.manager = GlossaryManagerPage(mode="child")
        self.addCleanup(self.manager.close)
        self.manager.set_glossary([dict(entry) for entry in GLOSSARY])

    def test_paste_is_one_step_that_undo_rolls_back(self):
        with patch.object(paste_terms, "exec_dialog", _PasteSession(PASTE_WITH_CONFLICTS)):
            self.manager.paste_terms_button.click()

        self.assertEqual(
            _triples(self.manager.get_glossary()),
            [
                ("林动", "Лин Дун", "герой"),
                ("武祖", "Предок Войны", ""),
                ("青阳镇", "Цинъян", "город"),
            ],
        )

        self.manager.undo_last_action()

        self.assertEqual(_triples(self.manager.get_glossary()), _triples(GLOSSARY))

    def test_paste_into_an_empty_glossary_enables_saving(self):
        manager = GlossaryManagerPage(mode="dialog")
        self.addCleanup(manager.close)
        manager.set_glossary([])
        self.assertFalse(manager.save_button.isEnabled())

        with patch.object(paste_terms, "exec_dialog", _PasteSession("青阳镇\tЦинъян")):
            manager.paste_terms_button.click()

        self.assertEqual(_triples(manager.get_glossary()), [("青阳镇", "Цинъян", "")])
        self.assertTrue(manager.save_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
