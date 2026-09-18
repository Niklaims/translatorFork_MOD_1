# -*- coding: utf-8 -*-
"""Регресс для замечания рецензента (minor, ui_dialogs_validation_b) о
побочном эффекте перехода save_changes на atomic_write_text.

atomic_write_bytes (gemini_translator/utils/io_utils.py) сам делает
``target.parent.mkdir(parents=True, exist_ok=True)``. Раньше, при пропавшей
папке главы (проект перемещён/почищен, пока окно валидации открыто), прямой
``open(filepath, 'w')`` падал с FileNotFoundError -- пользователь видел
громкое "Не удалось сохранить", а data['is_edited'] оставался True (правка не
терялась). После перехода на atomic_write_text та же ситуация молча
воссоздала бы папку и записала главу мимо структуры проекта, тихо сбросив
is_edited -- громкий отказ подменился бы тихим "успехом".

save_changes теперь явно проверяет, что папка главы существует, ДО вызова
atomic_write_text, и поднимает FileNotFoundError сам, если это не так --
поведение отказа остаётся прежним, а не унаследованным от хелпера.

Тест привязывает НАСТОЯЩЕЕ тело save_changes к минимальному объекту с
реальным QTableWidget (offscreen Qt) и настоящей временной папкой на диске.
"""
import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QWidget, QTableWidget, QTableWidgetItem

from gemini_translator.ui.dialogs import validation as validation_module
from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P


_APP = QApplication.instance() or QApplication([])


class _Harness(QWidget):
    """Минимальный объект с настоящим телом save_changes."""

    save_changes = P.save_changes
    update_row_color = P.update_row_color
    _invalidate_analysis_for_data = P._invalidate_analysis_for_data

    def __init__(self, results_data):
        super().__init__()
        self.results_data = results_data
        self.dirty_files = set()
        self._fixer_stale_rows = set()
        self._fixer_data_fingerprint = "stale"
        self.lbl_status = QTableWidgetItem()
        self._analyze_button_state_calls = 0
        self.translated_content_cache = {}

        self.table_results = QTableWidget(len(results_data), 4)
        for row in results_data:
            for col in range(4):
                self.table_results.setItem(row, col, QTableWidgetItem(""))

        class _StubButton:
            def setEnabled(self_inner, value):
                pass

        self.btn_save_changes = _StubButton()

    def _update_analyze_button_state(self):
        self._analyze_button_state_calls += 1


def test_save_changes_fails_loudly_when_chapter_dir_is_missing(tmp_path):
    chapter_dir = tmp_path / "Text"
    chapter_dir.mkdir()
    filepath = chapter_dir / "chapter1.xhtml"
    original_content = "<html><body><p>Оригинал.</p></body></html>"
    filepath.write_text(original_content, encoding="utf-8")

    results_data = {
        0: {
            'path': str(filepath),
            'internal_html_path': 'Text/chapter1.xhtml',
            'translated_html': "<html><body><p>Новый текст.</p></body></html>",
            'is_edited': True,
            'status': 'edited',
        },
    }
    harness = _Harness(results_data)

    # Папка главы пропадает, пока окно валидации открыто (проект
    # перемещён/почищен внешним процессом).
    shutil.rmtree(chapter_dir)
    assert not chapter_dir.exists()

    with patch.object(validation_module.QMessageBox, "critical") as critical_box:
        saved_count = harness.save_changes(show_feedback=False)

    assert saved_count == 0, "запись в пропавшую папку не должна засчитываться как успех"
    assert critical_box.called, "пользователь должен увидеть громкую ошибку, а не тихий успех"
    assert harness.results_data[0]['is_edited'] is True, (
        "правка не должна считаться сохранённой -- is_edited обязан остаться True"
    )
    assert not chapter_dir.exists(), (
        "save_changes не должен молча воссоздавать пропавшую папку главы "
        "(mkdir внутри atomic_write_bytes) -- отказ должен быть громким"
    )
