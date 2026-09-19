import tempfile
import unittest
import zipfile
import os
import posixpath
import types
from pathlib import Path


from gemini_translator.utils.language_tools import GlossaryRegexService
from gemini_translator.utils.term_frequency_tools import (
    GlossaryFrequencyWorker,
    calculate_term_frequency_payload,
    get_epub_signature,
)


def _path_module_without_normcase():
    """Модуль путей без normcase — как HybridPath из os_patch поверх mem://.

    Раньше роль такого модуля играл fs.path (PyFilesystem2); пакет fs из
    рантайма убран, а свойство «нет normcase» воспроизводится напрямую."""
    module = types.ModuleType("path_without_normcase")
    for name in dir(posixpath):
        if name.startswith("_") or name == "normcase":
            continue
        setattr(module, name, getattr(posixpath, name))
    return module


fs_path = _path_module_without_normcase()


def _write_epub(path, chapters):
    with zipfile.ZipFile(path, "w") as epub:
        for name, payload in chapters.items():
            epub.writestr(name, payload)


def _run_frequency_worker(epub_path, glossary):
    payloads = []
    errors = []
    worker = GlossaryFrequencyWorker(str(epub_path), glossary)
    worker.analysis_finished.connect(payloads.append)
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert errors == []
    assert len(payloads) == 1
    return payloads[0]


class TermFrequencyToolsTests(unittest.TestCase):
    def test_get_epub_signature_tolerates_path_module_without_normcase(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "book.epub"
            _write_epub(epub_path, {"OEBPS/ch1.xhtml": "<html><body>Text</body></html>"})
            expected_size = epub_path.stat().st_size

            original_path_module = os.path
            try:
                os.path = fs_path
                signature = get_epub_signature(str(epub_path))
            finally:
                os.path = original_path_module

        self.assertTrue(signature["exists"])
        self.assertEqual(signature["size"], expected_size)

    def test_calculate_term_frequency_payload_counts_terms_across_whole_epub(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "book.epub"
            _write_epub(
                epub_path,
                {
                    "OEBPS/ch1.xhtml": "<html><body>High High Low</body></html>",
                    "OEBPS/ch2.xhtml": "<html><body>High Medium Medium</body></html>",
                },
            )

            payload = calculate_term_frequency_payload(
                epub_path,
                [
                    {"original": "High", "rus": "", "note": ""},
                    {"original": "Medium", "rus": "", "note": ""},
                    {"original": "Low", "rus": "", "note": ""},
                ],
            )

        self.assertEqual(payload["terms"]["High"]["count"], 3)
        self.assertEqual(payload["terms"]["Medium"]["count"], 2)
        self.assertEqual(payload["terms"]["Low"]["count"], 1)

    def test_calculate_term_frequency_payload_tolerates_path_module_without_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "book.epub"
            _write_epub(epub_path, {"OEBPS/ch1.xhtml": "<html><body>High High</body></html>"})

            original_path_module = os.path
            try:
                os.path = fs_path
                payload = calculate_term_frequency_payload(
                    str(epub_path),
                    [{"original": "High", "rus": "", "note": ""}],
                )
            finally:
                os.path = original_path_module

        self.assertEqual(payload["terms"]["High"]["count"], 2)

    def test_frequency_worker_counts_single_occurrence_in_utf16_epub(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "book.epub"
            chapter = (
                '<?xml version="1.0" encoding="utf-16"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                "<p>РедкийТермин встречается только здесь.</p>"
                "</body></html>"
            ).encode("utf-16")
            _write_epub(epub_path, {"OEBPS/ch1.xhtml": chapter})

            payload = _run_frequency_worker(
                epub_path,
                [{"original": "РедкийТермин", "rus": "", "note": ""}],
            )

        self.assertEqual(payload["terms"]["РедкийТермин"]["count"], 1)
        self.assertEqual(payload["terms"]["РедкийТермин"]["files"], ["OEBPS/ch1.xhtml"])

    def test_regex_service_counts_unicode_normalized_alpha_term_once(self):
        service = GlossaryRegexService({"Café Noir": {}})

        counts = service.count_matches("Cafe\u0301 Noir appears once.")

        self.assertEqual(counts["Café Noir"], 1)

    def test_regex_service_counts_dash_variants_as_same_alpha_term_once(self):
        service = GlossaryRegexService({"Silver-Eyed Witch": {}})

        counts = service.count_matches("The Silver\u2011Eyed Witch appears once.")

        self.assertEqual(counts["Silver-Eyed Witch"], 1)

    def test_frequency_worker_counts_alpha_suffix_forms_without_separate_glossary_terms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "book.epub"
            chapter = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                "<p>Rune masters opened a school of Rune mastery.</p>"
                "<p>The Traditionalists argued over the traditionalist's vault.</p>"
                "</body></html>"
            ).encode("utf-8")
            _write_epub(epub_path, {"OEBPS/ch1.xhtml": chapter})

            payload = _run_frequency_worker(
                epub_path,
                [
                    {"original": "Rune master", "rus": "", "note": ""},
                    {"original": "Traditionalist", "rus": "", "note": ""},
                ],
            )

        self.assertEqual(payload["terms"]["Rune master"]["count"], 2)
        self.assertEqual(payload["terms"]["Traditionalist"]["count"], 2)

    def test_frequency_worker_does_not_double_count_explicit_alpha_variant_terms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = Path(temp_dir) / "book.epub"
            chapter = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                "<p>Rune masters arrived.</p>"
                "</body></html>"
            ).encode("utf-8")
            _write_epub(epub_path, {"OEBPS/ch1.xhtml": chapter})

            payload = _run_frequency_worker(
                epub_path,
                [
                    {"original": "Rune master", "rus": "", "note": ""},
                    {"original": "Rune masters", "rus": "", "note": ""},
                ],
            )

        self.assertEqual(payload["terms"]["Rune master"]["count"], 1)
        self.assertEqual(payload["terms"]["Rune masters"]["count"], 1)


def _frequency_counts(glossary_terms, chapters):
    """Счёт по временной EPUB, где каждая глава — один абзац: {термин: вхождений}."""
    with tempfile.TemporaryDirectory() as temp_dir:
        epub_path = Path(temp_dir) / "book.epub"
        _write_epub(
            epub_path,
            {
                f"OEBPS/ch{index}.xhtml": (
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    f"<html><body><p>{text}</p></body></html>"
                )
                for index, text in enumerate(chapters, start=1)
            },
        )
        payload = calculate_term_frequency_payload(epub_path, list(glossary_terms))
    return {term: stats["count"] for term, stats in payload["terms"].items()}


class TermCountDoesNotDependOnOtherTermsTests(unittest.TestCase):
    """Счёт термина — как если бы он был в глоссарии один.

    Раньше длинный термин «забирал» кусок текста, а потом его счёт
    прибавлялся всем терминам, которые содержатся в нём как строка. Счёт
    зависел от соседей по глоссарию: удалил редкие — и у оставшихся он
    поменялся, второй проход находил новых «редких»."""

    def test_second_pass_after_deleting_rare_terms_finds_nothing_new(self):
        # Сценарий пользователя на строках из «Небесного Владыки Бездны».
        chapters = [
            "我之绝学名为毁灭刃，能参悟多少便看你的悟性了。",
            "吴渊列为江州威胁榜第十四，潜力榜第一。威胁榜仅仅排第十四。",
        ]
        glossary = ["毁灭刃", "《毁灭刃》", "潜力榜", "威胁榜", "江州威胁榜"]

        first = _frequency_counts(glossary, chapters)
        kept = [term for term in glossary if first[term] > 1]
        second = _frequency_counts(kept, chapters)

        self.assertEqual(kept, ["威胁榜"])
        self.assertEqual(second, {"威胁榜": 2})

    def test_bracketed_twin_does_not_double_count_cjk_term(self):
        # 原初无量 встречается в книге один раз; 《原初无量》 после очистки
        # кавычек — та же строка. Раньше короткая получала 2 и переживала
        # первую чистку.
        counts = _frequency_counts(
            ["原初无量", "《原初无量》"],
            ["半天，原初无量，这就是太源真圣所创的传承"],
        )

        self.assertEqual(counts, {"原初无量": 1, "《原初无量》": 1})

    def test_word_is_not_counted_inside_a_longer_word(self):
        # «Li» отдельным словом не встречается ни разу, только внутри «Lin».
        counts = _frequency_counts(["Li", "Lin Feng"], ["Lin Feng came. Lin Feng left."])

        self.assertEqual(counts, {"Li": 0, "Lin Feng": 2})

    def test_plural_of_compound_term_counts_its_first_word_once(self):
        counts = _frequency_counts(["Dragon", "Dragon King"], ["The Dragon Kings came."])

        self.assertEqual(counts, {"Dragon": 1, "Dragon King": 1})

    def test_overlapping_cjk_terms_are_both_counted(self):
        # Без пробелов нельзя сказать, чьё это вхождение, — считаем оба
        # термина, иначе реально встречающийся уйдёт в кандидаты на удаление.
        counts = _frequency_counts(["林峰", "峰主"], ["林峰主来了"])

        self.assertEqual(counts, {"林峰": 1, "峰主": 1})

    def test_square_bracket_twin_does_not_double_count_bare_word(self):
        counts = _frequency_counts(
            ["[ARMAMENTARIUM]", "ARMAMENTARIUM"],
            ["He cast [ARMAMENTARIUM] once."],
        )

        self.assertEqual(counts, {"[ARMAMENTARIUM]": 1, "ARMAMENTARIUM": 1})

    def test_case_twin_does_not_hide_plural_form(self):
        counts = _frequency_counts(
            ["Acromantula", "acromantulas"],
            ["Acromantulas attacked. An acromantula fled."],
        )

        self.assertEqual(counts, {"Acromantula": 2, "acromantulas": 1})

    def test_multiword_term_is_found_across_line_break_in_markup(self):
        counts = _frequency_counts(["Dragon King"], ["The Dragon\n    King came."])

        self.assertEqual(counts, {"Dragon King": 1})

    def test_cjk_term_is_found_in_other_script_and_across_punctuation(self):
        counts = _frequency_counts(["龙王", "林峰"], ["龍王来了。林·峰笑了"])

        self.assertEqual(counts, {"龙王": 1, "林峰": 1})

    def test_non_cjk_terms_next_to_hanzi_are_counted(self):
        # В китайском тексте нет пробелов: латиница и числа стоят вплотную
        # к иероглифам.
        counts = _frequency_counts(["TED", "1558"], ["他看了TED演讲。1558打出了五杀"])

        self.assertEqual(counts, {"TED": 1, "1558": 1})


if __name__ == "__main__":
    unittest.main()
