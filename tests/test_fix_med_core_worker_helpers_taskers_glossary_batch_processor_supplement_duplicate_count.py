# -*- coding: utf-8 -*-
"""
Регресс на core-b/bugs/2-glossary-supplement-duplicate-.

В режиме merge_mode == 'supplement' (с включённым new_terms_limit) счётчик
дублей должен считаться ДО очистки updated_terms, а не после — иначе
итоговое сообщение всегда показывает "дубликатов: 0" независимо от
фактического числа найденных дублей.
"""

import asyncio
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from gemini_translator.core.worker_helpers.taskers.glossary_batch_processor import (
    GlossaryBatchProcessor,
)


class _FakePromptBuilder:
    def __init__(self, full_context_glossary):
        self._full_context_glossary = full_context_glossary

    def prepare_for_glossary_generation(self, full_text_for_api, *, settings, task_manager):
        # log_info пустой -> ветка логирования контекста в execute() пропускается.
        return "PROMPT", None, None, {}, self._full_context_glossary


class _FakeTaskManager:
    def __init__(self, stats):
        self._stats = stats
        self.saved_glossary_list = None

    def save_glossary_batch(self, *, task_id, timestamp, chapters_json, glossary_list):
        self.saved_glossary_list = glossary_list
        return self._stats


class _FakeWorker:
    def __init__(self, *, full_context_glossary, stats, new_terms_limit):
        self.worker_id = "fakeworker0000"
        self.glossary_merge_mode = "supplement"
        self.new_terms_limit = new_terms_limit
        self.force_accept = True  # пропускаем фильтрацию по исходному тексту/кириллице
        self.prompt_builder = _FakePromptBuilder(full_context_glossary)
        self.task_manager = _FakeTaskManager(stats)
        self.logged_messages = []

    def _post_event(self, name, payload):
        if name == "log_message":
            self.logged_messages.append(payload.get("message", ""))


class _TestableGlossaryBatchProcessor(GlossaryBatchProcessor):
    """Подменяем реальный вызов API — сам вызов API не является предметом теста."""

    def __init__(self, worker, ai_response_text):
        super().__init__(worker)
        self._ai_response_text = ai_response_text

    async def _execute_api_call(self, prompt, log_prefix, **kwargs):
        return self._ai_response_text


def _make_epub(tmp_dir: Path) -> Path:
    epub_path = tmp_dir / "book.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(
            "OEBPS/chapter1.html",
            "<html><body>Существующий герой встретил Новый персонаж.</body></html>",
        )
    return epub_path


def _run(coro):
    return asyncio.run(coro)


class SupplementDuplicateCountTests(unittest.TestCase):
    def test_supplement_mode_reports_actual_duplicate_count(self):
        # "Существующий" уже есть в глоссарии проекта -> должен уйти в updated_terms,
        # затем (в режиме supplement) быть отброшен, но посчитан как дубликат.
        full_context_glossary = [{"original": "Существующий"}]
        ai_response = json.dumps(
            {
                "Существующий": {"rus": "Существующий-перевод"},
                "Новый": {"rus": "Новый-перевод"},
            },
            ensure_ascii=False,
        )
        # stats['updated'] намеренно отличается от реального числа дублей (1),
        # чтобы тест не мог случайно пройти на fallback-ветке `stats['updated']`.
        fake_stats = {"total": 1, "new": 1, "updated": 5}

        with TemporaryDirectory() as tmp:
            epub_path = _make_epub(Path(tmp))
            worker = _FakeWorker(
                full_context_glossary=full_context_glossary,
                stats=fake_stats,
                new_terms_limit=10,
            )
            processor = _TestableGlossaryBatchProcessor(worker, ai_response)

            task_info = ("task1", ("glossary_batch_task", str(epub_path), ["OEBPS/chapter1.html"]))
            result = _run(processor.execute(task_info))

        self.assertTrue(result[1])  # успех

        final_messages = [m for m in worker.logged_messages if m.startswith("✅")]
        self.assertEqual(len(final_messages), 1)
        final_msg = final_messages[0]

        # Ключевая проверка дефекта: реальное число дублей (1), а не 0
        # (баг: len() очищенного списка) и не 5 (fallback на stats['updated']).
        self.assertIn("дубликатов: 1", final_msg)
        self.assertNotIn("дубликатов: 0", final_msg)
        self.assertNotIn("дубликатов: 5", final_msg)

        # Дубликат не должен попасть в то, что реально сохраняется в базу.
        saved_originals = {
            item["original"] for item in worker.task_manager.saved_glossary_list
        }
        self.assertNotIn("Существующий", saved_originals)
        self.assertIn("Новый", saved_originals)


if __name__ == "__main__":
    unittest.main()
