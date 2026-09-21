"""«Отменить» в Менеджере глоссариев возвращает терминам прежнюю дату
создания (столбец timestamp).

Раньше отмена правки целиком и отмена удаления строк вставляли строки без
timestamp. После сохранения у терминов в project_glossary.json стоял null,
а при следующей загрузке set_glossary ставил им текущее время: настоящие даты
создания пропадали насовсем."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GT_DISABLE_LOCAL_MODEL_DISCOVERY", "1")

from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QMessageBox

from main import EventBus
from gemini_translator.ui.widgets.glossary_widget import GlossaryWidget  # noqa: F401
from gemini_translator.ui.dialogs.glossary import GlossaryManagerPage
from gemini_translator.utils.glossary_tools import plan_glossary_paste
from gemini_translator.utils.settings import SettingsManager


GLOSSARY = [
    {"original": "林动", "rus": "Линь Дун", "note": "герой", "timestamp": 101.0},
    {"original": "武祖", "rus": "Боевой Предок", "note": "", "timestamp": 202.0},
]
NEW_TERM = {"original": "青阳镇", "rus": "Цинъян", "note": "город"}


def _records(entries):
    return [(e["original"], e["rus"], e["note"], e["timestamp"]) for e in entries]


def _confirm_button(box):
    """clickedButton окна «Подтверждение удаления»: нажата «Да, удалить»."""
    return next(
        button for button in box.buttons()
        if box.buttonRole(button) == QMessageBox.ButtonRole.YesRole
    )


class GlossaryManagerUndoTimestampTests(unittest.TestCase):
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

        self.manager = GlossaryManagerPage(mode="child")
        self.addCleanup(self.manager.close)
        self.manager.set_glossary([dict(entry) for entry in GLOSSARY])

    def tearDown(self):
        self.settings.flush()
        try:
            os.unlink(self.settings_file.name)
        except FileNotFoundError:
            pass

    def test_undo_of_a_whole_glossary_edit_keeps_creation_dates(self):
        # Вставка терминов кладёт в историю весь глоссарий до правки.
        plan = plan_glossary_paste(self.manager.get_glossary(include_db_id=True), [NEW_TERM])
        self.manager._apply_pasted_terms(plan, plan.conflicts)
        self.assertEqual(
            [entry["original"] for entry in self.manager.get_glossary()],
            ["林动", "武祖", "青阳镇"],
        )

        self.manager.undo_last_action()

        self.assertEqual(_records(self.manager.get_glossary()), _records(GLOSSARY))

    def test_undo_of_a_row_deletion_keeps_creation_dates(self):
        self.manager.table.selectRow(1)
        with patch.object(QMessageBox, "exec", return_value=None), \
             patch.object(QMessageBox, "clickedButton", _confirm_button):
            self.manager._remove_selected_terms()
        self.assertEqual(_records(self.manager.get_glossary()), _records(GLOSSARY[:1]))

        self.manager.undo_last_action()

        self.assertEqual(_records(self.manager.get_glossary()), _records(GLOSSARY))


if __name__ == "__main__":
    unittest.main()
