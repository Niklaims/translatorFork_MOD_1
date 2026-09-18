"""Дедуп dups-gt_utils_language_tools-39 (utils-text/design: dup-normalize-word-glossary).

SmartGlossaryFilter._normalize_word и GlossaryLogic._normalize_word были
одинаковыми методами (отсечение первого подходящего суффикса из
MORPHOLOGY_SUFFIXES_TO_IGNORE). Теперь одна module-level функция
normalize_word, оба класса зовут её напрямую.
"""

from __future__ import annotations

import unittest
from unittest import mock

import gemini_translator.utils.language_tools as lt


class NormalizeWordCharacterizationTests(unittest.TestCase):
    def test_strips_first_matching_suffix_only(self):
        # Порядок MORPHOLOGY_SUFFIXES_TO_IGNORE = ["'s", "es", "s"]: первое совпадение.
        self.assertEqual(lt.normalize_word("cat's"), "cat")
        self.assertEqual(lt.normalize_word("boxes"), "box")
        self.assertEqual(lt.normalize_word("cats"), "cat")
        self.assertEqual(lt.normalize_word("bus"), "bu")      # семантика копий сохранена как есть
        self.assertEqual(lt.normalize_word("tree"), "tree")
        self.assertEqual(lt.normalize_word(""), "")


class RoutingTests(unittest.TestCase):
    def test_copies_are_gone_from_both_classes(self):
        self.assertFalse(hasattr(lt.SmartGlossaryFilter, "_normalize_word"))
        self.assertFalse(hasattr(lt.GlossaryLogic, "_normalize_word"))

    def test_glossary_logic_tokens_route_through_module_function(self):
        logic = lt.GlossaryLogic.__new__(lt.GlossaryLogic)  # без __init__: токенизатору он не нужен
        with mock.patch.object(lt, "normalize_word", side_effect=lambda w: f"<{w}>"):
            tokens = lt.GlossaryLogic._get_universal_tokens(logic, "Cats and boxes")
        self.assertEqual(tokens, ["<cats>", "<and>", "<boxes>"])


if __name__ == "__main__":
    unittest.main()
