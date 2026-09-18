import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.ui.widgets.chapter_list_widget import ChapterListWidget


class MojibakeLabelsTests(unittest.TestCase):
    """Проверяет, что подписи задач-чанков и статуса 'held' не содержат
    повреждённых (mojibake) символов вместо эмодзи.

    Регрессия: копипаст/перекодировка подменила эмодзи на посторонние
    буквы из корейского и телугу алфавитов, которые визуально в редакторе
    выглядят как "странный значок", но при рендере в таблице задач
    показывают пользователю случайные иероглифы.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_widget(self):
        w = ChapterListWidget()
        self.addCleanup(w.close)
        return w

    def test_chunk_task_label_has_no_stray_korean_syllable(self):
        widget = self._make_widget()
        # payload: (task_type, epub_path, chapter_path, title, chunk_index, total_chunks)
        payload = ("epub_chunk", "/tmp/book.epub", "/tmp/chapter.html", None, 0, 3)

        display_text, _tooltip = widget._get_display_texts(payload)

        self.assertNotIn("쪼", display_text, "в подписи чанка не должно быть корейского слога U+CABC")
        self.assertIn("ЧАНК", display_text)

    def test_held_status_label_has_no_stray_telugu_syllables(self):
        widget = self._make_widget()

        status_text, _color = widget._get_status_display_info("held", {}, None)

        for codepoint in ("స", "్", "త"):
            self.assertNotIn(codepoint, status_text, "в подписи статуса 'held' не должно быть символов телугу")
        self.assertIn("Заморожено", status_text)


if __name__ == "__main__":
    unittest.main()
