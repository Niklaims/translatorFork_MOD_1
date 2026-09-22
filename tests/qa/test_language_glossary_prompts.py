"""Языковая проверка видит канонические термины своих абзацев, и только их.

Раньше глоссарий в языковую проверку не передавался вовсе: в промпте стояло
«none supplied», а порог glossary_term_dropped не срабатывал ни разу. В книги
попали «Куэнтин → Квентин» и «Пиэм → Пим».
"""

from __future__ import annotations

import asyncio

from gemini_translator.qa.language_validation import LanguageBlock, LanguageQaRequest
from gemini_translator.qa.llm import CancellationToken, QaModelSelection
from gemini_translator.qa.llm.language_repairer import LanguageBatchRepairer
from gemini_translator.qa.llm.language_reviewer import LanguageQualityReviewer
from gemini_translator.qa.llm.schemas import LanguageIssue
from gemini_translator.qa.models import GlossaryPolicy, RelevantGlossaryTerm
from gemini_translator.utils.epub_json import (
    build_html_document_model,
    build_translation_payload,
)


class _Client:
    def __init__(self, answer) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def complete_json(self, prompt, *, model, max_output_tokens, cancellation, purpose=""):
        self.prompts.append(prompt)
        return self.answer


def _request_and_blocks():
    model = build_html_document_model(
        "<p>Куэнтин вошёл в комнату.</p><p>Он обнажил меч.</p>", document_id="chapter-1"
    )
    ids = [block["id"] for block in build_translation_payload(model)["blocks"]]
    request = LanguageQaRequest(
        chapter_id="chapter-1",
        document_model=model,
        source_language="zh",
        target_language="ru",
        model=QaModelSelection("gemini", "qa-model"),
        cancellation=CancellationToken(),
        source_text_by_block={ids[0]: "昆汀走进了房间。", ids[1]: "他拔出了剑。"},
        glossary=(
            RelevantGlossaryTerm("昆汀", "Куэнтин", GlossaryPolicy.MUST_TRANSLATE, 1, 0),
            RelevantGlossaryTerm("剑", "меч", GlossaryPolicy.MUST_TRANSLATE, 1, 1),
        ),
    )
    blocks = (
        LanguageBlock(ids[0], "Куэнтин вошёл в комнату."),
        LanguageBlock(ids[1], "Он обнажил меч."),
    )
    return request, blocks


def test_the_diagnosis_of_a_chunk_is_shown_the_terms_its_source_names():
    request, blocks = _request_and_blocks()
    client = _Client({"issues": []})

    asyncio.run(LanguageQualityReviewer(client).diagnose_chapter(request, blocks[:1]))

    prompt = client.prompts[0]
    assert "昆汀 → Куэнтин" in prompt
    assert "剑 → меч" not in prompt


def test_the_correction_is_shown_the_terms_of_the_paragraphs_it_edits():
    request, blocks = _request_and_blocks()
    issue = LanguageIssue(
        issue_id="issue-1",
        category="typo",
        block_id=blocks[1].block_id,
        original_text="обнажил",
        replacement_text="обнажил",
        objective=True,
        confidence=0.9,
        explanation="Проверка.",
    )
    client = _Client({"replacements": [{"issue_id": "issue-1", "replacement_text": "выхватил"}]})

    asyncio.run(LanguageBatchRepairer(client).propose_batch(request, blocks, (issue,)))

    prompt = client.prompts[0]
    assert "剑 → меч" in prompt
    assert "昆汀 → Куэнтин" not in prompt
