"""Типографика не должна сочинять многоточия.

Читатель принимал лишние «…» за привычку авторов, а ставила их программа.
Тире оборванной реплики, тире перед кавычкой или знаком препинания, запятая
в конце абзаца, разрез абзаца по <br> и слова автора внутри кавычек
превращались в «…» — и до отправки модели, и после её ответа.

Правило теперь одно: многоточие в выходе бывает только там, где во входе уже
были точки или «…». Примеры взяты из сырых ответов модели в отладочных
журналах книги Ignited_Spark (17.09.2026).
"""

from __future__ import annotations

import re

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from gemini_translator.utils import text as text_utils

# Функции, через которые проходит текст главы: подготовка оригинала для модели
# и обработка её ответа (prettify_html зовёт refine_typography_in_html и
# finalize_cleanup, но они проверяются и по отдельности).
PIPELINE_TRANSFORMS = [
    "prettify_html_for_ai",
    "prettify_html",
    "refine_typography_in_html",
    "finalize_cleanup",
]

_ELLIPSIS_LIKE = re.compile(r"…|\.{2,}")

# Плотный алфавит: тире, кавычки, запятые, точки и немного букв — именно то,
# на что срабатывали правила с многоточиями.
_DENSE_TEXT = st.text(alphabet="«»–—─-.,!? …абвНетZx\n", max_size=40)
_TAGS = st.sampled_from(["p", "em", "div", "blockquote"])


@st.composite
def dense_fragment(draw):
    blocks = draw(st.lists(st.tuples(_TAGS, _DENSE_TEXT), max_size=5))
    html = "".join(f"<{tag}>{body}</{tag}>" for tag, body in blocks)
    if draw(st.booleans()):
        html = html.replace("\n", "<br/>")
    return html


@pytest.mark.parametrize("name", PIPELINE_TRANSFORMS)
def test_transform_never_invents_an_ellipsis(name):
    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(value=dense_fragment())
    @example(value="<p>«Вытащи его оттуда! ─ закричал он себе. ─ Спаси его!»</p>")
    @example(value="<p>─ Ну, по крайней мере дышу –</p><p>─ Понимаю.</p>")
    @example(value="<p>Она п̵о̴р̷а̴н̶и̵л̶а̸с̶ь̵-»</p>")
    @example(value="<p>кувыркаясь в воздухе,</p><p>а сам Денки шмякнулся.</p>")
    @example(value="<p>«─ Тойя просто дурачится, Шото!»</p>")
    @example(value="<p>第一行<br/>第二行</p>")
    @example(value="<p>啊啊啊——</p>")
    def check(value):
        result = getattr(text_utils, name)(value)
        allowed = len(_ELLIPSIS_LIKE.findall(value))
        produced = result.count("…")
        assert produced <= allowed, (
            f"{name} сочинил многоточие: во входе {allowed}, в выходе {produced}\n"
            f"вход:  {value!r}\nвыход: {result!r}"
        )

    check()


def _visible(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def test_author_words_inside_quotes_keep_their_dashes():
    out = _visible(text_utils.prettify_html(
        "<p>«Вытащи его оттуда! ─ закричал он себе. ─ Спаси его!»</p>"
    ))
    assert "…" not in out, out
    assert re.search(r"оттуда! [–—] закричал он себе\. [–—] Спаси", out), out


def test_interrupted_reply_keeps_its_dash():
    out = _visible(text_utils.prettify_html(
        "<p>─ Ну, по крайней мере дышу –</p><p>─ Понимаю.</p>"
    ))
    assert "…" not in out, out
    assert re.search(r"дышу\s*[–—-]", out), out


def test_hyphen_attached_to_word_before_comma_survives():
    out = _visible(text_utils.prettify_html(
        "<p>Другие уничтожают одно-, двух- и трех-очковых роботов.</p>"
    ))
    assert "…" not in out, out
    assert "одно-," in out, out


def test_dash_before_closing_quote_stays_a_dash():
    out = _visible(text_utils.prettify_html("<p>«Она поранилась-»</p>"))
    assert "…" not in out, out
    assert re.search(r"поранилась\s*[–—-]\s*»", out), out


def test_comma_at_paragraph_end_is_not_turned_into_ellipsis():
    out = _visible(text_utils.prettify_html(
        "<p>Он выронил Денки, беспорядочно кувыркаясь в воздухе,</p>"
    ))
    assert "…" not in out, out
    assert "воздухе," in out, out


def test_dash_right_after_opening_quote_is_dropped_not_turned_into_ellipsis():
    out = _visible(text_utils.prettify_html("<p>«─ Тойя просто дурачится, Шото!»</p>"))
    assert "…" not in out, out
    assert "«Тойя просто дурачится" in out, out


def test_source_split_by_br_gets_no_ellipsis_markers():
    out = text_utils.prettify_html_for_ai("<p>第一行<br/>第二行</p>")
    assert "…" not in out, out
    assert "第一行" in out and "第二行" in out, out


def test_source_dash_at_paragraph_end_reaches_the_model_as_a_dash():
    out = text_utils.prettify_html_for_ai("<p>啊啊啊——</p>")
    assert "…" not in out, out
    assert "啊啊啊——" in out, out
