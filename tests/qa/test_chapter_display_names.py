"""A chapter id is a file path inside the book; people read it by the file's name."""

from __future__ import annotations

from gemini_translator.qa.report_snapshot import chapter_display_name, chapter_display_names


def test_a_path_reads_as_its_file_name():
    assert chapter_display_name("OEBPS/Text/chapter12.xhtml") == "chapter12"
    assert chapter_display_name("chapter-1") == "chapter-1"
    assert chapter_display_name("Глава 12") == "Глава 12"
    assert chapter_display_name("") == ""


def test_two_files_with_one_name_keep_their_folders():
    names = chapter_display_names(
        ["Text/a/ch1.xhtml", "Text/b/ch1.xhtml", "Text/c/ch2.xhtml"]
    )

    assert names == {
        "Text/a/ch1.xhtml": "Text/a/ch1",
        "Text/b/ch1.xhtml": "Text/b/ch1",
        "Text/c/ch2.xhtml": "ch2",
    }
