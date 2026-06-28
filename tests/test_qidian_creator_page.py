import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: F401  (ensures a QApplication-capable env import)

from gemini_translator.ui.pages.qidian_creator_page import QIDIAN_CREATOR_UI_STATE_KEY, QidianCreatorPage
from gemini_translator.ui.dialogs.qidian_rulate_creator import _split_csv
from gemini_translator.ui.shell import ShellPage


class _TextField:
    def __init__(self):
        self.value = None

    def setText(self, value):
        self.value = value

    def setPlainText(self, value):
        self.value = value


class _ComboField:
    def __init__(self):
        self.data = ["first_suggestion", ""]
        self.find_calls = []
        self.index = None
        self.current_index = 0

    def findData(self, value):
        self.find_calls.append(value)
        try:
            return self.data.index(value)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.index = index
        self.current_index = index

    def currentData(self):
        return self.data[self.current_index]


class _SettingsManagerStub:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.saved_ui_state = None

    def load_settings(self):
        return dict(self.settings)

    def save_ui_state(self, payload):
        self.saved_ui_state = payload
        self.settings.update(payload)
        return True


class _ApplyPreparedMetadataHarness:
    _apply_prepared_metadata = QidianCreatorPage._apply_prepared_metadata

    def __init__(self):
        self.english_title_edit = _TextField()
        self.translated_title_edit = _TextField()
        self.translated_description_edit = _TextField()
        self.genres_edit = _TextField()
        self.tags_edit = _TextField()
        self.translator_team_combo = _ComboField()
        self.cover_prompt_edit = _TextField()
        self.action_state_updated = False

    def _update_action_state(self):
        self.action_state_updated = True


class _UiStateHarness:
    _load_ui_state = QidianCreatorPage._load_ui_state
    _save_ui_state = QidianCreatorPage._save_ui_state

    def __init__(self, settings=None):
        self.settings_manager = _SettingsManagerStub(settings)
        self.translator_team_combo = _ComboField()


class QidianCreatorPageContractTests(unittest.TestCase):
    def test_is_shell_page_subclass(self):
        self.assertTrue(issubclass(QidianCreatorPage, ShellPage))

    def test_page_title(self):
        self.assertEqual(QidianCreatorPage.page_title, "Qidian/Fanqie → Rulate")

    def test_split_csv_dedupes_and_strips(self):
        self.assertEqual(_split_csv("a, b ,a\nc"), ["a", "b", "c"])
        self.assertEqual(_split_csv(""), [])

    def test_log_is_in_dedicated_tab(self):
        page_source = Path("gemini_translator/ui/pages/qidian_creator_page.py").read_text(encoding="utf-8")

        self.assertIn("self.main_tabs = QTabWidget()", page_source)
        self.assertIn('self.main_tabs.addTab(main_tab, "Основное")', page_source)
        self.assertIn('self.main_tabs.addTab(log_tab, "Лог")', page_source)
        self.assertNotIn("root.addWidget(log_group)", page_source)

    def test_apply_prepared_metadata_accepts_legacy_metadata_without_translator_team_mode(self):
        page = _ApplyPreparedMetadataHarness()
        prepared = SimpleNamespace(
            english_title="Otherworldly Inn",
            translated_title="Inn",
            translated_description="Description",
            genres=["fantasy", "adventure"],
            tags=["tag-one", "tag-two"],
            cover_prompt="",
        )

        page._apply_prepared_metadata(prepared)

        self.assertEqual(page.english_title_edit.value, "Otherworldly Inn")
        self.assertEqual(page.genres_edit.value, "fantasy, adventure")
        self.assertEqual(page.translator_team_combo.find_calls, [])
        self.assertTrue(page.action_state_updated)

    def test_load_ui_state_restores_translator_team_mode(self):
        page = _UiStateHarness(
            {
                QIDIAN_CREATOR_UI_STATE_KEY: {
                    "translator_team_mode": "",
                }
            }
        )

        page._load_ui_state()

        self.assertEqual(page.translator_team_combo.currentData(), "")

    def test_save_ui_state_persists_translator_team_mode(self):
        page = _UiStateHarness()
        page.translator_team_combo.setCurrentIndex(1)

        page._save_ui_state()

        self.assertEqual(
            page.settings_manager.saved_ui_state,
            {
                QIDIAN_CREATOR_UI_STATE_KEY: {
                    "translator_team_mode": "",
                }
            },
        )
