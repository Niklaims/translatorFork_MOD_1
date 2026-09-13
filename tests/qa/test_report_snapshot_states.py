"""The report must list every checked chapter, not only those with completeness metrics.

Measured on three of the owner's books on 2026-09-13: 484, 490 and 238 chapter
states, hundreds of repairs, and not one metrics entry, because only the
language check was on. The report was built from metrics alone and stayed empty.
"""

from __future__ import annotations

import json

from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, QaChapterState, RiskLevel
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot


def _state(chapter_id: str, status: str = "checked", risk=RiskLevel.LOW) -> QaChapterState:
    return QaChapterState(
        chapter_id=chapter_id,
        status=status,
        risk_level=risk,
        updated_at="2026-09-09T10:00:00+00:00",
    )


def _language_only_journal() -> QaJournal:
    """The shape of the owner's real journals: states and repairs, no metrics."""
    journal = QaJournal.empty(book_id="book-1")
    journal.record_chapter_state(_state("chapter-1"))
    journal.record_chapter_state(_state("chapter-2", "deferred", RiskLevel.MEDIUM))
    journal.record_chapter_state(_state("chapter-3", "blocked", RiskLevel.HIGH))
    for patch_id, chapter_id in (
        ("lang-1", "chapter-1"),
        ("lang-2", "chapter-1"),
        ("lang-3", "chapter-3"),
    ):
        journal.append_repair(
            {"patch_id": patch_id, "chapter_id": chapter_id, "candidate_id": "language"}
        )
    return journal


def test_a_language_only_journal_lists_every_checked_chapter():
    snapshot = BookQaReportSnapshot.from_journal(_language_only_journal())

    assert [row.chapter_id for row in snapshot.rows] == [
        "chapter-1",
        "chapter-2",
        "chapter-3",
    ]
    assert [row.status for row in snapshot.rows] == ["checked", "deferred", "blocked"]
    assert [row.applied_repairs for row in snapshot.rows] == [2, 0, 1]
    assert snapshot.rows[0].checked_at == "2026-09-09T10:00:00+00:00"
    assert snapshot.has_completeness is False


def test_the_book_totals_count_statuses_and_repairs():
    snapshot = BookQaReportSnapshot.from_journal(_language_only_journal())

    assert snapshot.checked_count == 1
    assert snapshot.deferred_count == 1
    assert snapshot.blocking_count == 1
    assert snapshot.repaired_chapters == ("chapter-1", "chapter-3")
    assert snapshot.repair_count == 3
    assert snapshot.pending_suggestion_count == 0
    assert snapshot.pending_suggestion_chapters == ()


def test_without_metrics_the_risk_comes_from_the_chapter_state():
    snapshot = BookQaReportSnapshot.from_journal(_language_only_journal())

    assert [row.risk_level for row in snapshot.rows] == ["low", "medium", "high"]
    assert snapshot.rows[2].risk_label == "Высокий"


def test_metrics_win_over_the_state_and_mark_completeness():
    journal = _language_only_journal()
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-2",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=2900,
            possible_gaps=2,
            risk_level=RiskLevel.HIGH,
        )
    )

    snapshot = BookQaReportSnapshot.from_journal(journal)
    rows = {row.chapter_id: row for row in snapshot.rows}

    assert rows["chapter-2"].has_completeness is True
    assert rows["chapter-2"].risk_level == "high"
    assert rows["chapter-2"].possible_gaps == 2
    assert rows["chapter-2"].status == "deferred"
    assert rows["chapter-1"].has_completeness is False
    assert snapshot.has_completeness is True


def test_a_gate_counts_as_blocking_even_without_a_blocked_state():
    class _Gate:
        chapter_id = "chapter-1"
        reason = "подтверждённый пропуск"

    snapshot = BookQaReportSnapshot.from_journal(_language_only_journal(), [_Gate()])

    assert snapshot.blocking_count == 2
    assert snapshot.rows[0].blocked_reason == "подтверждённый пропуск"


def test_a_chapter_known_only_from_its_repairs_still_has_a_row():
    journal = QaJournal.empty(book_id="book-1")
    journal.append_repair({"patch_id": "old-1", "chapter_id": "chapter-9"})

    snapshot = BookQaReportSnapshot.from_journal(journal)

    assert [
        (row.chapter_id, row.status, row.risk_level, row.applied_repairs)
        for row in snapshot.rows
    ] == [("chapter-9", "", "", 1)]


def test_chapters_follow_natural_order():
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id in ("chapter-10", "chapter-2", "chapter-1"):
        journal.record_chapter_state(_state(chapter_id))

    snapshot = BookQaReportSnapshot.from_journal(journal)

    assert [row.chapter_id for row in snapshot.rows] == [
        "chapter-1",
        "chapter-2",
        "chapter-10",
    ]


def test_a_journal_object_without_chapter_states_still_reports_its_metrics():
    """Callers that hand over metrics only must not need the new attribute."""

    class _MetricsOnly:
        metrics = {
            "chapter-1": ChapterMetrics(
                chapter_id="chapter-1",
                source_language="zh",
                target_language="ru",
                source_chars=100,
                translated_chars=290,
            )
        }
        candidates = ()
        repairs = ()

    snapshot = BookQaReportSnapshot.from_journal(_MetricsOnly())

    assert [row.chapter_id for row in snapshot.rows] == ["chapter-1"]
    assert snapshot.rows[0].has_completeness is True


def test_a_saved_version_1_journal_still_builds_a_report(tmp_path):
    path = tmp_path / "translation_qa.json"
    journal = QaJournal.empty(book_id="book-1")
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-1",
            source_language="zh",
            target_language="ru",
            source_chars=100,
            translated_chars=290,
        )
    )
    journal.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("chapter_states")
    payload["schema_version"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    snapshot = BookQaReportSnapshot.from_journal(QaJournal.load(path))

    assert [row.chapter_id for row in snapshot.rows] == ["chapter-1"]
