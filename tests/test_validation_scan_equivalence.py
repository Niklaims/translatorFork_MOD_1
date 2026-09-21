"""Ускоренные проверки окна валидации дают ровно то же, что прежние.

Эталоны ниже — прежние реализации дословно: посимвольный поиск лишних угловых
скобок (4 мс на главу) и отпечаток структуры четырьмя обходами дерева. Входы —
случайный HTML из тегов, комментариев, CDATA, DOCTYPE, одиночных скобок и
текста; совпадать должно всё, включая порядок и текст превью.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gemini_translator.utils import text as text_utils

FAST_SETTINGS = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_PIECES = [
    "<p>", "</p>", "<h1>", "</h1>", "<h3 class='x'>", "</h3>", "<img src='a.png'/>",
    "<a href='#n'>", "</a>", "<ul>", "<li>", "</li>", "</ul>", "<ol>", "</ol>",
    "<br/>", "<!-- note -->", "<!--", "-->", "<![CDATA[x<y]]>", "<?xml version='1.0'?>",
    "<!DOCTYPE html>", "<!doctype html>", "<", ">", "< p>", "</ p>", "<3", "a > b",
    "Глава", " текст ", "林峰", "—", "\n", "&lt;", "<span>", "</span>", "<div>", "</div>",
]


def _reference_scan(html_content, collect_limit=0):
    """Прежний _scan_stray_angle_brackets дословно."""
    if not isinstance(html_content, str) or not html_content:
        return html_content, []

    result = []
    snippets = []
    i = 0
    length = len(html_content)

    while i < length:
        char = html_content[i]

        if char == '<':
            token_end = _reference_consume(html_content, i)
            if token_end is not None:
                result.append(html_content[i:token_end])
                i = token_end
                continue

            result.append('&lt;')
            if collect_limit <= 0 or len(snippets) < collect_limit:
                snippets.append(f"<: {text_utils._angle_artifact_preview(html_content, i)}")
            i += 1
            continue

        if char == '>':
            result.append('&gt;')
            if collect_limit <= 0 or len(snippets) < collect_limit:
                snippets.append(f">: {text_utils._angle_artifact_preview(html_content, i)}")
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result), snippets


def _reference_consume(text, start):
    """Прежний _consume_valid_angle_token дословно."""
    if text.startswith('<!--', start):
        end = text.find('-->', start + 4)
        return end + 3 if end != -1 else None

    if text.startswith('<![CDATA[', start):
        end = text.find(']]>', start + 9)
        return end + 3 if end != -1 else None

    if text.startswith('<?', start):
        end = text.find('?>', start + 2)
        return end + 2 if end != -1 else None

    doctype_match = re.match(r'<!DOCTYPE\b[^>]*>', text[start:], flags=re.IGNORECASE)
    if doctype_match:
        return start + doctype_match.end()

    tag_match = text_utils.HTML_TAG_TOKEN_RE.match(text, start)
    if tag_match:
        return tag_match.end()

    return None


def _reference_fingerprint(soup):
    """Прежний _create_structural_fingerprint дословно."""
    fp = {
        'headings': {},
        'images': len(soup.find_all('img')),
        'links': len(soup.find_all('a')),
        'lists': len(soup.find_all(['ol', 'ul']))
    }
    for h_tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        fp['headings'][h_tag.name] = fp['headings'].get(h_tag.name, 0) + 1
    return fp


_html = st.lists(st.sampled_from(_PIECES), max_size=60).map("".join)


@FAST_SETTINGS
@given(_html, st.integers(min_value=0, max_value=4))
def test_stray_angle_scan_matches_the_character_loop(html, limit):
    assert text_utils._scan_stray_angle_brackets(html, collect_limit=limit) == _reference_scan(html, limit)


@FAST_SETTINGS
@given(_html)
def test_structural_fingerprint_matches_four_find_alls(html):
    soup = BeautifulSoup(f"<html><body>{html}</body></html>", "html.parser")
    fingerprint = text_utils._create_structural_fingerprint(soup)

    assert fingerprint == _reference_fingerprint(soup)
    assert list(fingerprint["headings"]) == list(_reference_fingerprint(soup)["headings"])
