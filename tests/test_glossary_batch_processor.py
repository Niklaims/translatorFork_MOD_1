import unittest

from gemini_translator.core.worker_helpers.taskers.glossary_batch_processor import (
    filter_glossary_items_for_source_text,
)


class GlossaryBatchProcessorTests(unittest.TestCase):
    def test_source_text_filter_rejects_terms_present_only_in_prompt_examples(self):
        glossary_items = [
            {"original": "Ping", "rus": "Пинг", "note": "Персонаж; Псевдоним"},
            {
                "original": "Martian Manhunter",
                "rus": "Марсианский Охотник",
                "note": "Персонаж; Прозвище",
            },
        ]

        filtered, discarded_count = filter_glossary_items_for_source_text(
            glossary_items,
            "Martian Manhunter stepped into the room.",
            use_jieba_for_glossary_search=True,
        )

        self.assertEqual(discarded_count, 1)
        self.assertEqual([item["original"] for item in filtered], ["Martian Manhunter"])


if __name__ == "__main__":
    unittest.main()
