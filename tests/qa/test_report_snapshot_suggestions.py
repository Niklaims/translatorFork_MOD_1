"""«Ждут решения» counts pending and stale suggestions: both need the user."""

from __future__ import annotations

from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import QaChapterState, QaSuggestion
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot


def _suggestion(chapter_id: str, original: str, created_at="2026-09-13T10:00:00+00:00"):
    return QaSuggestion(
        suggestion_id=QaSuggestion.identity(chapter_id, "n.1", original, original + "!"),
        chapter_id=chapter_id,
        block_id="n.1",
        category="punctuation",
        original_text=original,
        replacement_text=original + "!",
        created_at=created_at,
    )


def _record(journal: QaJournal, chapter_id: str, *suggestions) -> None:
    journal.record_chapter_result(
        state=QaChapterState(chapter_id=chapter_id, status="checked"),
        suggestions=suggestions,
    )


def test_pending_and_stale_suggestions_wait_for_a_decision():
    journal = QaJournal.empty(book_id="book-1")
    stale = _suggestion("chapter-2", "c")
    dismissed = _suggestion("chapter-2", "d")
    _record(journal, "chapter-10", _suggestion("chapter-10", "a"), _suggestion("chapter-10", "b"))
    _record(journal, "chapter-2", stale, dismissed)
    journal.set_suggestion_status(stale.suggestion_id, "stale", "глава изменилась после проверки")
    journal.set_suggestion_status(dismissed.suggestion_id, "dismissed")

    snapshot = BookQaReportSnapshot.from_journal(journal)

    assert {row.chapter_id: row.pending_suggestions for row in snapshot.rows} == {
        "chapter-2": 1,
        "chapter-10": 2,
    }
    assert snapshot.pending_suggestion_count == 3
    assert snapshot.pending_suggestion_chapters == ("chapter-2", "chapter-10")
    assert [item.chapter_id for item in snapshot.suggestions] == [
        "chapter-2",
        "chapter-10",
        "chapter-10",
    ]
    assert [item.status for item in snapshot.suggestions_for("chapter-2")] == ["stale"]


def test_a_chapter_known_only_from_its_suggestions_still_has_a_row():
    journal = QaJournal.empty(book_id="book-1")
    journal.suggestions.append(_suggestion("chapter-7", "a"))

    snapshot = BookQaReportSnapshot.from_journal(journal)

    assert [(row.chapter_id, row.pending_suggestions) for row in snapshot.rows] == [
        ("chapter-7", 1)
    ]


def test_decided_suggestions_do_not_wait():
    journal = QaJournal.empty(book_id="book-1")
    applied = _suggestion("chapter-1", "a")
    _record(journal, "chapter-1", applied)
    journal.set_suggestion_status(applied.suggestion_id, "applied")

    snapshot = BookQaReportSnapshot.from_journal(journal)

    assert snapshot.suggestions == ()
    assert snapshot.rows[0].pending_suggestions == 0
