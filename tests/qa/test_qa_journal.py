import json
import math

import pytest

from gemini_translator.qa.journal import (
    QaJournal,
    QaJournalCorruptedError,
    QaJournalError,
    QaJournalUnsupportedVersionError,
)
from gemini_translator.qa.models import ChapterMetrics
from gemini_translator.utils.project_manager import TranslationProjectManager


def _metrics() -> ChapterMetrics:
    return ChapterMetrics(
        chapter_id="chapter-1",
        source_language="zh",
        target_language="ru",
        content_kind="narrative",
        source_chars=1000,
        translated_chars=2800,
        source_units=40,
        aligned_units=39,
        possible_gaps=1,
        glossary_expected=5,
        glossary_matched=5,
        glossary_conflicts=0,
        untranslated_by_script={"han": 0},
        allowed_foreign_fragments=1,
        language_tool_issues=0,
        protected_entities=0,
        syntax_candidates=0,
        quality_estimator=None,
        quality_score=None,
        quality_score_status="not_run",
        capability_durations={},
        retries=0,
        input_tokens=100,
        output_tokens=300,
        duration_seconds=4.5,
        risk_level="low",
        applied_actions=(),
    )


def test_journal_round_trip_uses_v3_json_and_dataframe_schema(tmp_path):
    """Removing v3 persistence or metric serialization breaks a restored report."""
    journal = QaJournal.empty(book_id="book-1")
    journal.upsert_metrics(_metrics())
    path = tmp_path / "translation_qa.json"

    journal.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    restored = QaJournal.load(path)

    assert payload["schema_version"] == 3
    assert payload["book_id"] == "book-1"
    assert set(payload) == {
        "schema_version",
        "book_id",
        "updated_at",
        "metrics",
        "candidates",
        "chapter_states",
        "repairs",
        "suggestions",
        "glossary_observations",
    }
    assert restored.metrics["chapter-1"].length_ratio == 2.8
    assert list(restored.metrics_frame().columns) == list(
        ChapterMetrics.dataframe_columns()
    )


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ("{not json", QaJournalCorruptedError),
        (json.dumps({"schema_version": 99}), QaJournalUnsupportedVersionError),
    ],
)
def test_journal_load_rejects_bad_data_without_rewriting_it(
    tmp_path, payload, error_type
):
    """Turning bad journals into empty files would erase the user's QA history."""
    path = tmp_path / "translation_qa.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(error_type):
        QaJournal.load(path)

    assert path.read_text(encoding="utf-8") == payload


def test_project_manager_uses_project_folder_for_qa_history_paths(tmp_path):
    """Using a cache path or a nonexistent project_dir loses durable QA history."""
    manager = TranslationProjectManager(str(tmp_path))

    assert manager.get_translation_qa_journal_path() == tmp_path / "translation_qa.json"
    assert manager.get_translation_qa_backup_dir() == tmp_path / "translation_qa_backups"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_journal_load_rejects_non_standard_json_numbers_without_rewriting(
    tmp_path, value
):
    """Using json.load defaults would accept NaN and silently poison reports."""
    journal = QaJournal.empty(book_id="book-1")
    journal.upsert_metrics(_metrics())
    path = tmp_path / "translation_qa.json"
    journal.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metrics"][0]["quality_score"] = value
    original = json.dumps(payload)
    path.write_text(original, encoding="utf-8")

    with pytest.raises(QaJournalCorruptedError):
        QaJournal.load(path)

    assert path.read_text(encoding="utf-8") == original


def test_journal_save_rejects_non_finite_metrics_as_strict_json(tmp_path):
    """allow_nan=True would write JSON consumers cannot safely read."""
    journal = QaJournal.empty(book_id="book-1")
    journal.candidates.append({"score": math.nan})

    with pytest.raises(ValueError):
        journal.save(tmp_path / "translation_qa.json")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unexpected": "data"}),
        lambda payload: payload.update({"schema_version": True}),
        lambda payload: payload.update({"candidates": ["not an object"]}),
        lambda payload: payload.update(
            {"repairs": [{"entry_id": "id", "chapter_id": "one", "decision": 1}]}
        ),
        lambda payload: payload.update(
            {
                "candidates": [
                    {"entry_id": "id", "chapter_id": "one", "decision": "unknown"}
                ]
            }
        ),
    ],
)
def test_journal_load_rejects_strict_schema_violations(tmp_path, mutate):
    """Loose validation would discard unknown data or invalid entry types."""
    journal = QaJournal.empty(book_id="book-1")
    path = tmp_path / "translation_qa.json"
    journal.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    original = json.dumps(payload)
    path.write_text(original, encoding="utf-8")

    with pytest.raises(QaJournalCorruptedError):
        QaJournal.load(path)

    assert path.read_text(encoding="utf-8") == original


def test_journal_save_removes_temp_and_preserves_target_on_serialization_error(tmp_path):
    """Catching only OSError leaves partial sibling temp files after json.dump errors."""
    journal = QaJournal.empty(book_id="book-1")
    journal.candidates.append({"not_serializable": object()})
    target = tmp_path / "translation_qa.json"
    target.write_text("existing journal", encoding="utf-8")
    temporary = tmp_path / ".translation_qa.json.tmp"

    with pytest.raises(TypeError):
        journal.save(target)

    assert target.read_text(encoding="utf-8") == "existing journal"
    assert not temporary.exists()


def test_a_journal_written_before_chapter_states_still_loads(tmp_path):
    """An existing project must keep its QA history when the schema grows."""
    path = tmp_path / "translation_qa.json"
    journal = QaJournal.empty(book_id="book-1")
    journal.upsert_metrics(_metrics())
    journal.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("chapter_states")
    payload.pop("suggestions")
    payload["schema_version"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    restored = QaJournal.load(path)

    assert restored.chapter_states == {}
    assert restored.metrics["chapter-1"].length_ratio == 2.8


def test_chapter_state_round_trips_and_stays_typed(tmp_path):
    """The final pass reads this state; an untyped entry would silently skip work."""
    from gemini_translator.qa.models import QaChapterState

    path = tmp_path / "translation_qa.json"
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_state(
        QaChapterState(
            chapter_id="chapter-1",
            status="deferred",
            analysis_identity="semantic-units-v1",
            risk_level="medium",
            book_sample_size=3,
        )
    )
    journal.save(path)

    restored = QaJournal.load(path)

    assert restored.chapter_states["chapter-1"].status == "deferred"
    assert restored.chapter_states["chapter-1"].book_sample_size == 3
    with pytest.raises(QaJournalError):
        journal.record_chapter_state({"chapter_id": "chapter-2"})


def _suggestion(chapter_id="chapter-1", original="сразу ушёл", replacement="тут же ушёл", **overrides):
    from gemini_translator.qa.models import QaSuggestion

    values = {
        "suggestion_id": QaSuggestion.identity(chapter_id, "n.1", original, replacement),
        "chapter_id": chapter_id,
        "block_id": "n.1",
        "category": "calque",
        "original_text": original,
        "replacement_text": replacement,
        "reason": "validation_declined",
        "explanation": "Калька.",
        "created_at": "2026-09-13T10:00:00+00:00",
    }
    values.update(overrides)
    return QaSuggestion(**values)


def _state(chapter_id="chapter-1"):
    from gemini_translator.qa.models import QaChapterState

    return QaChapterState(chapter_id=chapter_id, status="checked")


def test_suggestions_are_saved_with_their_reasons_and_read_back(tmp_path):
    path = tmp_path / "translation_qa.json"
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_result(state=_state(), suggestions=(_suggestion(),))

    journal.save(path)
    restored = QaJournal.load(path)

    assert restored.suggestions == [_suggestion()]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["suggestions"][0]["reason"] == "validation_declined"


def test_a_version_2_journal_loads_without_suggestions_and_saves_as_version_3(tmp_path):
    """Журналы книг владельца — версии 2; они обязаны открыться."""
    path = tmp_path / "translation_qa.json"
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_state(_state())
    journal.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("suggestions")
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    restored = QaJournal.load(path)
    restored.save(path)

    assert restored.suggestions == []
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 3
    assert saved["suggestions"] == []


def test_a_new_pass_replaces_undecided_suggestions_and_never_revives_decided_ones():
    journal = QaJournal.empty(book_id="book-1")
    pending = _suggestion(original="a", replacement="b")
    dismissed = _suggestion(original="c", replacement="d")
    stale = _suggestion(original="e", replacement="f")
    other_chapter = _suggestion(chapter_id="chapter-2", original="g", replacement="h")
    journal.record_chapter_result(state=_state(), suggestions=(pending, dismissed, stale))
    journal.record_chapter_result(state=_state("chapter-2"), suggestions=(other_chapter,))
    journal.set_suggestion_status(dismissed.suggestion_id, "dismissed")
    journal.set_suggestion_status(stale.suggestion_id, "stale", "глава изменилась после проверки")
    fresh = _suggestion(original="i", replacement="j")

    journal.record_chapter_result(state=_state(), suggestions=(dismissed, fresh))

    assert {item.suggestion_id: item.status for item in journal.suggestions} == {
        dismissed.suggestion_id: "dismissed",
        fresh.suggestion_id: "pending",
        other_chapter.suggestion_id: "pending",
    }


def test_a_pass_that_names_no_suggestions_leaves_the_chapters_alone():
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_result(state=_state(), suggestions=(_suggestion(),))

    journal.record_chapter_result(state=_state())

    assert len(journal.suggestions) == 1


def test_an_empty_tuple_clears_a_chapters_undecided_suggestions():
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_result(state=_state(), suggestions=(_suggestion(),))

    journal.record_chapter_result(state=_state(), suggestions=())

    assert journal.suggestions == []


def test_suggestions_are_recorded_only_with_the_chapter_they_belong_to():
    journal = QaJournal.empty(book_id="book-1")

    with pytest.raises(QaJournalError):
        journal.record_chapter_result(suggestions=(_suggestion(),))
    with pytest.raises(QaJournalError):
        journal.record_chapter_result(state=_state("chapter-2"), suggestions=(_suggestion(),))
    with pytest.raises(QaJournalError):
        journal.record_chapter_result(state=_state(), suggestions=({"suggestion_id": "x"},))


def test_a_status_change_is_found_by_id_and_validated():
    from gemini_translator.qa.models import QaModelValidationError

    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_result(state=_state(), suggestions=(_suggestion(),))
    suggestion_id = journal.suggestions[0].suggestion_id

    updated = journal.set_suggestion_status(suggestion_id, "applied")

    assert updated.status == "applied"
    assert journal.suggestion(suggestion_id).status == "applied"
    assert journal.suggestion("sg-unknown") is None
    with pytest.raises(QaJournalError):
        journal.set_suggestion_status("sg-unknown", "dismissed")
    with pytest.raises(QaModelValidationError):
        journal.set_suggestion_status(suggestion_id, "maybe")


def test_a_damaged_suggestion_makes_the_journal_unreadable_but_untouched(tmp_path):
    path = tmp_path / "translation_qa.json"
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_result(state=_state(), suggestions=(_suggestion(),))
    journal.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["suggestions"][0]["status"] = "maybe"
    original = json.dumps(payload)
    path.write_text(original, encoding="utf-8")

    with pytest.raises(QaJournalCorruptedError):
        QaJournal.load(path)

    assert path.read_text(encoding="utf-8") == original

