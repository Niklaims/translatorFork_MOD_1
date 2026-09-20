"""Типографика не должна вставать на зацикленном ответе модели.

Правило «китайского» тире ловит серию точек перед закрывающей кавычкой:
``((?:[.]|…){2,}|…)\\s*([»“"”])\\s*─``. Серия жадная, и на каждой позиции
внутри длинной череды точек движок заново проходит её до конца — время растёт
квадратично. На обычной главе это доли миллисекунды, но зацикленный ответ
модели (целая глава из точек) у проекта уже случался и уходит в перевод как
частичный: 60 КБ таких точек считались 25 секунд, 120 КБ — 101 секунду.
"""

from __future__ import annotations

import time

import pytest

from gemini_translator.utils import text as text_utils


def _degenerate_chapter(kilobytes: int) -> str:
    return "<p>Он остановился у кромки воды" + "." * (kilobytes * 1000) + "</p>"


# Щедро: до правки 60 КБ обходились в ~25 с, после — миллисекунды.
BUDGET_SECONDS = 5.0


@pytest.mark.parametrize("kilobytes", [30, 60])
def test_oper_dash_symbol_stays_quick_on_looping_model_output(kilobytes):
    chapter = _degenerate_chapter(kilobytes)

    started = time.perf_counter()
    text_utils.oper_dash_symbol(chapter)
    spent = time.perf_counter() - started

    assert spent < BUDGET_SECONDS, (
        f"{kilobytes} КБ точек обработаны за {spent:.1f} с — "
        "серия точек снова разбирается квадратично"
    )


@pytest.mark.parametrize(
    "source, expected",
    [
        ('<p>«Огонь..» ─ сказал он.</p>', '<p>«Огонь…», ─ сказал он.</p>'),
        ('<p>«Огонь...» ─ сказал он.</p>', '<p>«Огонь…», ─ сказал он.</p>'),
        ('<p>«Огонь…» ─ сказал он.</p>', '<p>«Огонь…», ─ сказал он.</p>'),
        ('<p>«Огонь….» ─ сказал он.</p>', '<p>«Огонь…», ─ сказал он.</p>'),
    ],
)
def test_dot_run_before_quote_still_collapses_to_ellipsis(source, expected):
    assert text_utils.oper_dash_symbol(source) == expected
