"""Какой абзац оригинала проверка видит рядом с абзацем перевода."""

from __future__ import annotations

from gemini_translator.qa.source_pairing import pair_source_text, payload_block_texts
from gemini_translator.utils.epub_json import (
    build_html_document_model,
    build_translation_payload,
)


# Разметка как в «Клинке Фаэруна»: оригинал — голый текст между <br />,
# перевод — абзацы <p>. Номера узлов DOM у них идут с разным шагом.
_SOURCE_ON_BR = """<html><body><h1>第6章 练功</h1>

      　　第6章 练功
     <br />
      　　刚才拔出木矛的时候没有注意。
     <br />
     <br />
      　　他低头仔细一看。
     <br />
</body></html>"""

_TARGET_ON_P = """<html><body>
<h1>Глава 6: «Тренировки»</h1>

<p>Глава 6. Тренировки.</p>

<p>Когда он выдёргивал копьё, то не обратил внимания.</p>

<p>Он опустил голову и присмотрелся.</p>
</body></html>"""


def _blocks(html: str, document_id: str) -> list[tuple[str, str]]:
    model = build_html_document_model(html, document_id=document_id)
    return payload_block_texts(build_translation_payload(model, document_id=document_id))


def test_each_translated_paragraph_gets_its_own_source_when_the_markup_differs():
    target = _blocks(_TARGET_ON_P, "chapter")

    pairs = pair_source_text(_blocks(_SOURCE_ON_BR, "source::chapter"), target)

    assert [pairs.get(block_id) for block_id, _ in target] == [
        "第6章 练功",
        "第6章 练功",
        "刚才拔出木矛的时候没有注意。",
        "他低头仔细一看。",
    ]


_LONG_SOURCE = (
    "The caravan had crossed the river at dawn, and by noon the scouts reported "
    "smoke on the horizon, thin and grey, rising from a village that was not on "
    "any of the maps the merchants had bought in Waterdeep for a small fortune."
)


def test_a_paragraph_split_in_two_keeps_its_whole_source_for_both_halves():
    source = [
        ("s0", "He opened the door."),
        ("s1", _LONG_SOURCE),
        ("s2", "Then he left."),
    ]
    target = [
        ("t0", "Он открыл дверь."),
        ("t1", "Караван переправился через реку на рассвете, а к полудню разведчики донесли о дыме на горизонте."),
        ("t2", "Тонкий и серый, он поднимался над деревней, которой не было ни на одной из карт, купленных купцами в Глубоководье за целое состояние."),
        ("t3", "Потом он ушёл."),
    ]

    pairs = pair_source_text(source, target)

    assert pairs == {
        "t0": "He opened the door.",
        "t1": _LONG_SOURCE,
        "t2": _LONG_SOURCE,
        "t3": "Then he left.",
    }


def test_two_source_paragraphs_merged_in_translation_are_shown_together():
    source = [
        ("s0", "He opened the door."),
        ("s1", "The caravan had crossed the river at dawn."),
        ("s2", "By noon the scouts reported smoke on the horizon."),
        ("s3", "Then he left."),
    ]
    target = [
        ("t0", "Он открыл дверь."),
        ("t1", "Караван переправился через реку на рассвете, а к полудню разведчики донесли о дыме на горизонте."),
        ("t2", "Потом он ушёл."),
    ]

    pairs = pair_source_text(source, target)

    assert pairs == {
        "t0": "He opened the door.",
        "t1": "The caravan had crossed the river at dawn. By noon the scouts reported smoke on the horizon.",
        "t2": "Then he left.",
    }


def test_blank_blocks_take_no_part_in_pairing():
    source = [("s0", "  \n "), ("s1", "He opened the door."), ("s2", "Then he left.")]
    target = [("t0", "Он открыл дверь."), ("t1", "　"), ("t2", "Потом он ушёл.")]

    pairs = pair_source_text(source, target)

    assert pairs == {"t0": "He opened the door.", "t2": "Then he left."}


def test_without_source_or_translation_nothing_is_paired():
    assert pair_source_text([], [("t0", "Он открыл дверь.")]) == {}
    assert pair_source_text([("s0", "He opened the door.")], []) == {}
