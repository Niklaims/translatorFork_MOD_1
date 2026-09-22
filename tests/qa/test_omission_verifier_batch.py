"""Кандидаты на пропуск одной главы проверяются одним запросом, а не каждый своим.

Замерено на «Арканном походе»: 3,8 запроса проверки пропусков на главу, и 98%
из них отвечают «не пропуск». Инструкция при этом повторялась в каждом запросе
и занимала 38% его объёма. Пачка до шести кандидатов даёт около одного
запроса на главу, а повторная проверка той же главы берёт ответ из кэша.
"""

from __future__ import annotations

import asyncio
import hashlib
import re

from gemini_translator.qa.llm import CancellationToken, OmissionVerifier, QaModelSelection
from gemini_translator.qa.llm.answer_cache import QaAnswerCache
from gemini_translator.qa.models import (
    AlignmentSpan,
    CandidateContext,
    GapCandidate,
    ProtectedEntityHint,
)


def _candidate(name: str) -> GapCandidate:
    left = AlignmentSpan((f"{name}-s0",), (f"{name}-t0",), 1.0, "1:1")
    right = AlignmentSpan((f"{name}-s2",), (f"{name}-t2",), 1.0, "1:1")
    return GapCandidate(
        candidate_id="gap-" + hashlib.sha256(name.encode()).hexdigest()[:20],
        side="source",
        source_unit_ids=(f"{name}-s1",),
        target_unit_ids=(),
        left_anchor=left,
        right_anchor=right,
        repairable=True,
        signals=("missing_in_target",),
    )


def _context(candidate: GapCandidate, **overrides) -> CandidateContext:
    values = dict(
        candidate_id=candidate.candidate_id,
        source_text=f"source gap of {candidate.candidate_id}",
        target_text="",
        source_before="left-source-anchor",
        source_after="right-source-anchor",
        target_before="left-target-anchor",
        target_after="right-target-anchor",
        source_language="en",
        target_language="ru",
        candidate_language="en",
    )
    values.update(overrides)
    return CandidateContext(**values)


def _items(count: int):
    candidates = [_candidate(f"c{index}") for index in range(count)]
    return [(candidate, _context(candidate), ()) for candidate in candidates]


class _BatchClient:
    """Answers every candidate it is shown, except those it is told to skip."""

    def __init__(self, items, *, skip=()) -> None:
        self.units = {candidate.candidate_id: candidate.source_unit_ids for candidate, _, _ in items}
        self.skip = set(skip)
        self.prompts: list[str] = []
        self.purposes: list[str] = []

    async def complete_json(self, prompt, *, model, max_output_tokens, cancellation, purpose=""):
        self.prompts.append(prompt)
        self.purposes.append(purpose)
        shown = re.findall(r"candidate_id: (gap-[0-9a-f]+)", prompt)
        return {
            "verdicts": [
                {
                    "candidate_id": candidate_id,
                    "decision": "missing_content",
                    "confidence": 0.97,
                    "source_unit_ids": list(self.units[candidate_id]),
                    "missing_facts": ["Потерян факт."],
                    "explanation": "Факта нет в переводе.",
                }
                for candidate_id in shown
                if candidate_id not in self.skip
            ]
        }


def _verify(verifier, items):
    return asyncio.run(
        verifier.verify_many(items, QaModelSelection("gemini", "qa-model"), CancellationToken())
    )


def test_the_candidates_of_a_chapter_share_one_request():
    items = _items(3)
    client = _BatchClient(items)

    results = _verify(OmissionVerifier(client), items)

    assert len(client.prompts) == 1
    assert client.purposes == ["omission_verification"]
    assert [result.candidate.candidate_id for result in results] == [
        candidate.candidate_id for candidate, _, _ in items
    ]
    assert all(result.status == "verified" and result.eligible_for_repair for result in results)


def test_more_than_six_candidates_take_another_request():
    items = _items(8)
    client = _BatchClient(items)

    _verify(OmissionVerifier(client), items)

    assert [prompt.count("candidate_id: ") for prompt in client.prompts] == [6, 2]


def test_a_candidate_the_answer_skipped_fails_closed():
    items = _items(3)
    skipped = items[1][0].candidate_id
    client = _BatchClient(items, skip={skipped})

    results = _verify(OmissionVerifier(client), items)

    by_id = {result.candidate.candidate_id: result for result in results}
    assert by_id[skipped].status == "invalid_response"
    assert by_id[skipped].eligible_for_repair is False
    assert by_id[items[0][0].candidate_id].status == "verified"


def test_a_candidate_the_foreign_text_filter_settles_costs_no_request():
    brand = _candidate("brand")
    items = [
        (
            brand,
            _context(
                brand,
                source_text="Apple",
                target_text="Apple",
                protected_entities=(ProtectedEntityHint(text="Apple", category="brand"),),
            ),
            (),
        )
    ]
    client = _BatchClient(items)

    results = _verify(OmissionVerifier(client), items)

    assert client.prompts == []
    assert results[0].status == "filtered"


def test_asking_the_same_chapter_again_is_answered_from_the_cache(tmp_path):
    items = _items(3)
    client = _BatchClient(items)
    cache = QaAnswerCache(tmp_path / "answers")

    first = _verify(OmissionVerifier(client, cache=cache), items)
    second = _verify(OmissionVerifier(client, cache=cache), items)

    assert len(client.prompts) == 1
    assert [result.verdict for result in second] == [result.verdict for result in first]
