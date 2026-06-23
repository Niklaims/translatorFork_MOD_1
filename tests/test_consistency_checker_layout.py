import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GT_DISABLE_LOCAL_MODEL_DISCOVERY", "1")

from PyQt6 import QtWidgets

from main import EventBus
from gemini_translator.ui.dialogs.consistency_checker import ConsistencyValidatorPage
from gemini_translator.utils.settings import SettingsManager


class ConsistencyCheckerLayoutTests(unittest.TestCase):
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

    def tearDown(self):
        self.settings.flush()
        try:
            os.unlink(self.settings_file.name)
        except FileNotFoundError:
            pass

    @patch("gemini_translator.ui.widgets.key_management_widget.KeyManagementWidget.minimumSizeHint")
    def test_settings_tab_keeps_key_management_widget_at_usable_width(self, mock_min_size):
        from PyQt6.QtCore import QSize
        mock_min_size.return_value = QSize(800, 600)
        page = ConsistencyValidatorPage(
            [{"name": "Chapter 1", "content": "text", "path": "chapter.xhtml"}],
            self.settings,
        )
        self.addCleanup(page.close)

        page.resize(2500, 1000)
        page.show()
        page.main_tabs.setCurrentIndex(1)
        self.app.processEvents()

        settings_tab = page.main_tabs.widget(1)
        settings_left_tabs = next(
            tab_widget
            for tab_widget in settings_tab.findChildren(QtWidgets.QTabWidget)
            if tab_widget.indexOf(page.key_management_widget) != -1
        )

        self.assertGreaterEqual(
            settings_left_tabs.minimumWidth(),
            page.key_management_widget.minimumSizeHint().width(),
        )


if __name__ == "__main__":
    unittest.main()
