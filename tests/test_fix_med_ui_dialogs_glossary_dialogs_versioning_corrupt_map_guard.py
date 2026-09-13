"""ui-dialogs-glossary-b/bugs/7 (вторая половина): битый glossary_versions.json
молча читается как «версий нет» и первое же сохранение атомарно и
необратимо затирает версии ВСЕХ терминов проекта одним self.term.

Атомарность записи (project_manager._write_version_map_unsafe ->
atomic_write_text) сама по себе НЕ защищает от этого сценария — она лишь
гарантирует, что на диск ляжет полностью валидный, но уже урезанный до
одного термина JSON.

TermVersioningDialog обязан отличать «в карте действительно нет версий» от
«файл есть и не пуст, но не прочитан» — и в последнем случае предупредить
пользователя и заблокировать сохранение, а не разрешать
_save_all_versions() перезаписать карту.

До исправления: QMessageBox.warning не вызывается, а _save_all_versions()
перезаписывает glossary_versions.json, уничтожая версии термина Alpha/Beta.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GT_DISABLE_LOCAL_MODEL_DISCOVERY", "1")

import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QMessageBox

from gemini_translator.utils.project_manager import TranslationProjectManager
from gemini_translator.ui.dialogs.glossary_dialogs.versioning import TermVersioningDialog


_APP = None


def _ensure_app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class CorruptVersionMapGuardTests(unittest.TestCase):
    def setUp(self):
        _ensure_app()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.pm = TranslationProjectManager(self.tmpdir.name)
        self.version_file = os.path.join(self.tmpdir.name, "glossary_versions.json")

        # Заранее пишем валидную карту с двумя терминами, затем портим файл
        # усечением (имитация сбоя посреди не-атомарной внешней записи или
        # повреждения диска) — ровно сценарий из failure_scenario ревьюера.
        self.pm.save_version_map(
            {
                "Alpha": [{"scope": ["ch1.xhtml"], "override": {"rus": "А"}}],
                "Beta": [{"scope": ["ch2.xhtml"], "override": {"rus": "Б"}}],
            }
        )
        with open(self.version_file, "r", encoding="utf-8") as f:
            valid_content = f.read()
        truncated = valid_content[: len(valid_content) // 2]
        with open(self.version_file, "w", encoding="utf-8") as f:
            f.write(truncated)
        self.original_bytes = truncated.encode("utf-8")

        # Убеждаемся, что порча действительно воспроизводит «молчаливый {}»
        # на уровне project_manager (иначе тест был бы про другой дефект).
        assert self.pm.load_version_map() == {}

    def _make_dialog(self):
        return TermVersioningDialog(
            term="Gamma",
            base_data={"rus": "Гамма", "note": ""},
            project_manager=self.pm,
            epub_path=None,
        )

    def test_construction_warns_when_version_file_is_corrupt(self):
        with patch.object(QMessageBox, "warning") as mocked_warning:
            dlg = self._make_dialog()
            try:
                mocked_warning.assert_called_once()
                self.assertTrue(getattr(dlg, "_versions_unreadable", False))
            finally:
                dlg.deleteLater()

    def test_save_after_corrupt_load_does_not_clobber_other_terms(self):
        with patch.object(QMessageBox, "warning"):
            dlg = self._make_dialog()
        try:
            dlg.term_rules.append(
                {"scope": ["ch3.xhtml"], "override": {"rus": "Гамма-версия"}}
            )
            with patch.object(QMessageBox, "warning") as mocked_warning_on_save:
                dlg._save_all_versions()
                mocked_warning_on_save.assert_called_once()

            with open(self.version_file, "rb") as f:
                after_bytes = f.read()
            self.assertEqual(
                after_bytes,
                self.original_bytes,
                "Сохранение поверх нечитаемой карты не должно менять файл на диске",
            )
        finally:
            dlg.deleteLater()

    def test_construction_does_not_warn_when_map_is_genuinely_empty(self):
        """Файла нет вовсе — это законное «версий ещё не было», а не
        повреждение; предупреждение показывать не нужно."""
        empty_dir = tempfile.TemporaryDirectory()
        self.addCleanup(empty_dir.cleanup)
        pm2 = TranslationProjectManager(empty_dir.name)
        with patch.object(QMessageBox, "warning") as mocked_warning:
            dlg = TermVersioningDialog(
                term="Gamma",
                base_data={"rus": "Гамма", "note": ""},
                project_manager=pm2,
                epub_path=None,
            )
            try:
                mocked_warning.assert_not_called()
                self.assertFalse(getattr(dlg, "_versions_unreadable", False))
            finally:
                dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
