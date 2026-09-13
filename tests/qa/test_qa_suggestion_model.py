"""A refused fix is kept exactly as proposed, and a damaged record is refused."""

from __future__ import annotations

import pytest

from gemini_translator.qa.models import QaModelValidationError, QaSuggestion


def _suggestion(**overrides) -> QaSuggestion:
    values = {
        "suggestion_id": QaSuggestion.identity(
            "chapter-1", "n.1", "сразу ушёл", "тут же ушёл"
        ),
        "chapter_id": "chapter-1",
        "block_id": "n.1",
        "category": "calque",
        "original_text": "сразу ушёл",
        "replacement_text": "тут же ушёл",
        "reason": "validation_declined",
        "explanation": "Калька с английского.",
        "created_at": "2026-09-13T10:00:00+00:00",
    }
    values.update(overrides)
    return QaSuggestion(**values)


def test_a_suggestion_round_trips_through_its_dict():
    suggestion = _suggestion()

    assert QaSuggestion.from_dict(suggestion.to_dict()) == suggestion
    assert suggestion.status == "pending"


def test_the_identity_is_stable_and_depends_on_every_part():
    first = QaSuggestion.identity("chapter-1", "n.1", "a", "b")

    assert first == QaSuggestion.identity("chapter-1", "n.1", "a", "b")
    assert first.startswith("sg") and len(first) == 22
    assert len(
        {
            first,
            QaSuggestion.identity("chapter-2", "n.1", "a", "b"),
            QaSuggestion.identity("chapter-1", "n.2", "a", "b"),
            QaSuggestion.identity("chapter-1", "n.1", "c", "b"),
            QaSuggestion.identity("chapter-1", "n.1", "a", "c"),
        }
    ) == 5


def test_an_empty_replacement_is_kept_but_cannot_be_applied():
    suggestion = _suggestion(replacement_text="")

    assert suggestion.awaits_decision is True
    assert suggestion.applicable is False


@pytest.mark.parametrize(
    ("status", "awaits", "applicable"),
    [
        ("pending", True, True),
        ("stale", True, False),
        ("applied", False, False),
        ("dismissed", False, False),
    ],
)
def test_what_still_awaits_a_decision(status, awaits, applicable):
    suggestion = _suggestion(status=status)

    assert suggestion.awaits_decision is awaits
    assert suggestion.applicable is applicable


@pytest.mark.parametrize(
    ("reason", "applicable"),
    [
        ("validation_declined", True),
        ("low_confidence (0.62 < 0.85)", True),
        ("ambiguous_span", False),
        ("paragraph_break", False),
    ],
)
def test_a_fix_the_text_cannot_take_is_left_to_a_person(reason, applicable):
    """Неоднозначный фрагмент или разрыв абзаца не вписать никаким нажатием."""
    assert _suggestion(reason=reason).applicable is applicable


@pytest.mark.parametrize(
    "damage",
    [
        lambda payload: payload.update(status="maybe"),
        lambda payload: payload.update(chapter_id=""),
        lambda payload: payload.update(original_text=None),
        lambda payload: payload.update(extra="x"),
        lambda payload: payload.pop("reason"),
    ],
)
def test_a_damaged_record_is_refused(damage):
    payload = _suggestion().to_dict()
    damage(payload)

    with pytest.raises(QaModelValidationError):
        QaSuggestion.from_dict(payload)
