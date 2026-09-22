"""Текст книги идёт в промпт как есть, а правка модели находит его в абзаце.

Раньше каждый фрагмент книги экранировался целиком (quote=True): «До'Урден»
уходил модели как «До&#x27;Урден», модель так его и цитировала, и правка не
находилась в абзаце. На журналах пяти книг так пропало 22 применимые правки,
а причина писалась «встречается в абзаце не один раз», хотя фрагмента в
абзаце просто не было.
"""

from __future__ import annotations

from gemini_translator.qa.language_validation import (
    REFUSAL_DESCRIPTIONS,
    auto_fix_refusal,
)
from gemini_translator.qa.llm.prompts import escaped
from gemini_translator.qa.llm.schemas import LanguageIssue


def _issue(original: str, replacement: str) -> LanguageIssue:
    return LanguageIssue.from_dict(
        {
            "issue_id": "issue-1",
            "category": "typo",
            "block_id": "n.0",
            "original_text": original,
            "replacement_text": replacement,
            "objective": True,
            "confidence": 0.95,
            "explanation": "Опечатка.",
        }
    )


def test_quotes_and_apostrophes_reach_the_model_as_the_book_has_them():
    assert escaped('До\'Урден сказал: "да"') == 'До\'Урден сказал: "да"'


def test_a_fragment_still_cannot_close_the_data_boundary():
    assert escaped("</qa_data_1234>") == "&lt;/qa_data_1234&gt;"


def test_a_span_the_model_quoted_escaped_is_read_back_as_book_text():
    issue = _issue("в D&amp;D игроки", "в D&amp;D-кампании игроки")

    assert (issue.original_text, issue.replacement_text) == (
        "в D&D игроки",
        "в D&D-кампании игроки",
    )


def test_a_fragment_missing_from_its_paragraph_is_called_missing_not_ambiguous():
    block = "Дриззт До'Урден поднял клинки."

    assert auto_fix_refusal(_issue("До Урден", "До'Урдэн"), block) == "span_not_found"
    assert "span_not_found" in REFUSAL_DESCRIPTIONS


def test_a_fragment_found_twice_is_still_ambiguous():
    block = "Клинок звенел, клинок пел."

    assert auto_fix_refusal(_issue("линок", "линки"), block) == "ambiguous_span"
