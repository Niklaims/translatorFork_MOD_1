"""Пробелы внутри кавычек убираются.

Жалоба 17.09.2026: во внутренних кавычках часто остаётся лишний пробел —
«„текст “». Обработка сохраняла пробел, который модель ставила у кавычки
(`"Привет "`), а правила, которое такие пробелы убирает, не было. В русском
тексте пробела не бывает после «„» и «„» и перед «»». Перед «“» он лишний,
только когда «“» закрывает «„»: в английских вставках «“» открывающая.
"""

from __future__ import annotations

import re

from gemini_translator.utils import text as text_utils


def _visible(html: str) -> str:
    return re.sub(r"<[^>]+>", "", text_utils.prettify_html(html))


# Точку в конце абзаца MISSING_DOT_PATTERN ставит перед закрывающими кавычками
# («„Привет.“»); где ей место — отдельный вопрос, здесь проверяются пробелы.
def test_space_before_inner_closing_quote_is_removed():
    out = _visible('<p>«Он сказал: "Привет "»</p>')
    assert " “" not in out, out
    assert re.search(r"„Привет\.?“»", out), out


def test_space_after_inner_opening_quote_is_removed():
    out = _visible('<p>«Он сказал: " Привет"»</p>')
    assert "„ " not in out, out
    assert "„Привет" in out, out


def test_space_before_outer_closing_quote_is_removed():
    out = _visible("<p>«Его звали «Тень» »</p>")
    assert " »" not in out, out
    assert re.search(r"„Тень\.?“»$", out), out


def test_space_between_outer_and_inner_opening_quotes_is_removed():
    out = _visible("<p>« „Звёздный экспресс“ прибыл», — сказал он.</p>")
    assert "«„Звёздный экспресс“" in out, out


def test_space_inside_inline_tag_before_closing_quote_is_removed_and_tag_kept():
    html = text_utils.prettify_html("<p>«Он сказал: „<em>Привет </em>“»</p>")
    assert "<em>" in html and "</em>" in html, html
    assert re.search(r"„Привет\.?“»", re.sub(r"<[^>]+>", "", html)), html


def test_space_before_an_opening_quote_is_kept():
    out = _visible("<p>Он написал “hello” на стене.</p>")
    assert re.search(r"написал [«“]hello[»”] на", out), out
    # Сама финальная чистка видит «“» открывающей, если «„» перед ней нет.
    finalized = text_utils.finalize_cleanup("<p>Он написал “hello” на стене.</p>")
    assert "написал “hello” на" in finalized, finalized


def test_quote_spacing_never_crosses_a_paragraph_boundary():
    html = text_utils.prettify_html("<p>«Первый абзац</p><p> » второй абзац.</p>")
    assert html.count("</p>") == 2, html
