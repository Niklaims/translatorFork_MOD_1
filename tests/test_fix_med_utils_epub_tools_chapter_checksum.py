"""
Регресс на находку utils-io/bugs/6-epubtools-weak-chapter-size-fi.

Отпечаток кэша размеров глав (`content_checksum` в
`get_epub_chapter_sizes_with_cache`) считался как простая сумма
`info.file_size` всех html/xhtml записей архива. Если содержимое одной
главы меняется без изменения её байтовой длины (например, часть ASCII-
текста заменяется на кириллицу того же байтового размера — суммарная
длина в байтах та же, но реальное количество токенов другое), сумма
размеров не меняется, а глава, не попавшая в выборку из 3 индексов
sanity-check (0, середина, последний), тихо получает устаревшее
кэшированное значение размера.

Тест собирает epub с 5 главами (некэшируемые главы 1 и 3 не входят в
выборку {0, 2, 4}), правит главу 1 так, чтобы её байтовая длина (и,
следовательно, сумма file_size всех глав, и физический размер архива
при хранении без сжатия) осталась прежней, но реальное количество
токенов изменилось, и проверяет, что вторая генерация кэша возвращает
АКТУАЛЬНОЕ значение, а не устаревшее.
"""

import zipfile

from gemini_translator.utils.epub_tools import (
    TASK_SIZE_UNIT_TOKENS,
    estimate_epub_chapter_input_size,
    get_epub_chapter_sizes_with_cache,
)

FIXED_DATE_TIME = (2020, 1, 1, 0, 0, 0)


class _FakeProjectManager:
    """Минимальный харнесс: хранит кэш размеров в памяти, как ProjectManager."""

    def __init__(self):
        self._cache = None

    def load_size_cache(self):
        return self._cache

    def save_size_cache(self, data):
        self._cache = data


def _chapter_html(body: str) -> bytes:
    return f"<html><body><p>{body}</p></body></html>".encode("utf-8")


def _write_epub(path, chapter_bodies):
    """Пишет epub с несжатыми (ZIP_STORED) html-записями фиксированной даты,
    чтобы физический размер архива зависел только от байтовой длины записей."""
    with zipfile.ZipFile(path, "w") as zf:
        for idx, body in enumerate(chapter_bodies):
            zinfo = zipfile.ZipInfo(f"ch_{idx:02d}.xhtml", date_time=FIXED_DATE_TIME)
            zf.writestr(zinfo, _chapter_html(body), compress_type=zipfile.ZIP_STORED)


def test_chapter_size_cache_detects_same_length_content_edit(tmp_path):
    epub_path = str(tmp_path / "book.epub")

    # 200 ASCII-символов в главе 1 (индекс не входит в выборку sanity-check {0, 2, 4}).
    ascii_body = "A" * 200
    # Кириллица того же байтового размера в UTF-8 (100 симв. * 2 байта = 200 байт),
    # но с другой реальной оценкой токенов (другой множитель chars-per-token).
    cyrillic_body = "а" * 100

    other_bodies = ["base text"] * 5

    original_bodies = list(other_bodies)
    original_bodies[1] = ascii_body
    _write_epub(epub_path, original_bodies)

    pm = _FakeProjectManager()

    # Первый вызов: кэша нет, полный пересчёт и сохранение.
    first_sizes = get_epub_chapter_sizes_with_cache(
        pm, epub_path, task_size_unit=TASK_SIZE_UNIT_TOKENS
    )
    assert "ch_01.xhtml" in first_sizes
    assert first_sizes["ch_01.xhtml"] == estimate_epub_chapter_input_size(
        _chapter_html(ascii_body).decode("utf-8"), TASK_SIZE_UNIT_TOKENS
    )

    # Правим главу 1 так, чтобы байтовая длина записи (и, следовательно,
    # сумма file_size всех глав и физический размер несжатого архива)
    # осталась прежней, но реальный текст (а с ним и число токенов) изменился.
    edited_bodies = list(other_bodies)
    edited_bodies[1] = cyrillic_body
    _write_epub(epub_path, edited_bodies)

    true_size_after_edit = estimate_epub_chapter_input_size(
        _chapter_html(cyrillic_body).decode("utf-8"), TASK_SIZE_UNIT_TOKENS
    )
    # Убедимся, что правка действительно меняет оценку размера — иначе тест
    # ничего не проверяет.
    assert true_size_after_edit != first_sizes["ch_01.xhtml"]

    second_sizes = get_epub_chapter_sizes_with_cache(
        pm, epub_path, task_size_unit=TASK_SIZE_UNIT_TOKENS
    )

    assert second_sizes["ch_01.xhtml"] == true_size_after_edit, (
        "Кэш вернул устаревший размер главы, изменённой без изменения "
        "суммарной длины байт — отпечаток кэша нечувствителен к такой правке"
    )
