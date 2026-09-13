"""core-b/bugs/4-chapter-output-write-not-atomi.

``ResponseParser.process_and_save_single_file`` писал переведённую главу
через голый ``open(output_path, "w").write(...)`` — без temp-файла и
``os.replace``. При падении процесса/питания посреди записи (реалистично
для многочасовой сессии перевода книги) файл главы на диске остаётся
усечённым/повреждённым.

Тест по образцу маршрутизации в tests/test_dedup_cluster_43_atomic_write.py:
подменяет ``atomic_write_text`` в пространстве имён ``response_parser`` и
проверяет, что запись главы действительно идёт через каноническую
атомарную запись (gemini_translator.utils.io_utils.atomic_write_text), а
не через прямой ``open()``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gemini_translator.core.worker_helpers import response_parser as response_parser_module
from gemini_translator.core.worker_helpers.response_parser import ResponseParser
from gemini_translator.utils.text import process_body_tag


def _build_parser():
    return ResponseParser(
        worker=SimpleNamespace(use_prettify=False),
        log_callback=lambda _message: None,
    )


def _sample_parts():
    original = (
        '<html><head><title>Chapter</title></head>'
        '<body class="chapter"><h1>Chapter</h1><p>Source.</p></body>'
        '</html>'
    )
    prefix, _, suffix = process_body_tag(original, return_parts=True, body_content_only=False)
    translated = '<body class="chapter"><h1>Glava</h1><p>Translated.</p></body>'
    return original, prefix, suffix, translated


def test_process_and_save_single_file_routes_through_canonical_atomic_write(tmp_path, monkeypatch):
    """Запись главы обязана идти через io_utils.atomic_write_text, а не open()."""
    original, prefix, suffix, translated = _sample_parts()
    output_path = tmp_path / "chapter_translated.html"

    calls = []
    real_atomic_write_text = response_parser_module.__dict__.get("atomic_write_text")

    def spying_atomic_write_text(path, text, **kwargs):
        calls.append((Path(path), text))
        # Реально пишем файл, чтобы остальной тест мог проверить содержимое.
        Path(path).write_text(text, encoding="utf-8")

    if real_atomic_write_text is None:
        pytest.fail(
            "response_parser не импортирует atomic_write_text из "
            "gemini_translator.utils.io_utils — запись главы всё ещё идёт "
            "через голый open(path, 'w')."
        )

    monkeypatch.setattr(response_parser_module, "atomic_write_text", spying_atomic_write_text)

    parser = _build_parser()
    parser.process_and_save_single_file(
        translated_body_content=translated,
        original_full_content=original,
        prefix_html=prefix,
        suffix_html=suffix,
        output_path=str(output_path),
        original_internal_path="Text/chapter.xhtml",
        version_suffix="_translated.html",
    )

    assert calls, (
        "process_and_save_single_file обязан сохранять главу через "
        "atomic_write_text (temp-файл + os.replace), а не через прямой open()"
    )
    written_path, written_text = calls[0]
    assert written_path == output_path
    assert '<h1>Glava</h1><p>Translated.</p>' in written_text
    assert output_path.read_text(encoding="utf-8") == written_text


def test_process_and_save_single_file_leaves_no_temp_file_on_disk(tmp_path):
    """После успешной записи в директории не должно оставаться temp-артефактов."""
    original, prefix, suffix, translated = _sample_parts()
    output_path = tmp_path / "chapter_translated.html"

    parser = _build_parser()
    parser.process_and_save_single_file(
        translated_body_content=translated,
        original_full_content=original,
        prefix_html=prefix,
        suffix_html=suffix,
        output_path=str(output_path),
        original_internal_path="Text/chapter.xhtml",
        version_suffix="_translated.html",
    )

    leftovers = [p for p in tmp_path.iterdir() if p.name != output_path.name]
    assert leftovers == [], f"остались временные файлы: {leftovers}"


def test_process_and_save_single_file_does_not_truncate_existing_file_on_write_failure(tmp_path, monkeypatch):
    """При сбое ФС во время записи существующий файл главы не должен усекаться."""
    original, prefix, suffix, translated = _sample_parts()
    output_path = tmp_path / "chapter_translated.html"
    output_path.write_text("СТАРЫЙ ПЕРЕВОД", encoding="utf-8")

    def failing_replace(*_args, **_kwargs):
        raise OSError("симулированный сбой ФС посреди замены файла")

    monkeypatch.setattr(response_parser_module.os, "replace", failing_replace)

    parser = _build_parser()
    with pytest.raises(OSError):
        parser.process_and_save_single_file(
            translated_body_content=translated,
            original_full_content=original,
            prefix_html=prefix,
            suffix_html=suffix,
            output_path=str(output_path),
            original_internal_path="Text/chapter.xhtml",
            version_suffix="_translated.html",
        )

    # Старое содержимое должно остаться нетронутым — атомарная запись не
    # тронула итоговый файл, пока не был готов полный новый вариант.
    assert output_path.read_text(encoding="utf-8") == "СТАРЫЙ ПЕРЕВОД"
