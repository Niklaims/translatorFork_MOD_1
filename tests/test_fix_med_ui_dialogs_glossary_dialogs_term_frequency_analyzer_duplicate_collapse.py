# tests/test_fix_med_ui_dialogs_glossary_dialogs_term_frequency_analyzer_duplicate_collapse.py
"""
Регресс на находку ui-dialogs-glossary-b/bugs/5-termfreq-duplicate-collapse.

glossary_map в TermFrequencyAnalyzerPage строился как original -> entry
(последняя запись при итерации побеждает). Если в глоссарии есть две записи
с одинаковым 'original' (обычная ситуация до/во время разрешения прямых
конфликтов), get_patch() адресовал только одну из них — вторая молча
оставалась в глоссарии без изменений, хотя пользователь думал, что решение
принято по термину целиком.
"""

from PyQt6 import QtWidgets

import gemini_translator.ui.dialogs.validation  # noqa: F401 — инициализирует UI-импорты
from gemini_translator.ui.dialogs.glossary_dialogs import term_frequency_analyzer as module


def _make_page(monkeypatch, glossary_data):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # Не даём фоновому анализу стартовать — тестируем только логику патча.
    monkeypatch.setattr(module.QtCore.QTimer, "singleShot", lambda *args: None)
    page = module.TermFrequencyAnalyzerPage(glossary_data, epub_path="unused.epub")
    return page, app


def test_get_patch_deletes_all_duplicate_entries_with_same_original(monkeypatch):
    entry_a = {"original": "魂聖", "rus": "духовный святой", "note": "первая версия"}
    entry_b = {"original": "魂聖", "rus": "святой дух", "note": "нерешённый конфликт"}
    page, app = _make_page(monkeypatch, [entry_a, entry_b])
    try:
        page.terms_to_delete.add("魂聖")

        patch_list = page.get_patch()

        # Обе записи с одинаковым original должны попасть в патч на удаление,
        # а не только последняя по порядку итерации.
        deleted_before = [p["before"] for p in patch_list if p["after"] is None]
        assert entry_a in deleted_before
        assert entry_b in deleted_before
        assert len(deleted_before) == 2
    finally:
        page.deleteLater()
        app.processEvents()


def test_get_patch_updates_all_duplicate_entries_with_same_original(monkeypatch):
    entry_a = {"original": "魂聖", "rus": "духовный святой", "note": "первая версия"}
    entry_b = {"original": "魂聖", "rus": "святой дух", "note": "нерешённый конфликт"}
    page, app = _make_page(monkeypatch, [entry_a, entry_b])
    try:
        page.pending_updates["魂聖"] = {"rus": "новый перевод", "note": "новое примечание"}

        patch_list = page.get_patch()

        updated_before = [p["before"] for p in patch_list if p["after"] is not None]
        # Вторая (скрытая в UI) запись не должна остаться нетронутой —
        # обе версии должны получить патч с новым переводом/примечанием.
        assert entry_a in updated_before
        assert entry_b in updated_before
        assert len(updated_before) == 2
        for p in patch_list:
            if p["after"] is not None:
                assert p["after"]["rus"] == "новый перевод"
                assert p["after"]["note"] == "новое примечание"
    finally:
        page.deleteLater()
        app.processEvents()
