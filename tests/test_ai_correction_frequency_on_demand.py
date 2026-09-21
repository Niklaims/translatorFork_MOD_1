"""Частоты терминов в окне AI-коррекции считаются по запросу.

Анализ проходит всю книгу (сотни глав) в потоке, который держит GIL. Пока он
идёт, главный поток ждёт интерпретатор на каждом событии Qt, и окно
открывалось с паузами в секунды — при том что частотный фильтр выключен по
умолчанию и нужен не каждый раз. Теперь окно берёт готовый кэш, а считать
заново начинает, только когда фильтр включили.
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets, sip

# Сначала виджет глоссария — так циклический импорт glossary ↔ widgets
# разрешается так же, как в приложении и остальных тестах.
from gemini_translator.ui.widgets.glossary_widget import GlossaryWidget  # noqa: F401

from gemini_translator.ui.dialogs.glossary_dialogs.ai_correction import CorrectionSessionPage
from gemini_translator.utils.term_frequency_tools import build_term_frequency_payload

_GLOSSARY = [{"original": "Alpha"}, {"original": "Beta"}]

_Owner = type("GlossaryManagerPage", (), {"get_glossary": lambda self: [dict(e) for e in _GLOSSARY]})


class _ProjectManagerStub:
    def __init__(self, payload):
        self.payload = payload

    def load_term_frequency_cache(self):
        return self.payload

    def save_term_frequency_cache(self, payload):
        self.payload = payload


class _FrequencyHarness:
    """Настоящие методы частотного фильтра страницы на лёгких виджетах.

    Методы — атрибуты класса, а виджеты живут под общим родителем, которого
    тест удаляет сам: связанные методы в самом объекте замкнули бы цикл, и
    виджеты удалил бы сборщик мусора — в любой момент, в том числе посреди
    чужой перестилизации приложения (см. test_theme_restyle_gc_safety).
    """

    _initialize_frequency_filter = CorrectionSessionPage._initialize_frequency_filter
    _on_frequency_filter_toggled = CorrectionSessionPage._on_frequency_filter_toggled
    _apply_term_frequency_payload = CorrectionSessionPage._apply_term_frequency_payload
    _update_frequency_status_label = CorrectionSessionPage._update_frequency_status_label
    _get_frequency_allowed_terms = CorrectionSessionPage._get_frequency_allowed_terms

    def __init__(self, epub_path, cached_payload):
        self.owner = _Owner()
        self.project_manager = _ProjectManagerStub(cached_payload)
        self.epub_path = epub_path
        self.root = QtWidgets.QWidget()
        self.cb_frequency_filter = QtWidgets.QCheckBox(self.root)
        self.freq_min_spinbox = QtWidgets.QSpinBox(self.root)
        self.freq_max_spinbox = QtWidgets.QSpinBox(self.root)
        self.frequency_group = QtWidgets.QGroupBox(self.root)
        self.frequency_status_label = QtWidgets.QLabel(self.root)
        self._frequency_worker = None
        self._term_frequency_payload = {}
        self._term_frequency_map = {}
        self.analysis_starts = 0
        self.cb_frequency_filter.stateChanged.connect(self._on_frequency_filter_toggled)

    def _get_glossary_owner(self):
        return self.owner

    def _resolve_frequency_sources(self):
        return self.project_manager, self.epub_path

    def _start_frequency_analysis(self):
        self.analysis_starts += 1

    def update_token_estimation(self):
        pass


class AiCorrectionFrequencyOnDemandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.epub_path = os.path.join(temp_dir.name, "book.epub")
        with open(self.epub_path, "wb") as epub:
            epub.write(b"stub")

    def _harness(self, cached_payload):
        page = _FrequencyHarness(self.epub_path, cached_payload)
        self.addCleanup(sip.delete, page.root)
        return page

    def _fresh_cache(self):
        return build_term_frequency_payload(
            _GLOSSARY,
            self.epub_path,
            {"Alpha": {"count": 3, "files": ["ch1.xhtml"]}, "Beta": {"count": 1, "files": ["ch2.xhtml"]}},
        )

    def test_opening_without_fresh_counts_does_not_scan_the_book(self):
        page = self._harness(cached_payload={})

        page._initialize_frequency_filter()

        self.assertEqual(page.analysis_starts, 0)
        self.assertTrue(page.cb_frequency_filter.isEnabled())
        self.assertFalse(page.cb_frequency_filter.isChecked())

    def test_enabling_the_filter_starts_the_scan_when_counts_are_missing(self):
        page = self._harness(cached_payload={})
        page._initialize_frequency_filter()

        page.cb_frequency_filter.setChecked(True)

        self.assertEqual(page.analysis_starts, 1)

    def test_fresh_cache_is_applied_without_scanning(self):
        page = self._harness(cached_payload=self._fresh_cache())

        page._initialize_frequency_filter()
        page.cb_frequency_filter.setChecked(True)

        self.assertEqual(page.analysis_starts, 0)
        self.assertEqual(set(page._term_frequency_map), {"Alpha", "Beta"})
        self.assertTrue(page.freq_min_spinbox.isEnabled())


if __name__ == "__main__":
    unittest.main()
