# -*- coding: utf-8 -*-
"""
Регресс на находку ui-dialogs-other/bugs/2-epub-reader-fd-leak-on-bad-opf:
SimpleEpubReader.__init__ открывает self.zf (zipfile.ZipFile), но если
последующий поиск OPF (find_opf_path) бросает исключение — например,
FileNotFoundError на EPUB без валидного container.xml и без .opf файлов —
self.zf никогда не закрывается, потому что исключение улетает из __init__
до того, как объект будет присвоен переменной вызывающего кода (и до того,
как кто-либо успеет вызвать close()).
"""

import zipfile

import pytest

from gemini_translator.ui.dialogs.rulate_export import SimpleEpubReader


def _make_broken_epub(tmp_path):
    """EPUB без META-INF/container.xml и без единого .opf файла."""
    epub_path = tmp_path / "broken.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("some_random_file.txt", "не EPUB-структура")
    return epub_path


def test_init_raises_filenotfounderror_on_epub_without_opf(tmp_path):
    """Сначала убеждаемся, что реальный код падает ожидаемым исключением."""
    epub_path = _make_broken_epub(tmp_path)

    with pytest.raises(FileNotFoundError):
        SimpleEpubReader(str(epub_path))


def test_init_closes_zip_handle_when_opf_lookup_fails(tmp_path):
    """
    Вызываем реальное тело __init__, привязанное к заранее созданному
    экземпляру (через __new__), чтобы сохранить ссылку на self.zf даже
    после того, как __init__ бросит исключение и обычный вызов
    SimpleEpubReader(...) не вернул бы объект вызывающему коду.
    """
    epub_path = _make_broken_epub(tmp_path)

    reader = SimpleEpubReader.__new__(SimpleEpubReader)
    with pytest.raises(FileNotFoundError):
        SimpleEpubReader.__init__(reader, str(epub_path))

    # До фикса: self.zf остаётся открытым (reader.zf.fp is not None) —
    # дескриптор файла .epub утекает, т.к. вызывающий код (load_chapters_only/
    # run) не может вызвать close() для объекта, который не был присвоен.
    assert reader.zf.fp is None, (
        "self.zf должен быть закрыт, если инициализация SimpleEpubReader "
        "не завершилась успешно (иначе течёт файловый дескриптор .epub)"
    )
