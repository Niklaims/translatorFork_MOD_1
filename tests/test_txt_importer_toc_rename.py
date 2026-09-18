"""
Переименование глав прямо в таблице оглавления мастера импорта TXT.

Ячейка названия хранит в UserRole словарь главы, и generate_epub менял в нём
'title', рассчитывая на ссылку в self.structure_data. PyQt6 отдаёт из UserRole
копию словаря, поэтому новое название до книги не доходило. По той же причине
_refresh_toc_table, пересобирая таблицу из structure_data, стирал переименования
при удалении и при разделении глав. Тесты меняют текст ячейки так же, как
редактор после двойного щелчка, и проверяют саму книгу или пересобранную таблицу.
"""

import zipfile

from PyQt6.QtWidgets import QDialog, QMessageBox

from gemini_translator.utils import txt_importer
from gemini_translator.utils.txt_importer import TxtImportWizardDialog


def _open_toc(tmp_path, qtbot, lines, regex=r"^Глава\s*\d+"):
    txt_path = tmp_path / "novel.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    dialog = TxtImportWizardDialog(str(txt_path), str(out_dir))
    qtbot.addWidget(dialog)
    dialog.regex_input.setText(regex)
    dialog.go_to_toc_editor()
    return dialog


def _row(table, title):
    return next(r for r in range(table.rowCount()) if table.item(r, 0).text() == title)


def _rename(table, old_title, new_title):
    # Редактор ячейки меняет только текст; словарь главы в UserRole остаётся прежним
    table.item(_row(table, old_title), 0).setText(new_title)


def _table_titles(table):
    return sorted(table.item(r, 0).text() for r in range(table.rowCount()))


def _chapter_xhtml(dialog, number):
    with zipfile.ZipFile(dialog.generated_epub_path) as epub:
        return epub.read(f"OEBPS/chapter_{number}.xhtml").decode("utf-8")


def test_title_renamed_in_table_reaches_epub(tmp_path, qtbot):
    dialog = _open_toc(tmp_path, qtbot, ["Глава 1", "текст один", "Глава 2", "текст два"])

    _rename(dialog.toc_table, "Глава 1", "Пролог")
    dialog.generate_epub()

    chapter = _chapter_xhtml(dialog, 1)
    assert "<h1>Пролог</h1>" in chapter
    assert "<p>текст один</p>" in chapter
    # Строка заголовка в TXT — «Глава 1»: её нет ни в заголовке, ни в тексте главы
    assert "Глава 1" not in chapter


def test_rename_survives_deleting_another_chapter(tmp_path, qtbot):
    dialog = _open_toc(tmp_path, qtbot, ["Глава 1", "один", "Глава 2", "два", "Глава 3", "три"])
    table = dialog.toc_table

    _rename(table, "Глава 1", "Пролог")
    table.selectRow(_row(table, "Глава 3"))
    dialog.delete_selected_chapter()

    assert _table_titles(table) == ["Глава 2", "Пролог"]


def test_rename_survives_splitting_a_chapter(tmp_path, qtbot, monkeypatch):
    dialog = _open_toc(
        tmp_path, qtbot, ["Глава 1", "один", "Интерлюдия", "между", "Глава 2", "два"]
    )
    table = dialog.toc_table

    def split_at_interlude(viewer):
        # В теле «Главы 1» строка «Интерлюдия» вторая
        viewer.table.setCurrentCell(1, 0)
        viewer.mark_as_header()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(txt_importer.ChapterViewerDialog, "exec", split_at_interlude)

    _rename(table, "Глава 2", "Финал")
    table.selectRow(_row(table, "Глава 1"))
    dialog.open_chapter_viewer()

    assert _table_titles(table) == ["Глава 1", "Интерлюдия", "Финал"]


def test_renamed_preamble_keeps_its_first_line(tmp_path, qtbot):
    # Текст до первой главы мастер собирает в «Начало / Предисловие». У обычной главы
    # первая строка — заголовок и в текст не идёт, у предисловия она часть текста.
    dialog = _open_toc(tmp_path, qtbot, ["Книга о тестах", "Автор: Кто-то", "Глава 1", "один"])

    _rename(dialog.toc_table, "Начало / Предисловие", "От автора")
    dialog.generate_epub()

    preamble = _chapter_xhtml(dialog, 1)
    assert "<h1>От автора</h1>" in preamble
    assert "<p>Книга о тестах</p>" in preamble
    assert "<p>Автор: Кто-то</p>" in preamble


def test_renamed_chapter_can_be_deleted_after_declined_build(tmp_path, qtbot, monkeypatch):
    # Без 第2章 мастер спрашивает, собирать ли книгу с пропуском; пользователь отказывается
    # и остаётся в таблице, где generate_epub уже перенёс новое название в главу
    dialog = _open_toc(
        tmp_path, qtbot, ["第1章", "一", "第3章", "三", "第4章", "四"], regex=r"^第\s*\d+\s*章"
    )
    table = dialog.toc_table
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)

    _rename(table, "第3章", "第3章 归来")
    dialog.generate_epub()
    table.selectRow(_row(table, "第3章 归来"))
    dialog.delete_selected_chapter()

    assert dialog.generated_epub_path is None
    assert _table_titles(table) == ["第1章", "第4章"]
