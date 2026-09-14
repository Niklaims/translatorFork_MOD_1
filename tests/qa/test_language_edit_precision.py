"""Measured on two finished books: 45% of refusals were not judgements at all.

Mechanical normalisations (a dash respelled, the case of an attribution verb)
were sent to a validator whose prompt tells it to confirm only what is
*impossible* in Russian, and it declined them at random — «— Спросил» became
«— спросил» 50 times and was refused 5 times.  Deletions could not be expressed
at all, so every «(Конец главы)» the check found died as «нет текста замены».
These tests pin the separation that makes a refusal mean something.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from gemini_translator.qa.language_validation import (
    REFUSAL_DESCRIPTIONS,
    LanguageQaRequest,
    LanguageQaResult,
    LanguageQualityPipeline,
    auto_fix_refusal,
    drops_adjacent_duplicate,
    is_mechanical_edit,
    only_yo_differs,
)
from gemini_translator.qa.llm import CancellationToken, QaModelSelection
from gemini_translator.qa.llm.language_reviewer import is_transient
from gemini_translator.qa.llm.schemas import LanguageIssue
from gemini_translator.utils.epub_json import (
    build_html_document_model,
    build_translation_payload,
)


_CHAPTER_HTML = (
    "<p>Дианьмэнь – это ворота.</p>"
    "<p>— Ты идёшь? — Спросил доктор.</p>"
    "<p>Он первым первым делом сел. (Конец главы)</p>"
)


class _Client:
    """Answer each request stage by its purpose, recording what was asked."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.purposes: list[str] = []

    async def complete_json(
        self, prompt, *, model, max_output_tokens, cancellation, purpose=""
    ):
        self.purposes.append(purpose)
        response = self.responses.get(purpose)
        if isinstance(response, BaseException):
            raise response
        if response is None:
            raise AssertionError(f"unexpected purpose {purpose!r}")
        return deepcopy(response)


def _model() -> dict:
    return build_html_document_model(_CHAPTER_HTML, document_id="chapter-1")


def _block_ids(model: dict) -> list[str]:
    return [block["id"] for block in build_translation_payload(model)["blocks"]]


def _issue(index, block_id, original, replacement, **overrides) -> dict:
    payload = {
        "issue_id": f"issue-{index}",
        "category": "punctuation",
        "block_id": block_id,
        "original_text": original,
        "replacement_text": replacement,
        "objective": True,
        "confidence": 0.95,
        "explanation": "Дефект.",
    }
    payload.update(overrides)
    return payload


def _request(model: dict, **overrides) -> LanguageQaRequest:
    values: dict[str, object] = {
        "chapter_id": "chapter-1",
        "document_model": model,
        "source_language": "zh",
        "target_language": "ru",
        "model": QaModelSelection("gemini", "qa-model"),
        "cancellation": CancellationToken(),
        "auto_fix_categories": ("typo", "grammar", "punctuation"),
    }
    values.update(overrides)
    return LanguageQaRequest(**values)  # type: ignore[arg-type]


def _run(client: _Client, request: LanguageQaRequest) -> LanguageQaResult:
    return asyncio.run(LanguageQualityPipeline(client).check_chapter(request))


def _made(issues: list[dict]) -> dict:
    return {
        "replacements": [
            {
                "issue_id": issue["issue_id"],
                "replacement_text": issue["replacement_text"],
            }
            for issue in issues
        ]
    }


# ---------------------------------------------------------------- classifiers


@pytest.mark.parametrize(
    "original, replacement",
    [
        ("Дианьмэнь – это", "Дианьмэнь — это"),          # тире
        ("— Спросил доктор.", "— спросил доктор."),       # регистр атрибуции
        ("Эддингтон , и", "Эддингтон, и"),                # лишний пробел
        ("Главное -  результат", "Главное — результат"),  # тире и пробел разом
    ],
)
def test_a_respelling_is_mechanical_whatever_the_model_thinks(original, replacement):
    """Тире, регистр и пробелы — не мнение о языке, а написание тех же слов."""
    assert is_mechanical_edit(original, replacement) is True


@pytest.mark.parametrize(
    "original, replacement",
    [
        ("тринадцать килограмм", "тринадцать килограммов"),
        ("можно провести выводы", "можно сделать выводы"),
        ("Чэнь Муу", "Чэня Муу"),
        ("густыми щеточкой усами", "густыми щеточкой, усами"),  # знак добавлен
    ],
)
def test_a_changed_word_is_never_mechanical(original, replacement):
    """Стоит поменяться букве в слове — это уже суждение, а не написание."""
    assert is_mechanical_edit(original, replacement) is False


def test_yo_is_recognised_as_a_spelling_policy_not_a_defect():
    assert only_yo_differs("Сдается", "Сдаётся") is True
    assert only_yo_differs("черт возьми", "чёрт возьми") is True
    assert only_yo_differs("все ушли", "всё ушло") is False


def test_an_adjacent_duplicate_is_a_defect_a_rewrite_is_not():
    assert drops_adjacent_duplicate("первым первым делом", "первым делом") is True
    assert drops_adjacent_duplicate("внимательно внимал", "внимал") is False
    assert drops_adjacent_duplicate("слишком преждевременно", "слишком рано") is False


# ------------------------------------------------------------------- the gate


def _make_issue(**overrides) -> LanguageIssue:
    payload = {
        "issue_id": "i1",
        "category": "punctuation",
        "block_id": "b1",
        "original_text": "Главное – результат",
        "replacement_text": "Главное — результат",
        "objective": True,
        "confidence": 0.95,
        "explanation": "Дефект.",
    }
    payload.update(overrides)
    return LanguageIssue.from_dict(payload)


def test_a_no_op_is_named_a_no_op_and_never_a_judgement():
    """«Модель не считает правку объективной» о правке, которой нет, — ложь."""
    issue = _make_issue(
        original_text="Пекин-Мукденской",
        replacement_text="Пекин-Мукденской",
        objective=False,
    )
    assert auto_fix_refusal(issue, "Дорога Пекин-Мукденской линии.") == "no_change"


def test_a_yo_only_edit_is_refused_as_policy_before_it_costs_a_request():
    issue = _make_issue(
        category="grammar", original_text="Сдается", replacement_text="Сдаётся"
    )
    assert auto_fix_refusal(issue, "Сдается мне, он прав.") == "yo_spelling"
    assert "yo_spelling" in REFUSAL_DESCRIPTIONS


def test_a_deletion_of_a_neural_artefact_is_eligible():
    """«(Конец главы)» — не правка текста, а мусор, который надо убрать."""
    issue = _make_issue(
        category="meta_comment", original_text="(Конец главы)", replacement_text=""
    )
    assert auto_fix_refusal(issue, "Он сел. (Конец главы)") == ""


def test_a_meta_comment_that_rewrites_rather_than_removes_stays_a_suggestion():
    """Разрешено удаление, а не свободная редактура под видом удаления."""
    issue = _make_issue(
        category="meta_comment",
        original_text="(Конец главы)",
        replacement_text="Конец главы.",
    )
    assert auto_fix_refusal(issue, "Он сел. (Конец главы)") == "category_not_auto_fixable"


def test_a_doubled_word_may_be_dropped_even_though_repetition_is_blacklisted():
    issue = _make_issue(
        category="repetition",
        original_text="первым первым делом",
        replacement_text="первым делом",
    )
    assert auto_fix_refusal(issue, "Он первым первым делом сел.") == ""


def test_a_repetition_rewrite_is_still_refused():
    issue = _make_issue(
        category="repetition",
        original_text="слишком преждевременно",
        replacement_text="слишком рано",
    )
    assert (
        auto_fix_refusal(issue, "Это слишком преждевременно.")
        == "category_not_auto_fixable"
    )


# ------------------------------------------------------------------ the split


def test_mechanical_edits_are_judged_by_their_own_request():
    """Один промпт не может спрашивать и «невозможно ли это», и «то же ли это слово»."""
    model = _model()
    blocks = _block_ids(model)
    mechanical = _issue(1, blocks[0], "Дианьмэнь – это", "Дианьмэнь — это")
    judgement = _issue(
        2, blocks[2], "первым первым делом", "первым делом", category="grammar"
    )
    client = _Client(
        {
            "language_diagnosis": {"issues": [mechanical, judgement]},
            "language_batch_correction": _made([mechanical, judgement]),
            "language_mechanical_validation": {
                "confirmed_issue_ids": ["issue-1"],
                "rejected_issue_ids": [],
            },
            "language_batch_validation": {
                "confirmed_issue_ids": [],
                "rejected_issue_ids": ["issue-2"],
            },
        }
    )

    result = _run(client, _request(model))

    assert client.purposes.count("language_mechanical_validation") == 1
    assert client.purposes.count("language_batch_validation") == 1
    assert [item.issue_id for item in result.applied] == ["issue-1"]
    assert result.refusals["issue-2"] == "validation_declined"


def test_a_chunk_of_only_mechanical_edits_never_asks_the_strict_validator():
    model = _model()
    blocks = _block_ids(model)
    mechanical = _issue(1, blocks[0], "Дианьмэнь – это", "Дианьмэнь — это")
    client = _Client(
        {
            "language_diagnosis": {"issues": [mechanical]},
            "language_batch_correction": _made([mechanical]),
            "language_mechanical_validation": {
                "confirmed_issue_ids": ["issue-1"],
                "rejected_issue_ids": [],
            },
        }
    )

    result = _run(client, _request(model))

    assert "language_batch_validation" not in client.purposes
    assert [item.issue_id for item in result.applied] == ["issue-1"]


def test_a_mechanical_stage_failure_loses_only_the_mechanical_edits():
    """Сбой одного пакета не должен уносить с собой правки другого."""
    model = _model()
    blocks = _block_ids(model)
    mechanical = _issue(1, blocks[0], "Дианьмэнь – это", "Дианьмэнь — это")
    judgement = _issue(
        2, blocks[2], "первым первым делом", "первым делом", category="grammar"
    )
    client = _Client(
        {
            "language_diagnosis": {"issues": [mechanical, judgement]},
            "language_batch_correction": _made([mechanical, judgement]),
            "language_mechanical_validation": RuntimeError("отказ"),
            "language_batch_validation": {
                "confirmed_issue_ids": ["issue-2"],
                "rejected_issue_ids": [],
            },
        }
    )

    result = _run(client, _request(model))

    assert [item.issue_id for item in result.applied] == ["issue-2"]
    assert result.refusals["issue-1"] == "language_mechanical_validation_failed"
    assert "language_mechanical_validation_failed" in REFUSAL_DESCRIPTIONS


# ------------------------------------------------------------- no silent loss


def test_an_issue_the_repairer_forgot_gets_a_refusal_not_silence():
    """Правка, пропавшая между стадиями, не видна ни в применённых, ни в отказах."""
    model = _model()
    blocks = _block_ids(model)
    first = _issue(1, blocks[0], "Дианьмэнь – это", "Дианьмэнь — это")
    second = _issue(2, blocks[1], "— Спросил доктор.", "— спросил доктор.")
    client = _Client(
        {
            "language_diagnosis": {"issues": [first, second]},
            # The model answers about one of the two issues it was given.
            "language_batch_correction": _made([first]),
            "language_mechanical_validation": {
                "confirmed_issue_ids": ["issue-1"],
                "rejected_issue_ids": [],
            },
        }
    )

    result = _run(client, _request(model))

    assert result.refusals["issue-2"] == "correction_omitted"
    assert "issue-2" in {issue.issue_id for issue in result.suggestions}
    assert "correction_omitted" in REFUSAL_DESCRIPTIONS


def test_a_deletion_survives_the_whole_pipeline_and_leaves_the_book():
    model = _model()
    blocks = _block_ids(model)
    artefact = _issue(
        1, blocks[2], " (Конец главы)", "", category="meta_comment"
    )
    client = _Client(
        {
            "language_diagnosis": {"issues": [artefact]},
            "language_batch_correction": _made([artefact]),
            "language_batch_validation": {
                "confirmed_issue_ids": ["issue-1"],
                "rejected_issue_ids": [],
            },
        }
    )

    result = _run(client, _request(model))

    assert [item.issue_id for item in result.applied] == ["issue-1"]
    texts = [
        block["inlines"][0]["text"]
        for block in build_translation_payload(result.preview_model)["blocks"]
    ]
    assert not any("Конец главы" in text for text in texts)


# ---------------------------------------------------------- transient failure


def test_a_pause_the_service_asked_for_survives_being_wrapped():
    """Хендлер знает про паузу в 59 с, а отдаёт наверх отказ без неё."""

    class _RateLimited(Exception):
        def __init__(self) -> None:
            super().__init__("API запросил паузу на 59с.")
            self.delay_seconds = 59

    try:
        try:
            raise _RateLimited()
        except _RateLimited as cause:
            raise RuntimeError("Сервис просит ждать дольше, чем может одна проверка") from cause
    except RuntimeError as wrapped:
        assert is_transient(wrapped) is True


def test_an_error_with_no_pause_anywhere_stays_permanent():
    try:
        try:
            raise ValueError("PROHIBITED_CONTENT")
        except ValueError as cause:
            raise RuntimeError("Блокировка на уровне промпта") from cause
    except RuntimeError as wrapped:
        assert is_transient(wrapped) is False


def test_deleting_a_whole_paragraph_of_artefact_leaves_the_book_intact():
    """«(Конец главы)» часто занимает весь абзац — удаление не должно ломать главу."""
    model = build_html_document_model(
        "<p>Он сел.</p><p>(Конец главы)</p>", document_id="chapter-1"
    )
    blocks = _block_ids(model)
    artefact = _issue(1, blocks[1], "(Конец главы)", "", category="meta_comment")
    client = _Client(
        {
            "language_diagnosis": {"issues": [artefact]},
            "language_batch_correction": _made([artefact]),
            "language_batch_validation": {
                "confirmed_issue_ids": ["issue-1"],
                "rejected_issue_ids": [],
            },
        }
    )

    result = _run(client, _request(model))

    assert [item.issue_id for item in result.applied] == ["issue-1"]
    payload = build_translation_payload(result.preview_model)
    texts = [
        "".join(inline.get("text", "") for inline in block["inlines"])
        for block in payload["blocks"]
    ]
    assert texts[0] == "Он сел."
    assert texts[1] == ""
