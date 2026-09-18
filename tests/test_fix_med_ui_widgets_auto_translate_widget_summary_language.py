"""
Регресс для находки ui-widgets-a/bugs/1-auto-translate-summary-mixed-l.

_update_translation_profile_summary() сперва строит русский текст лимита пакета
(batch_text), а затем безусловно перезаписывает его английской версией той же
фразы, если batch_tokens > 0 либо унаследован общий лимит задачи. В заметках
при этом добавлялась ещё одна английская строка и бессмысленный мойибэйк-фильтр
"СЃРёРм". Тест проверяет, что после исправления сводка и заметки остаются
полностью на русском языке в обоих сценариях (свой лимит токенов и
унаследованный лимит задачи).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PyQt6 import QtWidgets

from gemini_translator.ui.widgets.auto_translate_widget import AutoTranslateWidget


class _AutoTranslateSettingsManagerStub:
    def load_glossary_prompts(self):
        return {}

    def get_last_glossary_prompt_text(self):
        return ""

    def get_last_auto_translation_settings(self):
        return {}

    def get_last_auto_translation_preset_name(self):
        return None

    def load_auto_translation_presets(self):
        return {}

    def save_auto_translation_presets(self, presets):
        return True

    def save_last_auto_translation_settings(self, settings):
        return None

    def save_last_auto_translation_preset_name(self, name):
        return None


class TranslationProfileSummaryLanguageTests(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.widget = AutoTranslateWidget(settings_manager=_AutoTranslateSettingsManagerStub())

    def tearDown(self):
        self.widget.deleteLater()

    def test_summary_stays_russian_when_batch_token_limit_set(self):
        # Свой лимит токенов пакета > 0 — раньше вторая ветка безусловно
        # перезаписывала русский batch_text английским "Batch limit: ...".
        self.widget.batch_tokens_spin.setValue(5000)
        self.widget._update_translation_profile_summary()

        summary = self.widget.translation_summary_label.text()
        notes = self.widget.translation_summary_note.text()

        self.assertIn("Лимит пакета", summary)
        self.assertNotIn("Batch limit", summary)
        self.assertNotIn("The token limit is used directly", notes)

    def test_summary_stays_russian_when_task_limit_inherited(self):
        # Общий лимит задачи > 0, свой лимит токенов не задан — раньше вторая
        # ветка (elif) тоже перезаписывала текст английской фразой
        # "Batch limit: inherited from common settings ...".
        self.widget.batch_tokens_spin.setValue(0)
        self.widget._current_task_size_limit = 12000
        self.widget._update_translation_profile_summary()

        summary = self.widget.translation_summary_label.text()

        self.assertIn("Лимит пакета: как в общих настройках", summary)
        self.assertNotIn("inherited from common settings", summary)

    def test_no_mojibake_filter_leftover_in_notes(self):
        # Мусорный фильтр "СЃРёРм" никогда ничего не отфильтровывал и не
        # должен встречаться в исходнике/поведении после исправления.
        self.widget.batch_tokens_spin.setValue(1000)
        self.widget._update_translation_profile_summary()
        notes = self.widget.translation_summary_note.text()
        self.assertNotIn("СЃРёРм", notes)


if __name__ == "__main__":
    unittest.main()
