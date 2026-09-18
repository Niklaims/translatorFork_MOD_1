import os
import unittest
import uuid
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication

from gemini_translator.ui.widgets.auto_translate_pipeline_widget import (
    AutoTranslatePipelineWidget,
    StageCardWidget,
    ChapterStatusWidget,
    _chapter_display_name,
)
from gemini_translator.utils.settings import SettingsManager


class AutoTranslateChaptersProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings_manager = MagicMock(spec=SettingsManager)
        self.settings_manager._generic_loader = MagicMock(return_value={})
        self.settings_manager._generic_saver = MagicMock()

    def test_chapter_display_name(self):
        self.assertEqual(_chapter_display_name("OEBPS/Text/chapter_001.xhtml"), "📄 HTML: chapter_001.xhtml")
        self.assertEqual(_chapter_display_name("text/chapter_42.html"), "📄 HTML: chapter_42.html")
        self.assertEqual(_chapter_display_name("OEBPS/cover.xhtml"), "📄 HTML: cover.xhtml")
        self.assertEqual(_chapter_display_name("text/titlepage.xhtml"), "📄 HTML: titlepage.xhtml")

        # With mock parent having chapter_widget
        mock_parent = MagicMock()
        mock_parent.chapter_widget._char_suffix_for_chapters.return_value = " · 1 250 симв."
        self.assertEqual(
            _chapter_display_name("OEBPS/Text/chapter_001.xhtml", parent=mock_parent),
            "📄 HTML: chapter_001.xhtml · 1 250 симв."
        )

    def test_stage_card_chapters_and_status(self):
        card = StageCardWidget("machine_translation", "Машинный перевод")
        self.assertFalse(card.no_chapters_label.isHidden())
        self.assertEqual(card.chapter_count_label.text(), "")

        chapters = ["text/chapter_01.xhtml", "text/chapter_02.xhtml", "text/cover.xhtml"]
        card.set_chapters(chapters)

        self.assertTrue(card.no_chapters_label.isHidden())
        self.assertEqual(card.chapter_count_label.text(), "(3 глав)")
        self.assertEqual(len(card._chapter_widgets), 3)

        # Initial status is waiting
        for ch in chapters:
            self.assertEqual(card._chapter_widgets[ch].status, "waiting")

        # Update status of single chapter
        card.update_chapter_status("text/chapter_01.xhtml", "in_progress")
        self.assertEqual(card._chapter_widgets["text/chapter_01.xhtml"].status, "in_progress")

        card.update_chapter_status("text/chapter_02.xhtml", "success")
        self.assertEqual(card._chapter_widgets["text/chapter_02.xhtml"].status, "success")

        # Test slash normalization
        card.update_chapter_status("text\\cover.xhtml", "success")
        self.assertEqual(card._chapter_widgets["text/cover.xhtml"].status, "success")

        # Test summary update
        card.update_stage_summary()
        self.assertIn("2/3", card.subtitle_label.text())

        # When all success
        card.update_chapter_status("text/chapter_01.xhtml", "success")
        card.update_stage_summary()
        self.assertIn("Завершено (3/3)", card.subtitle_label.text())

        # Clear chapters
        card.clear_chapters()
        self.assertFalse(card.no_chapters_label.isHidden())
        self.assertEqual(card.chapter_count_label.text(), "")
        self.assertEqual(len(card._chapter_widgets), 0)

    def test_auto_translate_widget_update_chapters_and_tasks(self):
        widget = AutoTranslatePipelineWidget(self.settings_manager)
        chapters = ["text/chapter_01.xhtml", "text/chapter_02.xhtml"]
        widget.update_chapters(chapters)

        # All stage cards should have 2 chapters
        for card in widget.stages.values():
            self.assertEqual(len(card._chapter_widgets), 2)
            self.assertEqual(card.chapter_count_label.text(), "(2 глав)")

        # Update task states simulating task_manager.get_ui_state_list()
        task1_id = uuid.uuid4()
        task2_id = uuid.uuid4()
        ui_state_list = [
            ((task1_id, ("epub", "book.epub", "text/chapter_01.xhtml")), "in_progress", {}),
            ((task2_id, ("epub", "book.epub", "text/chapter_02.xhtml")), "success", {}),
        ]
        widget.update_task_states(ui_state_list)

        mt_card = widget.stages["machine_translation"]
        self.assertEqual(mt_card._chapter_widgets["text/chapter_01.xhtml"].status, "in_progress")
        self.assertEqual(mt_card._chapter_widgets["text/chapter_02.xhtml"].status, "success")

    def test_auto_translate_widget_refresh_from_project_manager(self):
        from PyQt6.QtWidgets import QWidget
        parent = QWidget()
        widget = AutoTranslatePipelineWidget(self.settings_manager, parent=parent)
        chapters = ["text/chapter_01.xhtml", "text/chapter_02.xhtml", "text/chapter_03.xhtml"]

        # Mock project_manager on parent
        pm = MagicMock()
        pm.load_glossary_generation_map.return_value = {"text/chapter_01.xhtml"}

        def get_versions(ch):
            if ch == "text/chapter_02.xhtml":
                return {"_translated.html": "rel/path"}
            if ch == "text/chapter_03.xhtml":
                return {"_validated.html": "rel/path"}
            return {}

        pm.get_versions_for_original.side_effect = get_versions
        parent.project_manager = pm
        parent.task_manager = None
        parent.engine = None
        parent.bus = None

        widget.update_chapters(chapters)

        # Verify stages list: synthesis and export removed, untranslated_fixing added after machine_translation
        expected_stages = [
            "glossary_collection",
            "glossary_validation",
            "machine_translation",
            "untranslated_fixing",
            "ai_editing",
        ]
        self.assertEqual(list(widget.stages.keys()), expected_stages)
        self.assertNotIn("synthesis", widget.stages)
        self.assertNotIn("export", widget.stages)

        # Check glossary_collection stage card
        gc_card = widget.stages["glossary_collection"]
        self.assertEqual(gc_card._chapter_widgets["text/chapter_01.xhtml"].status, "success")
        self.assertEqual(gc_card._chapter_widgets["text/chapter_02.xhtml"].status, "waiting")

        # Check machine_translation stage card
        mt_card = widget.stages["machine_translation"]
        self.assertEqual(mt_card._chapter_widgets["text/chapter_02.xhtml"].status, "success")

        # Check untranslated_fixing stage card
        utf_card = widget.stages["untranslated_fixing"]
        self.assertEqual(utf_card._chapter_widgets["text/chapter_01.xhtml"].status, "waiting")
        self.assertEqual(utf_card._chapter_widgets["text/chapter_02.xhtml"].status, "success")
        self.assertEqual(utf_card._chapter_widgets["text/chapter_03.xhtml"].status, "success")

        # Check ai_editing stage card
        ae_card = widget.stages["ai_editing"]
        self.assertEqual(ae_card._chapter_widgets["text/chapter_03.xhtml"].status, "success")

    def test_auto_translate_widget_untranslated_words_detection(self):
        from PyQt6.QtWidgets import QWidget
        parent = QWidget()
        widget = AutoTranslatePipelineWidget(self.settings_manager, parent=parent)
        chapters = ["text/chapter_01.xhtml"]

        pm = MagicMock()
        pm.load_glossary_generation_map.return_value = set()
        pm.get_versions_for_original.return_value = {"_translated.html": "rel/path"}
        pm.load_validation_cache.return_value = {
            "chapters": {
                "text/chapter_01.xhtml": {"untranslated_words": ["sword", "level"]}
            }
        }
        parent.project_manager = pm
        parent.task_manager = None
        parent.engine = None
        parent.bus = None

        widget.update_chapters(chapters)
        utf_card = widget.stages["untranslated_fixing"]
        # Chapter 1 has untranslated words in cache, so status is waiting
        self.assertEqual(utf_card._chapter_widgets["text/chapter_01.xhtml"].status, "waiting")

        # Now simulate cache updated where untranslated words were fixed
        pm.load_validation_cache.return_value = {
            "chapters": {
                "text/chapter_01.xhtml": {"untranslated_words": []}
            }
        }
        widget.refresh_chapter_statuses()
        self.assertEqual(utf_card._chapter_widgets["text/chapter_01.xhtml"].status, "success")

    def test_setup_page_has_sync_auto_translate_chapters_method(self):
        from gemini_translator.ui.dialogs.setup import InitialSetupPage
        self.assertTrue(hasattr(InitialSetupPage, "_sync_auto_translate_chapters"))


if __name__ == "__main__":
    unittest.main()
