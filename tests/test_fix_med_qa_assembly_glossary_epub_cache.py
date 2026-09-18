"""qa/assembly.py не должен перечитывать глоссарий и переоткрывать EPUB.

До правки load_project_glossary_terms() заново открывала и парсила
project_glossary.json на КАЖДЫЙ вызов build_chapter_qa_request (т.е. на
каждую главу QA-прохода), а _read_source_chapter() заново открывала
zipfile.ZipFile(epub_path) на каждую главу — хотя ни глоссарий, ни исходный
EPUB не меняются в течение одного прохода. Тесты проверяют алгоритмическое
свойство: число реальных чтений/парсингов не растёт с числом проверенных
глав, а не время выполнения.

Дополнительно (по замечаниям ревью к первой версии фикса):
- кэш открытых EPUB-архивов держит не больше одной книги и закрывает
  дескриптор прежней книги сразу, а не бессрочно (без этого приложение на
  Windows не могло бы перезаписать/удалить исходный EPUB, который QA держит
  открытым);
- инвалидация EPUB-кэша по изменению файла закреплена тестом-близнецом к
  глоссарному (раньше проверялась только вручную).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import zipfile

import pytest

from gemini_translator.core.chapter_qa_coordinator import TranslationReadyEvent
from gemini_translator.qa import assembly
from gemini_translator.qa.assembly import build_chapter_qa_request
from gemini_translator.qa.llm import QaModelSelection
from gemini_translator.qa.settings import QaSettings


_SOURCE_HTML = "<p>Text of a chapter, long enough to matter.</p>"
_TARGET_HTML = "<p>Текст главы, достаточно длинный, чтобы иметь значение.</p>"


class _ProjectManager:
    def __init__(self, folder: Path) -> None:
        self.project_folder = str(folder)


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """Кэши модульного уровня не должны утекать между тестами."""
    assembly._GLOSSARY_CACHE.clear()
    assembly.close_cached_source_archives()
    yield
    assembly.close_cached_source_archives()
    assembly._GLOSSARY_CACHE.clear()


def _write_glossary(tmp_path: Path, entries: list[dict[str, str]] | None = None) -> None:
    (tmp_path / "project_glossary.json").write_text(
        json.dumps(
            entries or [{"original": "tower", "rus": "башня"}], ensure_ascii=False
        ),
        encoding="utf-8",
    )


def _write_epub(
    tmp_path: Path, chapter_paths: tuple[str, ...], *, name: str = "book.epub", text: str = _SOURCE_HTML
) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for chapter_path in chapter_paths:
            archive.writestr(chapter_path, text)
    return path


def _bump_mtime(path: Path) -> None:
    # mtime может не измениться в пределах той же секунды на некоторых ФС —
    # сдвигаем явно вперёд, чтобы отпечаток файла точно поменялся.
    future = time.time() + 5
    os.utime(path, (future, future))


def _events(tmp_path: Path, epub_path: Path, chapter_paths: tuple[str, ...]):
    events = []
    for chapter_path in chapter_paths:
        translated = tmp_path / (chapter_path.replace("/", "_") + ".html")
        translated.write_text(_TARGET_HTML, encoding="utf-8")
        events.append(
            TranslationReadyEvent(
                task_id="task-1",
                chapter_id=chapter_path,
                source_path=chapter_path,
                translated_path=str(translated),
                source_language="auto",
                target_language="ru",
                epub_path=str(epub_path),
            )
        )
    return events


def _build_all(tmp_path: Path, project: _ProjectManager, events) -> None:
    for event in events:
        request = build_chapter_qa_request(
            event,
            project_manager=project,
            qa_settings=QaSettings(),
            model=QaModelSelection("gemini", "qa-model"),
            session_id="session-1",
            source_language_resolver=lambda html: "en",
        )
        assert request is not None


def test_glossary_is_parsed_once_across_many_chapters(tmp_path, monkeypatch):
    """Один и тот же глоссарий не должен парситься на каждую главу."""
    _write_glossary(tmp_path)
    project = _ProjectManager(tmp_path)
    chapter_paths = ("OEBPS/c1.xhtml", "OEBPS/c2.xhtml", "OEBPS/c3.xhtml")
    epub_path = _write_epub(tmp_path, chapter_paths)
    events = _events(tmp_path, epub_path, chapter_paths)

    original_loads = json.loads
    calls = {"n": 0}

    def counting_loads(*args, **kwargs):
        calls["n"] += 1
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(assembly.json, "loads", counting_loads)

    _build_all(tmp_path, project, events)

    assert calls["n"] == 1, (
        "project_glossary.json должен парситься один раз на весь проход, "
        f"а не на каждую из {len(events)} глав"
    )


def test_source_epub_is_opened_once_across_many_chapters(tmp_path, monkeypatch):
    """Один и тот же EPUB не должен переоткрываться на каждую главу."""
    _write_glossary(tmp_path)
    project = _ProjectManager(tmp_path)
    chapter_paths = ("OEBPS/c1.xhtml", "OEBPS/c2.xhtml", "OEBPS/c3.xhtml")
    epub_path = _write_epub(tmp_path, chapter_paths)
    events = _events(tmp_path, epub_path, chapter_paths)

    real_zipfile_cls = zipfile.ZipFile
    opens = {"n": 0}

    class CountingZipFile(real_zipfile_cls):
        def __init__(self, *args, **kwargs):
            opens["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(assembly.zipfile, "ZipFile", CountingZipFile)

    _build_all(tmp_path, project, events)

    assert opens["n"] == 1, (
        "исходный EPUB должен открываться один раз на весь проход, "
        f"а не на каждую из {len(events)} глав"
    )


def test_glossary_cache_invalidates_when_the_file_changes(tmp_path):
    """Правка глоссария посреди сессии обязана быть видна следующей главе."""
    _write_glossary(tmp_path)
    project = _ProjectManager(tmp_path)

    first = assembly.load_project_glossary_terms(project.project_folder)
    assert {term.original for term in first} == {"tower"}

    glossary_path = tmp_path / "project_glossary.json"
    _write_glossary(
        tmp_path,
        [{"original": "tower", "rus": "башня"}, {"original": "river", "rus": "река"}],
    )
    _bump_mtime(glossary_path)

    second = assembly.load_project_glossary_terms(project.project_folder)
    assert {term.original for term in second} == {"tower", "river"}


def test_epub_cache_invalidates_when_the_file_changes(tmp_path):
    """Правка EPUB посреди сессии обязана быть видна следующей главе.

    Ветка инвалидации архива (сравнение отпечатка, archive.close(), del из
    кэша) сложнее глоссарной и раньше не была закреплена тестом.
    """
    chapter_path = "OEBPS/c1.xhtml"
    epub_path = _write_epub(tmp_path, (chapter_path,), text=_SOURCE_HTML)

    event = _events(tmp_path, epub_path, (chapter_path,))[0]

    first = assembly._read_source_chapter(event)
    assert first == _SOURCE_HTML
    assert len(assembly._EPUB_ARCHIVE_CACHE) == 1

    other_html = "<p>Другое содержимое главы после правки EPUB.</p>"
    _write_epub(tmp_path, (chapter_path,), text=other_html)
    _bump_mtime(epub_path)

    second = assembly._read_source_chapter(event)
    assert second == other_html, "инвалидация по изменённому EPUB не сработала"
    assert len(assembly._EPUB_ARCHIVE_CACHE) == 1


def test_cache_holds_only_one_book_and_closes_the_previous_handle(tmp_path):
    """Кэш не должен бессрочно копить дескрипторы прочитанных книг.

    До правки вытеснение по пути происходило только при смене отпечатка
    ТОГО ЖЕ пути: архивы разных книг, к которым больше не обращаются,
    оставались открытыми до конца жизни процесса (на Windows это мешало бы
    приложению перезаписать/удалить исходный EPUB). Кэш должен держать не
    больше одной книги и явно закрывать прежний дескриптор при переходе на
    другую.
    """
    chapter_path = "OEBPS/c1.xhtml"
    book_a = _write_epub(tmp_path, (chapter_path,), name="a.epub")
    book_b = _write_epub(tmp_path, (chapter_path,), name="b.epub")
    book_c = _write_epub(tmp_path, (chapter_path,), name="c.epub")

    event_a = _events(tmp_path, book_a, (chapter_path,))[0]
    event_b = _events(tmp_path, book_b, (chapter_path,))[0]
    event_c = _events(tmp_path, book_c, (chapter_path,))[0]

    assert assembly._read_source_chapter(event_a) == _SOURCE_HTML
    entry_a = assembly._EPUB_ARCHIVE_CACHE[str(book_a)]
    assert not entry_a.archive.fp.closed

    assert assembly._read_source_chapter(event_b) == _SOURCE_HTML
    assert str(book_a) not in assembly._EPUB_ARCHIVE_CACHE, (
        "запись прежней книги должна быть вытеснена при переходе на другую"
    )
    assert entry_a.archive.fp is None or entry_a.archive.fp.closed, (
        "дескриптор прежней книги должен закрываться сразу, а не висеть "
        "до конца жизни процесса"
    )
    assert len(assembly._EPUB_ARCHIVE_CACHE) == 1

    assert assembly._read_source_chapter(event_c) == _SOURCE_HTML
    assert len(assembly._EPUB_ARCHIVE_CACHE) == 1, (
        "кэш не должен расти вместе с числом разных прочитанных книг"
    )


def test_close_cached_source_archives_closes_and_clears_the_cache(tmp_path):
    """close_cached_source_archives() обязана закрыть дескриптор и кэш."""
    chapter_path = "OEBPS/c1.xhtml"
    epub_path = _write_epub(tmp_path, (chapter_path,))
    event = _events(tmp_path, epub_path, (chapter_path,))[0]

    assert assembly._read_source_chapter(event) == _SOURCE_HTML
    entry = assembly._EPUB_ARCHIVE_CACHE[str(epub_path)]

    assembly.close_cached_source_archives()

    assert assembly._EPUB_ARCHIVE_CACHE == {}
    assert entry.archive.fp is None or entry.archive.fp.closed


def test_invalidation_waits_for_an_in_flight_read_instead_of_racing(tmp_path):
    """Инвалидация того же пути не должна гоняться с идущим archive.read().

    Раньше открытие архива отпускало общий лок перед чтением: другой поток,
    увидевший изменившийся отпечаток, мог успеть закрыть архив
    (archive.close()) между открытием и чтением, и archive.read() падал бы с
    ValueError на уже закрытом ZIP-архиве. Теперь чтение и проверка на
    устаревание держат один и тот же лок записи, поэтому закрытие ЖДЁТ
    завершения идущего чтения вместо гонки с ним.
    """
    chapter_path = "OEBPS/c1.xhtml"
    epub_path = _write_epub(tmp_path, (chapter_path,), text=_SOURCE_HTML)
    event = _events(tmp_path, epub_path, (chapter_path,))[0]

    # Прогреть кэш одной открытой записью.
    assert assembly._read_source_chapter(event) == _SOURCE_HTML
    entry = assembly._EPUB_ARCHIVE_CACHE[str(epub_path)]

    read_started = threading.Event()
    release_read = threading.Event()
    real_read = entry.archive.read

    def slow_read(name, *args, **kwargs):
        read_started.set()
        assert release_read.wait(timeout=5), "тест завис на ожидании release_read"
        return real_read(name, *args, **kwargs)

    entry.archive.read = slow_read

    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            results["value"] = assembly._read_source_chapter(event)
        except BaseException as exc:  # noqa: BLE001 - хотим увидеть саму ошибку
            errors.append(exc)

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    assert read_started.wait(timeout=5), "чтение не началось вовремя"

    # Сдвигаем mtime без изменения содержимого: отпечаток файла меняется
    # (и второй поток обязан увидеть устаревшую запись), а сами байты
    # ZIP-архива на диске остаются валидными для идущего чтения.
    _bump_mtime(epub_path)

    invalidator_done = threading.Event()

    def invalidator() -> None:
        assembly._open_source_epub_archive(str(epub_path))
        invalidator_done.set()

    invalidator_thread = threading.Thread(target=invalidator)
    invalidator_thread.start()

    # Пока читающий поток держит лок записи, инвалидатор обязан ждать, а не
    # закрывать архив прямо сейчас.
    assert not invalidator_done.wait(timeout=0.2), (
        "инвалидация не должна закрывать архив, пока идёт его чтение"
    )

    release_read.set()
    reader_thread.join(timeout=5)
    invalidator_thread.join(timeout=5)

    assert not errors, f"чтение не должно падать из-за гонки с инвалидацией: {errors}"
    assert results.get("value") == _SOURCE_HTML
