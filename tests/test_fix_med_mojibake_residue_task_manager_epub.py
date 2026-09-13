"""Остатки мохибейка (рецензия волны 2, ui-widgets-b/bugs/2): те же
повреждённые последовательности, что были в подписях chapter_list_widget,
жили ещё в двух строках лога task_manager.py («స్త 'Заморожено'») и в
подписи кнопки epub.py («롤 Восстановить оригинал»). Тесты сканируют
исходники: чужие алфавиты (телугу, хангыль) в этих файлах появляться не
должны, а восстановленные значки — должны.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_MANAGER = ROOT / "gemini_translator" / "core" / "task_manager.py"
EPUB_DIALOG = ROOT / "gemini_translator" / "ui" / "dialogs" / "epub.py"


def _foreign_script_chars(text: str) -> list[str]:
    return sorted({
        ch for ch in text
        if 0x0C00 <= ord(ch) <= 0x0C7F      # телугу
        or 0xAC00 <= ord(ch) <= 0xD7A3      # хангыль (слоги)
    })


def test_task_manager_freeze_log_lines_use_the_snowflake_icon():
    source = TASK_MANAGER.read_text(encoding="utf-8")
    assert _foreign_script_chars(source) == []
    freeze_lines = [line for line in source.splitlines() if "'Заморожено'" in line]
    assert freeze_lines, "строки лога про заморозку должны остаться"
    assert all("❄️" in line for line in freeze_lines)


def test_epub_restore_button_label_has_an_icon_instead_of_hangul():
    source = EPUB_DIALOG.read_text(encoding="utf-8")
    assert _foreign_script_chars(source) == []
    labels = [line for line in source.splitlines() if "Восстановить оригинал" in line]
    assert labels, "подпись кнопки восстановления должна остаться"
    assert all("↩️ Восстановить оригинал" in line for line in labels)
