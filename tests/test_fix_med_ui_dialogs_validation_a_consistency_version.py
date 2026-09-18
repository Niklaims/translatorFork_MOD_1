"""Регресс для ui-dialogs-validation/logic/5-consistency-check-arbitrary-ve.

_on_consistency_check раньше брал versions.get('') (такого ключа не бывает —
ключи это суффиксы вида '_translated_gemini.html') и при его отсутствии первую
ЗАРЕГИСТРИРОВАННУЮ версию (next(iter(versions.values()))), а не актуальную
(select_target_translation_version — приоритет _validated, затем лучшая по
mtime). Тест воспроизводит главу с двумя версиями перевода, где более старая
по времени регистрации версия новее на диске, и проверяет, что «Проверка
согласованности» анализирует именно её, а не первую по порядку вставки.
"""

import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from gemini_translator.ui.dialogs.validation import TranslationValidatorDialog


class _ProjectManagerStub:
    def __init__(self, project_folder, originals, versions_map):
        self.project_folder = project_folder
        self._originals = originals
        self._versions_map = versions_map

    def get_all_originals(self):
        return list(self._originals)

    def get_versions_for_original(self, original_path):
        # Обычный dict, как в реальном ProjectManager — порядок вставки
        # сохраняется, но не должен влиять на выбор версии.
        return dict(self._versions_map.get(original_path, {}))


class _ProgressDialogStub:
    def __init__(self, *args, **kwargs):
        self.value = 0

    def setWindowModality(self, *args, **kwargs):
        return None

    def show(self):
        return None

    def close(self):
        return None

    def wasCanceled(self):
        return False

    def setValue(self, value):
        self.value = value


class _MessageBoxStub:
    @staticmethod
    def warning(*args, **kwargs):
        return None


class ConsistencyCheckPicksTargetVersionTests(unittest.TestCase):
    def test_uses_select_target_translation_version_not_insertion_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            internal_path = "Text/chapter1.xhtml"
            # Зарегистрирован первым (в реальности — старый Gemini-перевод):
            # старый баг брал именно его через next(iter(versions.values())).
            first_registered_rel = "translated/chapter1_translated_gemini.html"
            # Зарегистрирован вторым, но физически это САМЫЙ СВЕЖИЙ файл —
            # именно его показывает таблица валидатора и берёт сборка EPUB.
            second_registered_rel = "translated/chapter1_translated_dp.html"

            first_full = os.path.join(temp_dir, first_registered_rel)
            second_full = os.path.join(temp_dir, second_registered_rel)
            os.makedirs(os.path.dirname(first_full), exist_ok=True)
            os.makedirs(os.path.dirname(second_full), exist_ok=True)

            with open(first_full, "w", encoding="utf-8") as fh:
                fh.write("<p>older on disk, registered first</p>")
            # Гарантируем различимый mtime между файлами.
            old_time = time.time() - 100
            os.utime(first_full, (old_time, old_time))

            with open(second_full, "w", encoding="utf-8") as fh:
                fh.write("<p>newer on disk, registered second</p>")

            captured = {}
            fake_dialog_module = types.ModuleType(
                "gemini_translator.ui.dialogs.consistency_checker"
            )

            class _ConsistencyDialogStub:
                def __init__(self, chapters, *args, **kwargs):
                    captured["chapters"] = chapters

                def exec(self):
                    return 0

            fake_dialog_module.ConsistencyValidatorDialog = _ConsistencyDialogStub

            harness = type("ConsistencyHarness", (), {})()
            harness.settings_manager = object()
            harness.translated_folder = temp_dir
            harness.project_manager = _ProjectManagerStub(
                temp_dir,
                [internal_path],
                {
                    internal_path: {
                        first_registered_rel: first_registered_rel,
                        second_registered_rel: second_registered_rel,
                    }
                },
            )
            harness.results_data = {}

            with patch.dict(sys.modules, {fake_dialog_module.__name__: fake_dialog_module}), \
                 patch("gemini_translator.ui.dialogs.validation.QProgressDialog", _ProgressDialogStub), \
                 patch("gemini_translator.ui.dialogs.validation.QMessageBox", _MessageBoxStub):
                TranslationValidatorDialog._on_consistency_check(harness)

            self.assertEqual(len(captured["chapters"]), 1)
            self.assertEqual(
                captured["chapters"][0]["content"],
                "<p>newer on disk, registered second</p>",
            )
            self.assertEqual(
                os.path.abspath(captured["chapters"][0]["path"]),
                os.path.abspath(second_full),
            )


if __name__ == "__main__":
    unittest.main()
