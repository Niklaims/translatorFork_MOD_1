"""
Регресс-тест для utils-io/bugs/3-txtimp-strict-utf8-read.

TxtImportWizardDialog.__init__ читал исходный TXT единственным вызовом
open(path, 'r', encoding='utf-8') без фолбэков, которые есть у
document_importer._read_text_with_fallbacks для .md/.html/.txt в общем
импортёре документов. Файл в другой однобайтовой кодировке (например,
cp1251 — частый случай для русских форумных дампов) валил
UnicodeDecodeError, и мастер сразу закрывался с сообщением об ошибке,
хотя тот же текст успешно читается через многокодировочный фолбэк.
"""

from PyQt6.QtWidgets import QMessageBox

from gemini_translator.utils.txt_importer import TxtImportWizardDialog


def test_cp1251_encoded_txt_is_read_via_fallback_not_rejected(tmp_path, qtbot, monkeypatch):
    text = (
        "Глава 1. Начало\n"
        "Первая строка текста на русском.\n"
        "Глава 2. Продолжение\n"
        "Вторая строка текста на русском.\n"
    )
    txt_path = tmp_path / "novel_cp1251.txt"
    txt_path.write_bytes(text.encode("cp1251"))
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    critical_calls = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: critical_calls.append(a)
    )

    dialog = TxtImportWizardDialog(str(txt_path), str(out_dir))
    qtbot.addWidget(dialog)

    assert not critical_calls, (
        "Мастер не должен показывать ошибку чтения для валидного cp1251-файла: "
        f"{critical_calls}"
    )
    assert dialog.analyzer.lines == text.splitlines()
