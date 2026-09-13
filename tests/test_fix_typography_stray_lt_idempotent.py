"""Регрессия к свойству идемпотентности initial_cleanup (hypothesis нашёл
контрпример в полном прогоне 2026-09-13).

Непарный «<» внутри абзаца до этого маскировался как начало тега вплоть до
ближайшего «>», то есть до закрывающего </p>: пунктуационные правила не
видели текст «?Ё», и пробел после «?» появлялся только со второго прохода,
когда перенос строки уже разбил абзац надвое и «<» остался один.
"""

from __future__ import annotations

from gemini_translator.utils import text as text_utils


def test_stray_lt_does_not_hide_following_text_from_punctuation_rules():
    once = text_utils.initial_cleanup("<p><\n?Ё</p>")
    twice = text_utils.initial_cleanup(once)
    assert twice == once
    assert "? Ё" in once  # правило пробела после «?» сработало с первого прохода


def test_real_tags_are_still_masked():
    # Настоящие теги (с атрибутами, закрывающие, комментарии) по-прежнему не
    # трогаются пунктуационными правилами.
    src = '<p class="x">Слово<!-- ?Ё --><em>?Ё</em></p>'
    once = text_utils.initial_cleanup(src)
    assert '<p class="x">' in once and "<!-- ?Ё -->" in once
    assert "<em>? Ё</em>" in once
