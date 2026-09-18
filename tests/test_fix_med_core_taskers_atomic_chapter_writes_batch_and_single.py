"""core-b/bugs/4-chapter-output-write-not-atomi (остаток после волны 2).

``ResponseParser.process_and_save_single_file`` уже пишет главу через
``atomic_write_text`` (см. tests/test_fix_med_core_worker_helpers_response_parser_atomic_chapter_write.py).
Остались два самостоятельных места, которые всё ещё пишут переведённую/
скопированную главу напрямую через ``open(out_path, "w").write(...)``:

- ``EpubBatchProcessor._save_successful_chapters`` (пакетный перевод);
- ``EpubSingleFileProcessor._copy_original_as_result`` (копирование
  оригинала для пустых/не требующих перевода глав).

При падении процесса/питания посреди записи файл главы остаётся усечённым.
Тесты проверяют, что оба места переведены на каноническую
``gemini_translator.utils.io_utils.atomic_write_text`` (temp-файл +
``os.replace``), по образцу маршрутизации в
tests/test_dedup_cluster_43_atomic_write.py.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gemini_translator.core.worker_helpers.taskers import epub_batch_processor as batch_module
from gemini_translator.core.worker_helpers.taskers import epub_single_file_processor as single_module
from gemini_translator.core.worker_helpers.taskers.epub_batch_processor import EpubBatchProcessor
from gemini_translator.core.worker_helpers.taskers.epub_single_file_processor import EpubSingleFileProcessor


def _build_batch_processor(output_folder):
    worker = SimpleNamespace(
        output_folder=str(output_folder),
        use_prettify=False,
        project_manager=None,
        task_manager=None,
        _post_event=lambda *_args, **_kwargs: None,
    )
    return EpubBatchProcessor(worker)


def _build_single_processor():
    worker = SimpleNamespace(
        project_manager=None,
        task_manager=None,
        _post_event=lambda *_args, **_kwargs: None,
    )
    return EpubSingleFileProcessor(worker)


def test_save_successful_chapters_routes_through_canonical_atomic_write(tmp_path, monkeypatch):
    """_save_successful_chapters обязан писать главу через atomic_write_text."""
    calls = []
    real_atomic_write_text = batch_module.__dict__.get("atomic_write_text")

    if real_atomic_write_text is None:
        pytest.fail(
            "epub_batch_processor не импортирует atomic_write_text из "
            "gemini_translator.utils.io_utils — запись главы всё ещё идёт "
            "через голый open(path, 'w')."
        )

    def spying_atomic_write_text(path, text, **kwargs):
        calls.append((Path(path), text))
        Path(path).write_text(text, encoding="utf-8")

    monkeypatch.setattr(batch_module, "atomic_write_text", spying_atomic_write_text)

    processor = _build_batch_processor(tmp_path)
    successful_paths, save_failed_paths = processor._save_successful_chapters(
        successful_chapters_data=[
            {"original_path": "Text/chapter1.xhtml", "final_html": "<p>Glava 1</p>"},
        ],
        file_suffix="_translated.html",
        log_prefix="TEST",
    )

    assert save_failed_paths == []
    assert successful_paths == ["Text/chapter1.xhtml"]
    assert calls, (
        "_save_successful_chapters обязан сохранять главу через "
        "atomic_write_text (temp-файл + os.replace), а не через прямой open()"
    )
    written_path, written_text = calls[0]
    assert written_text == "<p>Glava 1</p>"
    assert written_path.read_text(encoding="utf-8") == "<p>Glava 1</p>"


def test_save_successful_chapters_does_not_truncate_existing_file_on_write_failure(tmp_path, monkeypatch):
    """При сбое ФС во время замены существующий файл главы не усекается."""
    from gemini_translator.utils.translated_paths import build_translated_output_path

    out_path = build_translated_output_path(str(tmp_path), "Text/chapter1.xhtml", "_translated.html")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("СТАРЫЙ ПЕРЕВОД", encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("симулированный сбой ФС посреди замены файла")

    monkeypatch.setattr(batch_module.os, "replace", failing_replace)

    processor = _build_batch_processor(tmp_path)
    successful_paths, save_failed_paths = processor._save_successful_chapters(
        successful_chapters_data=[
            {"original_path": "Text/chapter1.xhtml", "final_html": "<p>Novy perevod</p>"},
        ],
        file_suffix="_translated.html",
        log_prefix="TEST",
    )

    assert successful_paths == []
    assert save_failed_paths == ["Text/chapter1.xhtml"]
    assert Path(out_path).read_text(encoding="utf-8") == "СТАРЫЙ ПЕРЕВОД"


def test_copy_original_as_result_routes_through_canonical_atomic_write(tmp_path, monkeypatch):
    """_copy_original_as_result обязан писать через atomic_write_text."""
    calls = []
    real_atomic_write_text = single_module.__dict__.get("atomic_write_text")

    if real_atomic_write_text is None:
        pytest.fail(
            "epub_single_file_processor не импортирует atomic_write_text из "
            "gemini_translator.utils.io_utils — запись главы всё ещё идёт "
            "через голый open(path, 'w')."
        )

    def spying_atomic_write_text(path, text, **kwargs):
        calls.append((Path(path), text))
        Path(path).write_text(text, encoding="utf-8")

    monkeypatch.setattr(single_module, "atomic_write_text", spying_atomic_write_text)

    processor = _build_single_processor()
    out_path = tmp_path / "chapter_translated.html"
    processor._copy_original_as_result(
        str(out_path),
        "<html><body>Original</body></html>",
        "Text/chapter1.xhtml",
        "_translated.html",
    )

    assert calls, (
        "_copy_original_as_result обязан сохранять главу через "
        "atomic_write_text (temp-файл + os.replace), а не через прямой open()"
    )
    written_path, written_text = calls[0]
    assert written_path == out_path
    assert written_text == "<html><body>Original</body></html>"
    assert out_path.read_text(encoding="utf-8") == written_text


def test_copy_original_as_result_does_not_truncate_existing_file_on_write_failure(tmp_path, monkeypatch):
    """При сбое ФС во время замены существующая копия оригинала не усекается."""
    out_path = tmp_path / "chapter_translated.html"
    out_path.write_text("СТАРАЯ КОПИЯ", encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("симулированный сбой ФС посреди замены файла")

    monkeypatch.setattr(single_module.os, "replace", failing_replace)

    processor = _build_single_processor()
    with pytest.raises(OSError):
        processor._copy_original_as_result(
            str(out_path),
            "<html><body>Novy original</body></html>",
            "Text/chapter1.xhtml",
            "_translated.html",
        )

    assert out_path.read_text(encoding="utf-8") == "СТАРАЯ КОПИЯ"
