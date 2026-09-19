"""Свойства частотного анализа глоссария.

Пользователь чистит глоссарий так: удаляет всё, что встретилось в книге не
больше одного раза, и запускает анализ снова. Раньше второй проход находил
новых «редких»: длинный термин забирал кусок текста, а его счёт потом
прибавлялся всем терминам, которые содержатся в нём как строка. Счёт термина
зависел от соседей по глоссарию, и удаление одних меняло счёт других.

Главное свойство: счёт термина такой же, как если бы он был в глоссарии один.
Из него следует, что удаление любых терминов не меняет счёт оставшихся и
одного прохода достаточно. Два эталона ниже проверяют сам счёт: для
иероглифов — обычный `str.count` по тексту без знаков препинания, для слов —
регулярное выражение с границами слов.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gemini_translator.utils.term_frequency_tools import calculate_term_frequency_payload

# 峰/峯 и 龍/龙 — пары упрощённого и традиционного письма: термин обязан
# находиться в любом из них.
_HANZI = "林峰峯主王龍龙大"
_CJK_PUNCTUATION = ["《", "》", "·", "，", "。", " "]
_WORDS = ["li", "lin", "feng", "dragon", "king", "kings", "sect", "master", "a", "b"]
_ALPHA_SEPARATORS = [" ", " ", "-", "'s ", ". ", ", ", " [", "] "]

FAST_SETTINGS = settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


def _frequency_stats(glossary_terms, chapters):
    """{термин: (вхождений, главы)} по временной EPUB из глав-абзацев.

    Объявление кодировки обязательно, как в настоящих главах EPUB: без него
    UnicodeDammit на коротком тексте из одних «《》» угадывает windows-1251."""
    with tempfile.TemporaryDirectory() as temp_dir:
        epub_path = Path(temp_dir) / "book.epub"
        with zipfile.ZipFile(epub_path, "w") as epub:
            for index, text in enumerate(chapters, start=1):
                epub.writestr(
                    f"OEBPS/ch{index}.xhtml",
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    f"<html><body><p>{text}</p></body></html>",
                )
        payload = calculate_term_frequency_payload(epub_path, list(glossary_terms))
    return {
        term: (stats["count"], tuple(stats["files"]))
        for term, stats in payload["terms"].items()
    }


def _random_case(draw, word):
    return draw(st.sampled_from([word, word.capitalize(), word.upper()]))


@st.composite
def cjk_terms(draw):
    core = draw(st.text(alphabet=_HANZI, min_size=1, max_size=4))
    wrapper = draw(st.sampled_from(["{}", "《{}》", "“{}”"]))
    if len(core) > 1 and draw(st.booleans()):
        cut = draw(st.integers(min_value=1, max_value=len(core) - 1))
        core = core[:cut] + "·" + core[cut:]
    return wrapper.format(core)


@st.composite
def alpha_terms(draw):
    words = [_random_case(draw, draw(st.sampled_from(_WORDS))) for _ in range(draw(st.integers(1, 2)))]
    term = draw(st.sampled_from([" ", "-"])).join(words)
    return draw(st.sampled_from(["{}", "[{}]"])).format(term)


@st.composite
def chapter_texts(draw):
    parts = []
    for _ in range(draw(st.integers(min_value=1, max_value=12))):
        if draw(st.booleans()):
            parts.append(draw(st.text(alphabet=_HANZI, min_size=1, max_size=6)))
            parts.append(draw(st.sampled_from(_CJK_PUNCTUATION)))
        else:
            parts.append(_random_case(draw, draw(st.sampled_from(_WORDS))))
            parts.append(draw(st.sampled_from(_ALPHA_SEPARATORS)))
    return "".join(parts)


@st.composite
def books(draw):
    glossary = draw(st.lists(st.one_of(cjk_terms(), alpha_terms()), min_size=1, max_size=8, unique=True))
    chapters = draw(st.lists(chapter_texts(), min_size=1, max_size=3))
    return glossary, chapters


@FAST_SETTINGS
@given(book=books())
def test_term_count_does_not_depend_on_other_glossary_terms(book):
    glossary, chapters = book

    together = _frequency_stats(glossary, chapters)

    for term, stats in together.items():
        assert _frequency_stats([term], chapters)[term] == stats, term


@FAST_SETTINGS
@given(
    term=st.text(alphabet="林主王大", min_size=1, max_size=3),
    chapters=st.lists(
        st.text(alphabet=list("林主王大") + ["，", "《", "》", " "], min_size=0, max_size=40),
        min_size=1,
        max_size=3,
    ),
)
def test_cjk_count_equals_plain_substring_count(term, chapters):
    # Эталон: сколько раз термин стоит в тексте без знаков препинания, без
    # перекрытий — ровно то, что делает str.count.
    expected = sum(re.sub(r"\W+", "", chapter).count(term) for chapter in chapters)

    assert _frequency_stats([term], chapters)[term][0] == expected


@FAST_SETTINGS
@given(
    term=st.sampled_from(["a", "b", "ab", "ba", "a b", "a-b", "[a", "b]", "[ab]", "a.", "ab's"]),
    chapters=st.lists(
        st.text(alphabet=["a", "b", "A", "B", "x", "1", "_", " ", "-", "[", "]", ".", "'", "s"], max_size=40),
        min_size=1,
        max_size=3,
    ),
)
def test_alpha_count_equals_whole_word_regex_count(term, chapters):
    # Эталон: без учёта регистра, пробелы схлопнуты, а буква/цифра/_ на краю
    # термина не может стоять вплотную к такой же в тексте. Слова короче трёх
    # букв без форм множественного числа, так что считается ровно термин.
    left = r"(?<![a-z0-9_])" if re.match(r"\w", term) else ""
    right = r"(?![a-z0-9_])" if re.search(r"\w$", term) else ""
    pattern = re.compile(left + re.escape(term.lower()) + right)
    expected = sum(
        len(pattern.findall(re.sub(r"\s+", " ", chapter).lower()))
        for chapter in chapters
    )

    assert _frequency_stats([term], chapters)[term][0] == expected
