# -*- coding: utf-8 -*-
"""Регресс для ui-dialogs-validation/runtime/12-non-atomic-chapter-and-glossar
(группа ui_dialogs_validation_b).

TranslationValidatorPage.save_changes писал отредактированный HTML главы
напрямую через ``open(filepath, 'w', encoding='utf-8')``, что усекает файл
в момент открытия. Если запись обрывается посреди (диск переполнен, процесс
убит), на диске остаётся усечённый/пустой файл главы, а
``data['is_edited']`` в памяти уже сброшен -- откатиться некуда.

Тест привязывает НАСТОЯЩЕЕ тело save_changes к минимальному объекту с
реальным QTableWidget (offscreen Qt) и настоящим временным файлом на диске.

(a) Характеризационный тест: имитируем сбой диска на этапе записи байтов
    (не на открытии файла) -- так, чтобы у обеих реализаций (голый open и
    атомарная запись) сбой происходил в одной и той же логической точке.
    Голый ``open(path, 'w')`` усекает целевой файл ДО того, как запись
    вообще начинается, так что после сбоя файл главы пуст. Атомарная запись
    пишет во временный файл и никогда не трогает целевой путь до
    ``os.replace`` -- при сбое оригинал остаётся нетронутым. До исправления
    этот тест ПАДАЕТ на assert-е "файл не тронут".
(b) Тест-маршрутизация: save_changes обязан вызывать канонический
    ``atomic_write_text`` из ``gemini_translator.utils.io_utils``, а не
    писать в файл напрямую.
"""
import builtins
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QWidget, QTableWidget, QTableWidgetItem

from gemini_translator.ui.dialogs import validation as validation_module
from gemini_translator.ui.dialogs.validation import TranslationValidatorPage as P
from gemini_translator.utils import io_utils


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
        self.lbl_status = QTableWidgetItem()  # у QTableWidgetItem есть setText
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


def _make_harness(filepath, translated_html):
    results_data = {
        0: {
            'path': str(filepath),
            'internal_html_path': 'Text/chapter1.xhtml',
            'translated_html': translated_html,
            'is_edited': True,
            'status': 'edited',
        },
    }
    return _Harness(results_data)


class _FaultyWriteFile:
    """Оборачивает файловый объект так, чтобы write() падал -- имитация
    сбоя диска ПОСЛЕ открытия файла (а не отказа в самом open())."""

    def __init__(self, real_file):
        self._real_file = real_file

    def write(self, data):
        raise OSError("disk full (simulated)")

    def __getattr__(self, name):
        return getattr(self._real_file, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._real_file.close()
        return False


def _patched_open_that_fails_on_write(marker):
    """Возвращает замену builtins.open: обычное поведение для всех путей,
    кроме тех, что содержат ``marker`` (целевой файл главы и его temp-копии
    из atomic_write_bytes) -- для них запись байтов имитирует сбой диска,
    но САМ open() отрабатывает как обычно (в 'w'/'wb' режиме это означает,
    что ОС уже усекла файл, если это прямой open() по целевому пути)."""
    real_open = builtins.open

    def _fake_open(path, mode="r", *args, **kwargs):
        real_file = real_open(path, mode, *args, **kwargs)
        if "w" in mode and marker in str(path):
            return _FaultyWriteFile(real_file)
        return real_file

    return _fake_open


# ---------------------------------------------------------------------------
# (a) Характеризационный тест: сбой посреди записи не должен усекать файл
# ---------------------------------------------------------------------------

def test_save_changes_does_not_truncate_file_on_write_failure(tmp_path, monkeypatch):
    filepath = tmp_path / "chapter1_marker.xhtml"
    original_content = "<html><body><p>Оригинал, который нельзя терять.</p></body></html>"
    filepath.write_text(original_content, encoding="utf-8")

    harness = _make_harness(filepath, "<html><body><p>Новый текст.</p></body></html>")

    monkeypatch.setattr(
        builtins, "open", _patched_open_that_fails_on_write("chapter1_marker")
    )

    with patch.object(validation_module.QMessageBox, "critical") as critical_box:
        saved_count = harness.save_changes(show_feedback=False)

    assert saved_count == 0
    assert critical_box.called, "об ошибке сохранения нужно сообщить пользователю"
    # Атомарная запись: сбой посреди работы не должен был тронуть
    # оригинальный файл -- os.replace() не был достигнут.
    assert filepath.read_text(encoding="utf-8") == original_content, (
        "сбой посреди записи не должен усекать/портить файл главы"
    )
    # Никакого временного файла-огрызка рядом с целевым не остаётся.
    leftovers = [p for p in tmp_path.iterdir() if p != filepath]
    assert leftovers == [], f"остался temp-файл: {leftovers}"


# ---------------------------------------------------------------------------
# (b) Маршрутизация: запись обязана идти через канонический atomic_write_text
# ---------------------------------------------------------------------------

def test_save_changes_routes_through_canonical_atomic_write_text(tmp_path):
    filepath = tmp_path / "chapter2.xhtml"
    filepath.write_text("старое содержимое", encoding="utf-8")

    new_html = "<html><body><p>Сохранённая правка.</p></body></html>"
    harness = _make_harness(filepath, new_html)

    calls = []
    real_atomic_write_text = io_utils.atomic_write_text

    def spying_atomic_write_text(path, text, **kwargs):
        calls.append((str(path), text))
        return real_atomic_write_text(path, text, **kwargs)

    with patch(
        "gemini_translator.ui.dialogs.validation.atomic_write_text",
        spying_atomic_write_text,
    ):
        saved_count = harness.save_changes(show_feedback=False)

    assert saved_count == 1
    assert calls == [(str(filepath), new_html)], (
        "save_changes должен передавать путь и HTML главы ровно один раз "
        "в канонический atomic_write_text, а не писать в файл напрямую"
    )
    assert filepath.read_text(encoding="utf-8") == new_html


def test_save_changes_success_path_still_updates_in_memory_state(tmp_path):
    """Убеждаемся, что переход на atomic_write_text не сломал штатное
    поведение при успешной записи (is_edited сбрасывается, статус
    обновляется, файл помечается грязным)."""
    filepath = tmp_path / "chapter3.xhtml"
    filepath.write_text("старое", encoding="utf-8")
    new_html = "<p>ok</p>"
    harness = _make_harness(filepath, new_html)

    saved_count = harness.save_changes(show_feedback=False)

    assert saved_count == 1
    assert harness.results_data[0]['is_edited'] is False
    assert harness.results_data[0]['status'] == 'neutral'
    assert 'Text/chapter1.xhtml' in harness.dirty_files
    assert filepath.read_text(encoding="utf-8") == new_html
