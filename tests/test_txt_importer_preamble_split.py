"""
Предисловие в мастере импорта TXT: разделение через «Просмотр / Разделить...» и перенумерация.

У обычной главы первая строка — заголовок, в просмотр идёт текст после неё. У предисловия
заголовка нет, и строка 0 уже часть текста. ChapterViewerDialog.mark_as_header при этом
всегда прибавлял единицу на пропущенный заголовок, поэтому новая глава из предисловия
вставала на строку ниже выбранной: выбранная строка оставалась в предисловии, а следующая
пропадала из книги как заголовок. Тесты выбирают строку в настоящем просмотре и проверяют
главы собранного EPUB.

С тех пор как главы можно переименовывать в таблице, предисловие узнаётся по флагу
is_preamble, а не по названию, — это же нужно просмотру и «Сквозной перенумерации».
"""

import re
import zipfile

from PyQt6.QtWidgets import QDialog

from gemini_translator.utils import txt_importer
from gemini_translator.utils.txt_importer import TxtImportWizardDialog


def _open_toc(tmp_path, qtbot, lines):
    txt_path = tmp_path / "novel.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    dialog = TxtImportWizardDialog(str(txt_path), str(out_dir))
    qtbot.addWidget(dialog)
    dialog.regex_input.setText(r"^Глава\s*\d+")
    dialog.go_to_toc_editor()
    return dialog


def _row(table, title):
    return next(r for r in range(table.rowCount()) if table.item(r, 0).text() == title)


def _select(table, title):
    table.selectRow(_row(table, title))


def _rename(table, old_title, new_title):
    # Редактор ячейки меняет только текст; словарь главы в UserRole остаётся прежним
    table.item(_row(table, old_title), 0).setText(new_title)


def _split_at(monkeypatch, line_text):
    # Пользователь выделяет строку в просмотре и жмёт «Сделать заголовком новой главы»
    def choose_line(viewer):
        rows = [viewer.table.item(r, 0).text() for r in range(viewer.table.rowCount())]
        viewer.table.setCurrentCell(rows.index(line_text), 0)
        viewer.mark_as_header()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(txt_importer.ChapterViewerDialog, "exec", choose_line)


def _chapters(dialog):
    # [(заголовок, [абзацы])] в порядке глав книги
    with zipfile.ZipFile(dialog.generated_epub_path) as epub:
        names = sorted(
            (name for name in epub.namelist() if re.fullmatch(r"OEBPS/chapter_\d+\.xhtml", name)),
            key=lambda name: int(re.search(r"\d+", name).group()),
        )
        chapters = []
        for name in names:
            xhtml = epub.read(name).decode("utf-8")
            chapters.append((re.search(r"<h1>(.*?)</h1>", xhtml).group(1), re.findall(r"<p>(.*?)</p>", xhtml)))
        return chapters


def test_splitting_preamble_starts_chapter_at_selected_line(tmp_path, qtbot, monkeypatch):
    dialog = _open_toc(tmp_path, qtbot, ["Книга", "Пролог", "текст пролога", "Глава 1", "один"])

    _select(dialog.toc_table, "Начало / Предисловие")
    _split_at(monkeypatch, "Пролог")
    dialog.open_chapter_viewer()
    dialog.generate_epub()

    assert _chapters(dialog) == [
        ("Начало / Предисловие", ["Книга"]),
        ("Пролог", ["текст пролога"]),
        ("Глава 1", ["один"]),
    ]


def test_splitting_regular_chapter_starts_chapter_at_selected_line(tmp_path, qtbot, monkeypatch):
    dialog = _open_toc(tmp_path, qtbot, ["Глава 1", "один", "Интерлюдия", "между", "Глава 2", "два"])

    _select(dialog.toc_table, "Глава 1")
    _split_at(monkeypatch, "Интерлюдия")
    dialog.open_chapter_viewer()
    dialog.generate_epub()

    assert _chapters(dialog) == [
        ("Глава 1", ["один"]),
        ("Интерлюдия", ["между"]),
        ("Глава 2", ["два"]),
    ]


def test_splitting_preamble_at_its_first_line_turns_preamble_into_chapter(tmp_path, qtbot, monkeypatch):
    # Регулярное выражение не узнало «Пролог» в первой строке, и он попал в предисловие.
    # Текста до этой строки нет, поэтому пустое предисловие оставлять незачем.
    dialog = _open_toc(tmp_path, qtbot, ["Пролог", "текст пролога", "Глава 1", "один"])

    _select(dialog.toc_table, "Начало / Предисловие")
    _split_at(monkeypatch, "Пролог")
    dialog.open_chapter_viewer()
    dialog.generate_epub()

    assert _chapters(dialog) == [
        ("Пролог", ["текст пролога"]),
        ("Глава 1", ["один"]),
    ]


def test_renamed_preamble_shows_its_first_line_in_viewer(tmp_path, qtbot, monkeypatch):
    dialog = _open_toc(tmp_path, qtbot, ["Книга", "Пролог", "Глава 1", "один", "Глава 2", "два"])
    table = dialog.toc_table
    shown = []

    def look(viewer):
        shown.extend(viewer.table.item(r, 0).text() for r in range(viewer.table.rowCount()))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(txt_importer.ChapterViewerDialog, "exec", look)

    _rename(table, "Начало / Предисловие", "От автора")
    # Удаление пересобирает таблицу, и новое название попадает в данные главы
    _select(table, "Глава 2")
    dialog.delete_selected_chapter()
    _select(table, "От автора")
    dialog.open_chapter_viewer()

    assert shown == ["Книга", "Пролог"]


def test_renumbering_leaves_renamed_preamble_unnumbered_and_counts_chapters_from_one(tmp_path, qtbot):
    dialog = _open_toc(tmp_path, qtbot, ["Книга", "Глава 5", "один", "Глава 9", "два"])

    _rename(dialog.toc_table, "Начало / Предисловие", "От автора")
    dialog.chk_force_renumber.setChecked(True)
    dialog.generate_epub()

    assert [title for title, _ in _chapters(dialog)] == ["От автора", "Глава 1", "Глава 2"]


def test_renumbering_without_preamble_counts_chapters_from_one(tmp_path, qtbot):
    dialog = _open_toc(tmp_path, qtbot, ["Глава 5", "один", "Глава 9", "два"])

    dialog.chk_force_renumber.setChecked(True)
    dialog.generate_epub()

    assert [title for title, _ in _chapters(dialog)] == ["Глава 1", "Глава 2"]
