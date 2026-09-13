"""
Регресс для находки mcp-bench-cli/bugs/6-filter-repack-duplicate-chapte.

В режиме «разбавить» (`FilterPackagingDialog._calculate_new_chapter_list`,
dilute-ветка) `itertools.cycle(self.successful_chapters)` использовался без
ограничения на количество уникальных успешных глав. Если пользователь просит
больше глав на пакет (`chapters_per_batch_spin`, диапазон 2..50), чем есть
успешных глав, одна и та же успешная глава попадает в ОДИН и тот же
epub_batch payload несколько раз — модель тратит вызов API на повторный
перевод одного и того же контента внутри одной задачи впустую.

Тест воспроизводит боевой метод `_calculate_new_chapter_list` на минимальном
диалоге (offscreen Qt, без сети/реальных настроек) и проверяет, что список
глав внутри одного batch-payload не содержит повторов.
"""
import os
import unittest
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.scripts.package_filter_tasks import FilterPackagingDialog


class FilterPackagingDiluteDuplicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_dilute_mode_does_not_duplicate_successful_chapter_within_one_batch(self):
        """1 успешная глава, chapters_per_batch=5 => num_needed_to_pad=4.
        До фикса cycle() вернул бы одну и ту же главу 4 раза подряд в один batch.
        """
        dialog = FilterPackagingDialog(
            filtered_chapters=["Text/bad1.xhtml"],
            successful_chapters=["Text/good1.xhtml"],
            recommended_size=10_000,
            epub_path="book.epub",
            real_chapter_sizes={
                "Text/bad1.xhtml": 100,
                "Text/good1.xhtml": 100,
            },
        )
        self.addCleanup(dialog.close)
        dialog.chapters_per_batch_spin.setValue(5)
        self.assertTrue(dialog.dilute_checkbox.isChecked())

        result = dialog._calculate_new_chapter_list()

        self.assertEqual(result["type"], "payloads")
        payload = result["data"][0]
        batch_chapters = payload[2]

        counts = Counter(batch_chapters)
        duplicated = {chapter: n for chapter, n in counts.items() if n > 1}
        self.assertFalse(
            duplicated,
            f"Одна и та же глава повторилась внутри одного batch-payload: {duplicated} "
            f"(batch={batch_chapters})",
        )
        # Главную (плохую) главу всё ещё нужно сохранить.
        self.assertIn("Text/bad1.xhtml", batch_chapters)
        self.assertEqual(payload[3]["save_chapters"], ["Text/bad1.xhtml"])

    def test_dilute_mode_still_pads_up_to_available_successful_chapters(self):
        """При нескольких успешных главах и достаточном chapters_per_batch
        поведение разбавления не должно урезаться сверх необходимого."""
        dialog = FilterPackagingDialog(
            filtered_chapters=["Text/bad1.xhtml"],
            successful_chapters=["Text/good1.xhtml", "Text/good2.xhtml", "Text/good3.xhtml"],
            recommended_size=10_000,
            epub_path="book.epub",
            real_chapter_sizes={
                "Text/bad1.xhtml": 100,
                "Text/good1.xhtml": 100,
                "Text/good2.xhtml": 100,
                "Text/good3.xhtml": 100,
            },
        )
        self.addCleanup(dialog.close)
        dialog.chapters_per_batch_spin.setValue(4)

        result = dialog._calculate_new_chapter_list()

        payload = result["data"][0]
        batch_chapters = payload[2]
        self.assertEqual(len(batch_chapters), 4)
        self.assertEqual(len(set(batch_chapters)), 4)


if __name__ == "__main__":
    unittest.main()
