"""A manual pass walks the book the way its chapter list reads, not as sorted strings."""

from __future__ import annotations

from pathlib import Path

from gemini_translator.qa.assembly import build_manual_events


class _ProjectManager:
    def __init__(self, folder: Path, data: dict) -> None:
        self.project_folder = str(folder)
        self.data = data


def test_chapters_are_checked_in_their_natural_order(tmp_path: Path) -> None:
    """Строковая сортировка вела проход по chapter1, chapter10, chapter100, chapter1000."""
    data = {}
    for name in ("chapter1000", "chapter2", "chapter10", "chapter1", "chapter100"):
        (tmp_path / f"{name}_translated.html").write_text("перевод", encoding="utf-8")
        data[f"OEBPS/{name}.xhtml"] = {"_translated.html": f"{name}_translated.html"}

    events = build_manual_events(project_manager=_ProjectManager(tmp_path, data), epub_path="")

    assert [event.chapter_id for event in events] == [
        "OEBPS/chapter1.xhtml",
        "OEBPS/chapter2.xhtml",
        "OEBPS/chapter10.xhtml",
        "OEBPS/chapter100.xhtml",
        "OEBPS/chapter1000.xhtml",
    ]
