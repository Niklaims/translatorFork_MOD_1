import json

from PyQt6 import QtGui, QtWidgets

from gemini_translator.ui.selection_translator import (
    SelectionTranslationController,
    TranslationPopup,
    looks_foreign,
    parse_google_translate_response,
    split_text_for_translation,
)


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_google_response_parser_joins_all_translation_parts():
    payload = json.dumps(
        [
            [
                ["Привет", "Hello", None, None, 10],
                [", мир", ", world", None, None, 10],
            ],
            None,
            "en",
        ],
        ensure_ascii=False,
    ).encode("utf-8")

    assert parse_google_translate_response(payload) == "Привет, мир"


def test_translation_splitter_preserves_text_and_size_limit():
    source = ("First paragraph with words.\n\n" * 80) + "Final paragraph."

    chunks = split_text_for_translation(source, max_chars=120)

    assert len(chunks) > 1
    assert "".join(chunks) == source
    assert all(0 < len(chunk) <= 120 for chunk in chunks)


def test_foreign_text_detection_avoids_plain_russian_selection():
    assert looks_foreign("Hello world") is True
    assert looks_foreign("异度旅社") is True
    assert looks_foreign("український текст") is True
    assert looks_foreign("обычный русский текст") is False
    assert looks_foreign("123 — 456") is False


def test_controller_replaces_the_original_line_edit_selection():
    app = _app()
    controller = SelectionTranslationController(app)
    editor = QtWidgets.QLineEdit("Hello world")
    editor.setSelection(0, 5)
    snapshot = controller._selection_snapshot(editor)
    popup = TranslationPopup("Hello", can_replace=True)

    assert snapshot is not None
    controller._replace_selection(snapshot, "Привет", popup)

    assert editor.text() == "Привет world"
    controller.shutdown()
    app.removeEventFilter(controller)
    popup.close()


def test_controller_replaces_multiline_plain_text_selection():
    app = _app()
    controller = SelectionTranslationController(app)
    editor = QtWidgets.QPlainTextEdit()
    editor.setPlainText("Start\nHello world\nEnd")
    cursor = editor.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(17, QtGui.QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    snapshot = controller._selection_snapshot(editor)
    popup = TranslationPopup("Hello world", can_replace=True)

    assert snapshot is not None
    controller._replace_selection(snapshot, "Привет, мир", popup)

    assert editor.toPlainText() == "Start\nПривет, мир\nEnd"
    controller.shutdown()
    app.removeEventFilter(controller)
    popup.close()


def test_controller_excludes_password_and_explicit_secret_fields():
    app = _app()
    controller = SelectionTranslationController(app)
    password = QtWidgets.QLineEdit()
    password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
    key_editor = QtWidgets.QPlainTextEdit()
    key_editor.setProperty("selectionTranslationDisabled", True)

    assert controller._translation_disabled(password) is True
    assert controller._translation_disabled(key_editor) is True
    controller.shutdown()
    app.removeEventFilter(controller)


def test_controller_reads_selected_title_from_chapter_list_without_replacement():
    app = _app()
    controller = SelectionTranslationController(app)
    chapter_panel = QtWidgets.QWidget()
    chapter_panel.setObjectName("chapterListPanel")
    chapter_list = QtWidgets.QListWidget(chapter_panel)
    chapter_list.addItem("第一章 新的开始")
    chapter_list.setCurrentRow(0)

    source = controller._resolve_text_source(chapter_list.viewport())
    snapshot = controller._selection_snapshot(source)

    assert source is chapter_list
    assert snapshot is not None
    assert snapshot.text == "第一章 新的开始"
    assert snapshot.editable is False
    controller.shutdown()
    app.removeEventFilter(controller)
