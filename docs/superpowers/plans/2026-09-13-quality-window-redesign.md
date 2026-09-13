# Quality Window Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the «Качество перевода» window list every checked chapter, keep the language fixes the check refused so the user can apply or dismiss them, and build the window from the application's own style vocabulary.

**Architecture:**
- **Stage 1.** Report rows are built from the union of chapter states, metrics and repairs.
- **Stage 2.**
  - The 900-line dialog becomes a shell plus three views: report, suggestions and settings.
  - The views are built from theme style hooks.
  - The theme gains readable status-text tokens.
  - The key dropdown is replaced by a count of the provider's working keys.
- **Stage 3.**
  - Refused suggestions are persisted in journal v3.
  - An accepted suggestion is written through the same path as an automatic fix: backup → atomic write → repair store → journal.

**Tech Stack:** Python 3.11+, PyQt6 6.11 (offscreen in tests), pytest, ruff 0.16.

**Spec:** `docs/superpowers/specs/2026-09-13-quality-window-redesign-design.md`

## Global Constraints

### Where and how to work

- Work in the worktree `.worktrees/quality-window-redesign` on branch `feature/quality-window-redesign`.
- Run tests with `.venv/bin/python -m pytest`.
- Lint with `.venv/bin/python -m ruff check <changed files>`.
- Stage files by name. Never run `git add -A` or `git add .`.

### The shared main checkout

- In the main checkout (`/Users/rasreo/dev/translatorFork_MOD`), never commit, stash, revert, reset or check out anything.
- Read it only with `git --no-optional-locks`.
- Push only when the owner asks.
- Never modify the files below. The main checkout holds other sessions' uncommitted edits to them, and a stage that touches them cannot be fast-forwarded:
  - `gemini_translator/api/handlers/gemini.py`
  - `gemini_translator/config/translation_qa_prompts.json`
  - `gemini_translator/qa/language_validation.py`
  - `gemini_translator/qa/llm/language_repairer.py`
  - `gemini_translator/qa/llm/language_reviewer.py`
  - `gemini_translator/qa/llm/schemas.py`
  - `gemini_translator/ui/widgets/log_widget.py`
  - `main.py`
  - `tests/qa/test_language_check_completeness.py`
  - `tests/qa/test_language_refusal_reasons.py`
  - `tests/qa/test_qa_request_safety.py`
  - `tests/test_settings_runtime_store.py`
  - `tests/qa/test_language_edit_precision.py`
  - `tests/test_log_event_timestamps.py`

### Copy and styling

- UI copy is Russian and exactly as written in this plan.
- Code comments and docstrings are English, matching the surrounding files.
- New widgets are styled only through objectName style hooks and palette tokens. No hex colours and no `setStyleSheet` calls in them. The one exception is the inline spans that `qa.text_diff.highlight_pair` already produces.

### Contracts that must hold

- These signals stay on `TranslationQualityDialog`:
  - `check_chapter_requested(str)`
  - `check_all_requested()`
  - `resume_requested()`
  - `undo_chapter_requested(str)`
  - `undo_all_requested()`
  - `cancel_requested()`
  - `settings_changed(object)`
  - `embedding_test_requested(object)`
  - `export_requested(str)`
- These methods stay on `TranslationQualityDialog`: `set_report`, `set_busy`, `set_progress`, `append_log`, `set_status`, `selected_chapter_id`, `select_chapter`, `qa_settings`.
- The `QaSettings` schema does not change.
- `LanguageReplacement` requires a non-empty `replacement_text`, and it lives in a file this plan must not touch. A suggestion with an empty replacement is therefore shown and can be dismissed, but «Применить» is unavailable for it.
- Every new text/background token pair reaches at least 4.5:1 contrast in both themes.

### Commits and stages

- A commit trailer names the model that actually wrote the commit, exactly as your own harness gives it. The commit blocks below leave it as a placeholder on purpose.
- After each stage:
  1. Run the full suite.
  2. Run ruff on the changed files.
  3. Do a mutation check of the stage's key behaviour.
  4. Look at the real window in both themes.
  5. Fast-forward `main` in the main checkout.

## Deviations from the spec, with reasons

1. **Status text tokens.** Status chips and the danger button write their text in new palette tokens `success_text`, `warning_text` and `danger_text`, not in `__SUCCESS__`, `__WARNING__` or `__DANGER__`. Measured in the light theme, the spec's pairs give 2.97, 3.29 and 4.40:1, below the spec's own 4.5:1 floor. In the dark theme the new tokens equal the base colours, so nothing changes there.
2. **Status in the table.** In the chapter table the status is coloured text, not a chip widget, as in the approved mockup. A widget per cell is what froze the task list before.
3. **`ChapterQaTableModel` is removed in stage 2.** The report table is a `QTableWidget`, as the spec says, so the model would be dead code. Its performance test is replaced by a test that an unchanged report does not rebuild the table.
4. **«Сбросить» next to a legacy key provider.** When a legacy key-provider line is shown, the embedding card gets a «Сбросить» button. With Gemini selected there is no own-key field, so otherwise the legacy value could only be cleared by switching the provider away and back.
5. **`quality_score` on the row.** `ChapterQaRow` gets a fifth new field, `quality_score`, in stage 2. The score column and the score card need it.
6. **`embedding_checked(str)`.** The controller gets this signal so the connection probe's result lands in the settings card's result line, not only in the window's status line.

## File map

| File | Stage | Responsibility |
|---|---|---|
| `gemini_translator/qa/report_snapshot.py` | 1, 2, 3 | Qt-free report: rows from states, metrics and repairs; book totals; pending suggestions |
| `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_models.py` | 1, 2 | Stage 1: status column and hidden completeness columns; stage 2: only `DECISION_LABELS` and re-exports |
| `gemini_translator/ui/themes.py` | 2 | Readable status text tokens, danger button on tokens, `QLabel#statusChip` |
| `gemini_translator/qa/assembly.py` | 2 | `embedding_key_counts` |
| `gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py` | 2, 3 | Status chip, metric card, empty state, date and count wording; stage 3: suggestion card |
| `gemini_translator/ui/dialogs/validation_dialogs/quality_settings_view.py` | 2 | «Настройки» tab |
| `gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py` | 2, 3 | «Отчёт» tab |
| `gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py` | 2, 3 | «Предложения» tab |
| `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py` | 1, 2, 3 | Shell: header, tabs, action bar, public signals and methods |
| `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_controller.py` | 2, 3 | `embedding_checked`; apply and dismiss suggestion |
| `gemini_translator/ui/dialogs/validation.py` | 2 | Passes `key_counter` and `book_title` |
| `gemini_translator/qa/models.py` | 3 | `QaSuggestion` |
| `gemini_translator/qa/journal.py` | 3 | Journal v3 with `suggestions` |
| `gemini_translator/qa/service.py` | 3 | Record, apply and dismiss suggestions |
| `gemini_translator/core/chapter_qa_coordinator.py` | 3 | `apply_suggestion`, `dismiss_suggestion` |

---

# Stage 1. The report from chapter states

### Task 1: Report rows from chapter states, metrics and repairs

**Files:**
- Modify: `gemini_translator/qa/report_snapshot.py` (whole file)
- Test: `tests/qa/test_report_snapshot_states.py` (create)

**Interfaces:**
- Consumes: `QaJournal.chapter_states: dict[str, QaChapterState]`, `QaJournal.metrics`, `QaJournal.repairs`, `QaJournal.candidates`; `natural_sort_key(value: str) -> list` from `gemini_translator/utils/text_sort.py`.
- Produces:
  - `CHAPTER_STATUS_LABELS: dict[str, str]` with the keys `"checked"`, `"deferred"`, `"blocked"` and `""`.
  - New `ChapterQaRow` fields, all with defaults: `status: str = ""`, `checked_at: str = ""`, `pending_suggestions: int = 0`, `has_completeness: bool = False`.
  - New `BookQaReportSnapshot` properties:
    - `has_completeness -> bool`
    - `checked_count -> int`
    - `deferred_count -> int`
    - `blocking_count -> int`
    - `repair_count -> int`
    - `pending_suggestion_count -> int`
    - `pending_suggestion_chapters -> tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

Create `tests/qa/test_report_snapshot_states.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_report_snapshot_states.py -v`

Expected: FAIL. The language-only journal gives no rows (`assert [] == ['chapter-1', ...]`), and the new properties raise `AttributeError`.

- [ ] **Step 3: Write the implementation**

Replace the whole of `gemini_translator/qa/report_snapshot.py` with:

```python
"""One immutable, Qt-free view of the QA journal, ready to be shown or exported."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..utils.text_sort import natural_sort_key
from .book_metrics import BookMetricsAnalyzer, RelativeRisk
from .models import ChapterMetrics, RiskLevel


RISK_LABELS = {
    RiskLevel.LOW: "Низкий",
    RiskLevel.MEDIUM: "Средний",
    RiskLevel.HIGH: "Высокий",
    RiskLevel.FAILED: "Сбой",
}
RELATIVE_RISK_LABELS = {
    RelativeRisk.UNAVAILABLE: "нет книжной нормы",
    RelativeRisk.LOW: "в норме книги",
    RelativeRisk.MEDIUM: "отклонение",
    RelativeRisk.HIGH: "сильное отклонение",
}
# What each recorded chapter status means to the person reading the report.
# The empty status belongs to a chapter known only from its repairs: a journal
# written before chapter states were recorded.
CHAPTER_STATUS_LABELS = {
    "checked": "Проверена",
    "deferred": "Отложена",
    "blocked": "Блокирует",
    "": "Нет данных",
}


@dataclass(frozen=True, slots=True)
class ChapterQaRow:
    """One chapter as the report shows it, already formatted for reading."""

    chapter_id: str
    language_pair: str
    length_ratio: float
    profile_status: str
    book_position: str
    glossary_conflicts: int
    untranslated_fragments: int
    possible_gaps: int
    confirmed_gaps: int
    language_issues: int
    applied_repairs: int
    risk_label: str
    risk_level: str
    duration_seconds: float
    tokens: int
    blocked_reason: str = ""
    status: str = ""
    checked_at: str = ""
    pending_suggestions: int = 0
    # Only a completeness check produces metrics; without them every field
    # above that describes length, gaps or the book norm is a placeholder.
    has_completeness: bool = False


@dataclass(frozen=True, slots=True)
class BookQaReportSnapshot:
    """An immutable view of the journal, safe to hand to the UI thread."""

    rows: tuple[ChapterQaRow, ...] = ()
    decisions_by_chapter: dict[str, tuple[str, ...]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limited_mode_chapters: tuple[str, ...] = ()

    @property
    def blocked_chapters(self) -> tuple[str, ...]:
        return tuple(row.chapter_id for row in self.rows if row.blocked_reason)

    @property
    def repaired_chapters(self) -> tuple[str, ...]:
        return tuple(row.chapter_id for row in self.rows if row.applied_repairs)

    @property
    def has_completeness(self) -> bool:
        return any(row.has_completeness for row in self.rows)

    @property
    def checked_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "checked")

    @property
    def deferred_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "deferred")

    @property
    def blocking_count(self) -> int:
        return sum(
            1 for row in self.rows if row.status == "blocked" or row.blocked_reason
        )

    @property
    def repair_count(self) -> int:
        return sum(row.applied_repairs for row in self.rows)

    @property
    def pending_suggestion_count(self) -> int:
        return sum(row.pending_suggestions for row in self.rows)

    @property
    def pending_suggestion_chapters(self) -> tuple[str, ...]:
        return tuple(row.chapter_id for row in self.rows if row.pending_suggestions)

    @classmethod
    def from_journal(cls, journal, open_gates=()) -> "BookQaReportSnapshot":
        """Build the snapshot from a loaded journal and the queue's open gates."""
        gate_reasons = {
            str(getattr(gate, "chapter_id", "")): str(getattr(gate, "reason", ""))
            or "неустранённый риск"
            for gate in open_gates or ()
        }
        metrics_by_chapter = dict(getattr(journal, "metrics", None) or {})
        states = dict(getattr(journal, "chapter_states", None) or {})
        decisions: dict[str, list[str]] = {}
        for entry in getattr(journal, "candidates", ()):
            chapter_id = str(entry.get("chapter_id", ""))
            decision = str(entry.get("decision", ""))
            if chapter_id and decision:
                decisions.setdefault(chapter_id, []).append(decision)
        repairs_by_chapter: dict[str, int] = {}
        for repair in getattr(journal, "repairs", ()):
            chapter_id = str(repair.get("chapter_id", ""))
            if chapter_id:
                repairs_by_chapter[chapter_id] = repairs_by_chapter.get(chapter_id, 0) + 1

        # A chapter belongs in the report once anything about it was recorded:
        # a language-only check leaves a state and repairs, never metrics.
        chapter_ids = sorted(
            set(metrics_by_chapter) | set(states) | set(repairs_by_chapter),
            key=natural_sort_key,
        )
        metrics = [
            metrics_by_chapter[chapter_id]
            for chapter_id in chapter_ids
            if chapter_id in metrics_by_chapter
        ]
        positions = _book_positions(metrics)
        rows = tuple(
            _row_for(
                chapter_id,
                metrics_by_chapter.get(chapter_id),
                states.get(chapter_id),
                tuple(decisions.get(chapter_id, ())),
                repairs_by_chapter.get(chapter_id, 0),
                positions.get(chapter_id, "нет книжной нормы"),
                gate_reasons.get(chapter_id, ""),
            )
            for chapter_id in chapter_ids
        )
        return cls(
            rows=rows,
            decisions_by_chapter={
                chapter_id: tuple(values) for chapter_id, values in decisions.items()
            },
            limited_mode_chapters=tuple(
                item.chapter_id for item in metrics if _checked_without_alignment(item)
            ),
        )


def _checked_without_alignment(metrics: ChapterMetrics) -> bool:
    """Report whether this chapter was checked without semantic comparison.

    The journal keeps no mode field, but it does not need one: a chapter that
    was aligned has aligned units, and a chapter checked in limited mode has
    source units and none aligned.  The report's counter for this has existed
    from the start and was never filled.
    """
    return metrics.source_units > 0 and metrics.aligned_units == 0


def _book_positions(metrics: list[ChapterMetrics]) -> dict[str, str]:
    """Describe each chapter against its own language pair, when that is known."""
    if not metrics:
        return {}
    try:
        analyzer = BookMetricsAnalyzer()
        frame = analyzer.analyze(metrics)
        if frame.empty:
            return {}
        positions: dict[str, str] = {}
        for item in metrics:
            risk = analyzer.classify_ratio_risk(frame, item.chapter_id)
            if risk.baseline.median is None:
                positions[item.chapter_id] = "нет книжной нормы"
                continue
            z_value = risk.robust_z
            label = RELATIVE_RISK_LABELS.get(risk.relative_risk, "")
            positions[item.chapter_id] = (
                f"медиана {risk.baseline.median:.2f}, z={z_value:.1f} ({label})"
                if z_value is not None
                else f"медиана {risk.baseline.median:.2f}"
            )
        return positions
    except Exception:  # noqa: BLE001 - a report must never fail on statistics
        return {}


def _row_for(
    chapter_id: str,
    metrics: ChapterMetrics | None,
    state,
    decisions: tuple[str, ...],
    applied_repairs: int,
    book_position: str,
    blocked_reason: str,
) -> ChapterQaRow:
    confirmed_gaps = sum(
        1 for decision in decisions if decision in {"fixed", "repair_rejected"}
    )
    status = str(getattr(state, "status", "") or "")
    checked_at = str(getattr(state, "updated_at", "") or "")
    if metrics is None:
        risk = _state_risk(state)
        return ChapterQaRow(
            chapter_id=chapter_id,
            language_pair="",
            length_ratio=0.0,
            profile_status="",
            book_position="",
            glossary_conflicts=0,
            untranslated_fragments=0,
            possible_gaps=0,
            confirmed_gaps=confirmed_gaps,
            language_issues=0,
            applied_repairs=applied_repairs,
            risk_label=RISK_LABELS.get(risk, "") if risk is not None else "",
            risk_level=str(risk) if risk is not None else "",
            duration_seconds=0.0,
            tokens=0,
            blocked_reason=blocked_reason,
            status=status,
            checked_at=checked_at,
        )
    untranslated = metrics.untranslated_by_script or {}
    risk = RiskLevel(metrics.risk_level) if metrics.risk_level else RiskLevel.LOW
    return ChapterQaRow(
        chapter_id=metrics.chapter_id,
        language_pair=f"{metrics.source_language} → {metrics.target_language}",
        length_ratio=metrics.length_ratio,
        profile_status=_profile_status(metrics),
        book_position=book_position,
        glossary_conflicts=metrics.glossary_conflicts,
        untranslated_fragments=sum(int(value) for value in untranslated.values()),
        possible_gaps=metrics.possible_gaps,
        confirmed_gaps=confirmed_gaps,
        language_issues=metrics.language_tool_issues,
        applied_repairs=applied_repairs,
        risk_label=RISK_LABELS.get(risk, str(risk)),
        risk_level=str(risk),
        duration_seconds=metrics.duration_seconds,
        tokens=metrics.input_tokens + metrics.output_tokens,
        blocked_reason=blocked_reason,
        status=status,
        checked_at=checked_at,
        has_completeness=True,
    )


def _state_risk(state) -> RiskLevel | None:
    """The risk a chapter state recorded, or None when there is no usable one."""
    value = getattr(state, "risk_level", None)
    if not value:
        return None
    try:
        return RiskLevel(value)
    except ValueError:
        return None


def _profile_status(metrics: ChapterMetrics) -> str:
    from .ratio_profiles import get_ratio_profile

    try:
        profile = get_ratio_profile(metrics.source_language, metrics.target_language)
    except KeyError:
        return "профиль не задан"
    inside = profile.contains(metrics.length_ratio)
    bounds = f"{profile.minimum:.2f}–{profile.maximum:.2f}"
    return f"{'в профиле' if inside else 'вне профиля'} {bounds}"
```

- [ ] **Step 4: Run the new tests and the existing report users**

Run: `.venv/bin/python -m pytest tests/qa/test_report_snapshot_states.py tests/qa/test_limited_mode_alert.py tests/qa/test_translation_qa_performance.py tests/qa/test_qa_reporting.py tests/qa/test_translation_quality_dialog.py tests/qa/test_translation_quality_controller.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/qa/report_snapshot.py tests/qa/test_report_snapshot_states.py
git commit -m "feat(qa): list every checked chapter in the quality report

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 2: The current window shows the status and hides empty completeness columns

**Files:**
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_models.py`
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py`:
  - `set_report`, lines 467-485;
  - `_on_selection_changed`, lines 812-844.
- Test: `tests/qa/test_translation_quality_dialog.py` (append)

**Interfaces:**
- Consumes: `CHAPTER_STATUS_LABELS`, `ChapterQaRow.status`, `ChapterQaRow.checked_at`, `ChapterQaRow.has_completeness`, and `BookQaReportSnapshot.has_completeness`, `checked_count`, `deferred_count` (Task 1).
- Produces:
  - A `("Статус", "status")` column at index 1 of `ChapterQaTableModel.COLUMNS`.
  - `ChapterQaTableModel.COMPLETENESS_FIELDS: frozenset[str]`.
  - `ChapterQaTableModel.hidden_columns() -> tuple[int, ...]`.

This state lives only until stage 2 replaces the table. It exists so stage 1 alone already gives the owner a full report.

- [ ] **Step 1: Write the failing test**

Append to `tests/qa/test_translation_quality_dialog.py`:

```python
def _language_only_snapshot() -> BookQaReportSnapshot:
    from gemini_translator.qa.models import QaChapterState

    journal = QaJournal.empty(book_id="book-1")
    for chapter_id, status in (("chapter-1", "checked"), ("chapter-2", "deferred")):
        journal.record_chapter_state(QaChapterState(chapter_id=chapter_id, status=status))
    journal.append_repair({"patch_id": "lang-1", "chapter_id": "chapter-1"})
    return BookQaReportSnapshot.from_journal(journal)


def _column(name: str) -> int:
    return [field for _title, field in ChapterQaTableModel.COLUMNS].index(name)


def test_a_language_only_book_fills_the_table_with_statuses(qt_app):
    """Без метрик полноты отчёт был пуст, хотя главы проверены и исправлены."""
    dialog = TranslationQualityDialog()
    dialog.set_report(_language_only_snapshot())

    model = dialog.table_model
    assert model.rowCount() == 2
    assert model.index(0, _column("status")).data() == "Проверена"
    assert model.index(1, _column("status")).data() == "Отложена"
    assert model.index(0, _column("applied_repairs")).data() == "1"


def test_completeness_columns_hide_until_a_chapter_has_metrics(qt_app):
    dialog = TranslationQualityDialog()

    dialog.set_report(_language_only_snapshot())
    assert dialog.table.isColumnHidden(_column("possible_gaps"))
    assert not dialog.table.isColumnHidden(_column("applied_repairs"))

    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    assert not dialog.table.isColumnHidden(_column("possible_gaps"))


def test_a_chapter_without_metrics_shows_its_status_not_zero_ratios(qt_app):
    dialog = TranslationQualityDialog()
    dialog.set_report(_language_only_snapshot())

    dialog.select_chapter("chapter-1")
    details = dialog.details.toPlainText()

    assert "Статус: Проверена" in details
    assert "Исправлено автоматически: 1" in details
    assert "Коэффициент длины" not in details
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_translation_quality_dialog.py -k "language_only or completeness_columns or without_metrics" -v`

Expected: FAIL with `ValueError: 'status' is not in list`.

- [ ] **Step 3: Add the status column and the hidden columns to the model**

In `translation_quality_models.py`:

1. Change the snapshot import to:

```python
from ....qa.report_snapshot import (
    CHAPTER_STATUS_LABELS,
    RELATIVE_RISK_LABELS,
    RISK_LABELS,
    BookQaReportSnapshot,
    ChapterQaRow,
)
```

2. Replace `COLUMNS` with the block below. The block also declares which fields are completeness fields.

```python
    COLUMNS = (
        ("Глава", "chapter_id"),
        ("Статус", "status"),
        ("Риск", "risk_label"),
        ("Языковая пара", "language_pair"),
        ("Коэффициент", "length_ratio"),
        ("Профиль длины", "profile_status"),
        ("Книжная норма", "book_position"),
        ("Конфликты терминов", "glossary_conflicts"),
        ("Остатки исходника", "untranslated_fragments"),
        ("Возможные пропуски", "possible_gaps"),
        ("Подтверждённые", "confirmed_gaps"),
        ("Языковые дефекты", "language_issues"),
        ("Исправлено", "applied_repairs"),
        ("Время, с", "duration_seconds"),
        ("Токены", "tokens"),
    )
    # Every field here comes from a completeness check.  A book checked for
    # language only has none of them, and a table of zeros reads as a clean result.
    COMPLETENESS_FIELDS = frozenset(
        {
            "language_pair",
            "length_ratio",
            "profile_status",
            "book_position",
            "glossary_conflicts",
            "untranslated_fragments",
            "possible_gaps",
            "confirmed_gaps",
            "language_issues",
            "duration_seconds",
            "tokens",
        }
    )
```

3. Add this method after `row_for_chapter`:

```python
    def hidden_columns(self) -> tuple[int, ...]:
        """Columns that have nothing to show for the current report."""
        if self._snapshot.has_completeness:
            return ()
        return tuple(
            index
            for index, (_title, field_name) in enumerate(self.COLUMNS)
            if field_name in self.COMPLETENESS_FIELDS
        )
```

4. In `data`, make the `DisplayRole` branch start with the status:

```python
        if role == Qt.ItemDataRole.DisplayRole:
            if field_name == "status":
                return CHAPTER_STATUS_LABELS.get(row.status, row.status)
            if field_name == "risk_label" and row.blocked_reason:
```

The rest of `data` stays as it is.

- [ ] **Step 4: Hide the columns in the dialog and describe chapters without metrics**

In `translation_quality_dialog.py`:

1. Extend the import from `.translation_quality_models` with `CHAPTER_STATUS_LABELS`. It is re-exported there because the module imports it.

```python
from .translation_quality_models import (
    CHAPTER_STATUS_LABELS,
    BookQaReportSnapshot,
    ChapterQaTableModel,
    DECISION_LABELS,
)
```

2. In `set_report`, replace the lines from `self.table_model.set_snapshot(snapshot)` to `parts = [f"Глав в отчёте: {len(snapshot.rows)}"]` with:

```python
        self.table_model.set_snapshot(snapshot)
        hidden = set(self.table_model.hidden_columns())
        for column in range(self.table_model.columnCount()):
            self.table.setColumnHidden(column, column in hidden)
        blocked = snapshot.blocked_chapters
        repaired = snapshot.repaired_chapters
        parts = [
            f"Глав в отчёте: {len(snapshot.rows)}",
            f"проверено: {snapshot.checked_count}",
        ]
        if snapshot.deferred_count:
            parts.append(f"отложено: {snapshot.deferred_count}")
```

3. In `_on_selection_changed`, replace the `lines = [...]` list (from `lines = [` to its closing `]`, the line after `f"Риск: {row.risk_label}",`) with:

```python
            lines = [
                f"Глава: {row.chapter_id}",
                f"Статус: {CHAPTER_STATUS_LABELS.get(row.status, row.status)}",
            ]
            if row.checked_at:
                lines.append(f"Проверена: {row.checked_at}")
            if row.has_completeness:
                lines.extend(
                    (
                        f"Языковая пара: {row.language_pair}",
                        f"Коэффициент длины: {row.length_ratio:.2f} — {row.profile_status}",
                        f"Книжная норма: {row.book_position}",
                        f"Возможные пропуски: {row.possible_gaps}, "
                        f"подтверждённые: {row.confirmed_gaps}",
                        f"Конфликты терминов: {row.glossary_conflicts}, "
                        f"остатки исходника: {row.untranslated_fragments}, "
                        f"языковые дефекты: {row.language_issues}",
                    )
                )
            lines.append(f"Исправлено автоматически: {row.applied_repairs}")
            if row.risk_label:
                lines.append(f"Риск: {row.risk_label}")
```

4. In `translation_quality_models.py`, add `"CHAPTER_STATUS_LABELS",` to `__all__`.

- [ ] **Step 5: Run the dialog, controller and log tests**

Run: `.venv/bin/python -m pytest tests/qa/test_translation_quality_dialog.py tests/qa/test_translation_quality_controller.py tests/qa/test_quality_pass_log.py tests/qa/test_translation_qa_performance.py -q`

Expected: PASS. The existing `test_selecting_a_chapter_shows_its_decisions` still finds `chapter-1`, `zh → ru` and `Исправлено`.

- [ ] **Step 6: Commit**

```bash
git add gemini_translator/ui/dialogs/validation_dialogs/translation_quality_models.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py tests/qa/test_translation_quality_dialog.py
git commit -m "feat(ui): show chapter status and hide empty completeness columns

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 3: Verify stage 1 and fast-forward main

**Files:** none changed, unless a check fails.

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider`

Expected: every test passes. If a failure is outside the files this stage changed, run that test alone on `e08fa4d` in a scratch worktree before blaming the stage.

- [ ] **Step 2: Lint the changed files**

Run: `.venv/bin/python -m ruff check gemini_translator/qa/report_snapshot.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_models.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py tests/qa/test_report_snapshot_states.py tests/qa/test_translation_quality_dialog.py`

Expected: `All checks passed!`

- [ ] **Step 3: Mutation check — the report must really use the union**

```bash
.venv/bin/python - <<'EOF'
from pathlib import Path
path = Path("gemini_translator/qa/report_snapshot.py")
text = path.read_text(encoding="utf-8")
mutated = text.replace(
    "set(metrics_by_chapter) | set(states) | set(repairs_by_chapter)",
    "set(metrics_by_chapter)",
)
assert mutated != text
path.write_text(mutated, encoding="utf-8")
EOF
.venv/bin/python -m pytest tests/qa/test_report_snapshot_states.py -q
git restore gemini_translator/qa/report_snapshot.py
git diff --stat
```

Expected: at least 5 tests FAIL while mutated. After the restore, `git diff --stat` prints nothing.

- [ ] **Step 4: Check the main checkout can take a fast-forward**

```bash
ls /Users/rasreo/dev/translatorFork_MOD/.git/hooks | grep -v '\.sample$'
git --no-optional-locks -C /Users/rasreo/dev/translatorFork_MOD rev-parse --abbrev-ref HEAD
git --no-optional-locks -C /Users/rasreo/dev/translatorFork_MOD merge-base --is-ancestor main feature/quality-window-redesign && echo ancestor
git --no-optional-locks -C /Users/rasreo/dev/translatorFork_MOD status --short | awk '{print $2}' | sort > /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/dirty.txt
git diff --name-only main..feature/quality-window-redesign | sort > /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/stage.txt
comm -12 /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/dirty.txt /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/stage.txt
```

Expected:
- The hooks listing is empty, or you read every hook it lists before merging.
- The branch is `main`.
- `ancestor` is printed.
- `comm` prints nothing.

If `comm` prints a file, stop and tell the owner which file overlaps.

- [ ] **Step 5: Fast-forward**

Run: `git -C /Users/rasreo/dev/translatorFork_MOD merge --ff-only feature/quality-window-redesign`

Expected: `Fast-forward`. Do not push.

---

# Stage 2. The window's design

### Task 4: Readable status text, the danger button on tokens, and the status chip

**Files:**
- Modify: `gemini_translator/ui/themes.py`:
  - helpers after `_rgba`, around line 114;
  - `build_theme_palette`, lines 116-185;
  - the danger button block, lines 628-638;
  - the key legend chips, after line 356.
- Test: `tests/test_theme_semantic_tokens.py` (append)

**Interfaces:**
- Consumes: `_mix`, `_hex_to_rgb`, `_rgba`, `build_theme_palette`, `build_stylesheet`, `LIGHT_DEFAULT_THEME_COLORS`, `DARK_DEFAULT_THEME_COLORS`.
- Produces:
  - Palette keys `success_text`, `warning_text`, `danger_text`, `danger_hover_bg`. The stylesheet builder substitutes every palette key as `__KEY__`.
  - Style hook `QLabel#statusChip` with the dynamic property `tone`: `"success"`, `"warning"`, `"danger"` or `"neutral"`. The base rule is the neutral look.
  - `QPushButton#dangerActionButton` styled on tokens, with hover, pressed and disabled states.

Measured before this task, in the light theme: the text of `success` on `success_soft_bg` gives 2.97:1, `warning` gives 3.29:1 and `danger` gives 4.40:1. The dark theme gives 4.71:1 or more for every pair.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_theme_semantic_tokens.py`:

```python
import re

import pytest


_SCHEMES = {
    "light": themes.LIGHT_DEFAULT_THEME_COLORS,
    "dark": themes.DARK_DEFAULT_THEME_COLORS,
}


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _over(color: str, surface: str) -> tuple[int, int, int]:
    """Blend an rgba() token over an opaque surface, the way the screen shows it."""
    match = re.fullmatch(r"rgba\((\d+), (\d+), (\d+), ([0-9.]+)\)", color)
    if match is None:
        return _rgb(color)
    alpha = float(match.group(4))
    under = _rgb(surface)
    return tuple(
        round(alpha * int(match.group(index + 1)) + (1 - alpha) * under[index])
        for index in range(3)
    )


def _ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    """WCAG 2.x contrast ratio, written independently of themes.py."""

    def luminance(rgb):
        def channel(value):
            scaled = value / 255
            return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

        red, green, blue = (channel(value) for value in rgb)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("scheme", sorted(_SCHEMES))
@pytest.mark.parametrize("tone", ["success", "warning", "danger"])
@pytest.mark.parametrize("surface", ["panel_bg", "list_bg", "list_alt_bg"])
def test_status_text_reads_on_its_soft_background(scheme, tone, surface):
    """Фишка статуса и опасная кнопка — не ниже 4.5:1 в обеих темах."""
    palette = themes.build_theme_palette(_SCHEMES[scheme])

    background = _over(palette[f"{tone}_soft_bg"], palette[surface])

    assert _ratio(_rgb(palette[f"{tone}_text"]), background) >= 4.5


@pytest.mark.parametrize("scheme", sorted(_SCHEMES))
def test_the_danger_button_still_reads_under_the_pointer(scheme):
    palette = themes.build_theme_palette(_SCHEMES[scheme])

    background = _over(palette["danger_hover_bg"], palette["panel_bg"])

    assert _ratio(_rgb(palette["danger_text"]), background) >= 4.5


@pytest.mark.parametrize("scheme", sorted(_SCHEMES))
def test_a_neutral_chip_reads(scheme):
    palette = themes.build_theme_palette(_SCHEMES[scheme])

    assert _ratio(_rgb(palette["text_secondary"]), _rgb(palette["chip_bg"])) >= 4.5


def test_the_dark_theme_keeps_its_status_colours():
    """Тёмная тема и так читалась: там цвет текста не должен сдвигаться."""
    palette = themes.build_theme_palette(themes.DARK_DEFAULT_THEME_COLORS)

    for tone in ("success", "warning", "danger"):
        assert palette[f"{tone}_text"] == palette[tone]


def test_the_danger_button_and_the_status_chip_are_built_from_tokens():
    palette = themes.build_theme_palette(themes.LIGHT_DEFAULT_THEME_COLORS)
    sheet = themes.build_stylesheet(themes.LIGHT_DEFAULT_THEME_COLORS)

    danger = sheet.split("QPushButton#dangerActionButton {", 1)[1].split("}", 1)[0]
    assert palette["danger_soft_bg"] in danger
    assert palette["danger_text"] in danger
    assert "#412026" not in sheet
    assert "QPushButton#dangerActionButton:disabled" in sheet
    success = sheet.split('QLabel#statusChip[tone="success"] {', 1)[1].split("}", 1)[0]
    assert palette["success_text"] in success
    assert "__SUCCESS_TEXT__" not in sheet and "__DANGER_HOVER_BG__" not in sheet
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_theme_semantic_tokens.py -v`

Expected: FAIL with `KeyError: 'success_text'`. `test_the_danger_button_and_the_status_chip_are_built_from_tokens` fails too.

- [ ] **Step 3: Add the contrast helpers**

In `gemini_translator/ui/themes.py`, insert right after the `_rgba` function:

```python
def _wcag_luminance(color: str) -> float:
    """Relative luminance as WCAG defines it; `_luminance` above is a cruder blend."""

    def channel(value: int) -> float:
        scaled = value / 255.0
        return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in _hex_to_rgb(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(color_a: str, color_b: str) -> float:
    high, low = sorted((_wcag_luminance(color_a), _wcag_luminance(color_b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# How opaque the soft status fills are at rest and under the pointer.
STATUS_SOFT_ALPHA = 0.14
STATUS_HOVER_ALPHA = 0.22
# A little above WCAG AA's 4.5:1, so rounding in the final blend never drops a
# pair under the line.
READABLE_STATUS_CONTRAST = 4.6


def _readable_status_text(tone: str, surfaces, towards: str, alphas) -> str:
    """Shift a status colour toward the title text until it reads on its own fills.

    The soft fill is the status colour itself at low opacity, so the text is
    checked against that fill over every surface a chip or a danger button
    sits on.  A dark theme's status colours already read and come back as they are.
    """
    for step in range(21):
        candidate = _mix(tone, towards, step * 0.05)
        if all(
            _contrast_ratio(candidate, _mix(surface, tone, alpha))
            >= READABLE_STATUS_CONTRAST
            for surface in surfaces
            for alpha in alphas
        ):
            return candidate
    return towards
```

- [ ] **Step 4: Add the tokens to the palette**

In `build_theme_palette`:

1. Right after `info = _status("#2563c9", "#6aa6ff", window_bg)`, add:

```python
    status_surfaces = (panel_bg, list_bg, list_alt_bg)
    success_text = _readable_status_text(
        success, status_surfaces, title_text, (STATUS_SOFT_ALPHA,)
    )
    warning_text = _readable_status_text(
        warning, status_surfaces, title_text, (STATUS_SOFT_ALPHA,)
    )
    danger_text = _readable_status_text(
        danger, status_surfaces, title_text, (STATUS_SOFT_ALPHA, STATUS_HOVER_ALPHA)
    )
```

2. Replace the six status entries of the returned dict — from `"success": success,` through `"danger_soft_bg": _rgba(danger, 0.14),` — with:

```python
        "success": success,
        "success_soft_bg": _rgba(success, STATUS_SOFT_ALPHA),
        "success_text": success_text,
        "warning": warning,
        "warning_soft_bg": _rgba(warning, STATUS_SOFT_ALPHA),
        "warning_text": warning_text,
        "danger": danger,
        "danger_soft_bg": _rgba(danger, STATUS_SOFT_ALPHA),
        "danger_hover_bg": _rgba(danger, STATUS_HOVER_ALPHA),
        "danger_text": danger_text,
```

- [ ] **Step 5: Put the danger button on tokens**

Replace the two blocks `QPushButton#dangerActionButton { ... }` and `QPushButton#dangerActionButton:hover { ... }` in `STYLESHEET_TEMPLATE` with:

```css
QPushButton#dangerActionButton {
    background-color: __DANGER_SOFT_BG__;
    color: __DANGER_TEXT__;
    border: 1px solid __DANGER__;
    font-weight: 600;
}

QPushButton#dangerActionButton:hover {
    background-color: __DANGER_HOVER_BG__;
    border-color: __DANGER_TEXT__;
}

QPushButton#dangerActionButton:pressed {
    background-color: __DANGER_SOFT_BG__;
    border-color: __DANGER_TEXT__;
}

QPushButton#dangerActionButton:disabled,
QPushButton#dangerActionButton:disabled:hover,
QPushButton#dangerActionButton:disabled:pressed {
    background-color: __INPUT_DISABLED_BG__;
    color: __TEXT_MUTED__;
    border-color: __BORDER__;
}
```

- [ ] **Step 6: Add the status chip**

In `STYLESHEET_TEMPLATE`, right after the block `QLabel#keyLegendChip[state="exhausted"] { ... }`, add:

```css
QLabel#statusChip {
    background-color: __CHIP_BG__;
    border: 1px solid __BORDER_STRONG__;
    border-radius: 10px;
    padding: 4px 10px;
    color: __TEXT_SECONDARY__;
    font-weight: 600;
}

QLabel#statusChip[tone="success"] {
    background-color: __SUCCESS_SOFT_BG__;
    border-color: __SUCCESS__;
    color: __SUCCESS_TEXT__;
}

QLabel#statusChip[tone="warning"] {
    background-color: __WARNING_SOFT_BG__;
    border-color: __WARNING__;
    color: __WARNING_TEXT__;
}

QLabel#statusChip[tone="danger"] {
    background-color: __DANGER_SOFT_BG__;
    border-color: __DANGER__;
    color: __DANGER_TEXT__;
}
```

- [ ] **Step 7: Run the theme tests and the other palette users**

Run: `.venv/bin/python -m pytest tests/test_theme_semantic_tokens.py tests/test_log_widget_batching.py tests/test_glossary_open_perf.py -q`

Expected: PASS.

- [ ] **Step 8: Confirm the light and dark pairs with the design kit's script**

```bash
.venv/bin/python - <<'EOF' > /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/pairs.txt
import re
from gemini_translator.ui import themes
for base in (themes.LIGHT_DEFAULT_THEME_COLORS, themes.DARK_DEFAULT_THEME_COLORS):
    palette = themes.build_theme_palette(base)
    surface = palette["panel_bg"]
    for tone in ("success", "warning", "danger"):
        red, green, blue, alpha = re.fullmatch(r"rgba\((\d+), (\d+), (\d+), ([0-9.]+)\)", palette[f"{tone}_soft_bg"]).groups()
        under = themes._hex_to_rgb(surface)
        blended = themes._rgb_to_hex(tuple(round(float(alpha) * int(value) + (1 - float(alpha)) * under[index]) for index, value in enumerate((red, green, blue))))
        print(palette[f"{tone}_text"], blended)
EOF
while read -r fg bg; do python3 ~/.claude/ux-ui-agent-skills/scripts/contrast.py "$fg" "$bg" | head -3; done < /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/pairs.txt
```

Expected: six pairs, and each prints `Normal text  AA  (4.5:1): PASS`.

- [ ] **Step 9: Commit**

```bash
git add gemini_translator/ui/themes.py tests/test_theme_semantic_tokens.py
git commit -m "feat(ui): readable status text tokens, danger button and status chip on the palette

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 5: Count a provider's working embedding keys

**Files:**
- Modify: `gemini_translator/qa/assembly.py`: add a function after `green_embedding_keys`, around line 885.
- Test: `tests/qa/test_embedding_key_counts.py` (create)

**Interfaces:**
- Consumes: `green_embedding_keys(settings_manager, provider_id, model_id) -> tuple[str, ...]`, and `settings_manager.load_key_statuses()`, whose entries are dicts with `"provider"` and `"key"`.
- Produces: `embedding_key_counts(settings_manager, provider_id: str, model_id: str) -> tuple[int, int]`. It returns how many of the provider's keys work for the model, and how many distinct keys the provider has.

- [ ] **Step 1: Write the failing test**

Create `tests/qa/test_embedding_key_counts.py`:

```python
"""The quality window shows how many of a provider's keys can embed, not a list of keys."""

from __future__ import annotations

from gemini_translator.qa.assembly import embedding_key_counts


class _Manager:
    def __init__(self, keys, blocked=()) -> None:
        self.keys = list(keys)
        self.blocked = set(blocked)

    def load_key_statuses(self):
        return [dict(item) for item in self.keys]

    def is_key_limit_active(self, key_info, model_id):
        return (key_info.get("key"), model_id) in self.blocked


def test_working_keys_are_counted_out_of_the_providers_keys():
    manager = _Manager(
        [
            {"provider": "gemini", "key": "g-1"},
            {"provider": "gemini", "key": "g-2"},
            {"provider": "gemini", "key": "g-3"},
            {"provider": "openrouter", "key": "o-1"},
        ],
        blocked={("g-2", "gemini-embedding-001")},
    )

    assert embedding_key_counts(manager, "gemini", "gemini-embedding-001") == (2, 3)


def test_a_limit_on_another_model_does_not_count_against_embeddings():
    manager = _Manager(
        [{"provider": "gemini", "key": "g-1"}, {"provider": "gemini", "key": "g-2"}],
        blocked={("g-1", "gemini-2.5-flash")},
    )

    assert embedding_key_counts(manager, "gemini", "gemini-embedding-001") == (2, 2)


def test_a_key_listed_twice_counts_once():
    manager = _Manager(
        [{"provider": "gemini", "key": "g-1"}, {"provider": "gemini", "key": " g-1 "}]
    )

    assert embedding_key_counts(manager, "gemini", "gemini-embedding-001") == (1, 1)


def test_nothing_to_read_counts_nothing():
    class _Broken:
        def load_key_statuses(self):
            raise RuntimeError("database is locked")

    assert embedding_key_counts(None, "gemini", "gemini-embedding-001") == (0, 0)
    assert embedding_key_counts(_Manager([]), "", "gemini-embedding-001") == (0, 0)
    assert embedding_key_counts(_Broken(), "gemini", "gemini-embedding-001") == (0, 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_embedding_key_counts.py -v`

Expected: FAIL with `ImportError: cannot import name 'embedding_key_counts'`.

- [ ] **Step 3: Write the implementation**

In `gemini_translator/qa/assembly.py`, insert right after `green_embedding_keys`:

```python
def embedding_key_counts(
    settings_manager, provider_id: str, model_id: str
) -> tuple[int, int]:
    """How many of a provider's keys can embed right now, out of how many it has.

    The quality window shows this instead of a list of keys: semantic checking
    draws on every healthy key of the provider, so the count is what the user
    actually decides on.
    """
    if settings_manager is None or not provider_id:
        return (0, 0)
    try:
        statuses = settings_manager.load_key_statuses() or ()
    except Exception:  # noqa: BLE001 - unreadable statuses mean no key
        return (0, 0)
    provider_keys = {
        str(key_info.get("key") or "").strip()
        for key_info in statuses
        if str(key_info.get("provider") or "") == str(provider_id)
    }
    provider_keys.discard("")
    working = green_embedding_keys(settings_manager, provider_id, model_id)
    return (len(working), len(provider_keys))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/qa/test_embedding_key_counts.py tests/qa/test_embedding_key_pool.py tests/qa/test_manual_qa_setup.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/qa/assembly.py tests/qa/test_embedding_key_counts.py
git commit -m "feat(qa): count a provider's working embedding keys

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 6: Shared building blocks of the window

**Files:**
- Create: `gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py`
- Test: `tests/qa/test_quality_widgets.py` (create)

**Interfaces:**
- Consumes: the style hooks `statusChip`, `projectStatsCard`, `projectCardTitle`, `metricValueLabel`, `mutedLabel`, `pathActionButton`, `projectPathCard`, `heroTitle` and `heroSubtitle` (Task 4 and the existing theme).
- Produces:
  - `make_label(text="", name="", *, wrap=False, parent=None) -> QLabel`. The label is plain text.
  - `make_button(text, name, parent=None) -> QPushButton`.
  - `repolish(widget) -> None`.
  - `StatusChip(text="", tone="neutral", parent=None)`, with `.set_tone(tone)` and `.set_state(text, tone)`.
  - `MetricCard(title, action_text="", parent=None)`, with:
    - attributes `title_label`, `value_label`, `detail_label`, `action_button` (`None` without an action);
    - signal `action_clicked()`;
    - method `.set_values(value, detail)`.
  - `EmptyState(title, text, parent=None)`, with `title_label` and `text_label`.
  - `format_checked_at(value: str) -> str`.
  - `STATUS_TONES`.

- [ ] **Step 1: Write the failing test**

Create `tests/qa/test_quality_widgets.py`:

```python
"""The window's building blocks carry meaning in words and are styled by name only."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from gemini_translator.ui.dialogs.validation_dialogs.quality_widgets import (
    EmptyState,
    MetricCard,
    StatusChip,
    format_checked_at,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_a_status_chip_keeps_only_known_tones(qt_app):
    chip = StatusChip("Готово к проверке", "success")

    assert chip.objectName() == "statusChip"
    assert chip.property("tone") == "success"

    chip.set_state("Идёт проверка", "warning")
    assert (chip.text(), chip.property("tone")) == ("Идёт проверка", "warning")

    chip.set_tone("purple")
    assert chip.property("tone") == "neutral"


def test_a_status_chip_never_renders_markup(qt_app):
    assert StatusChip("<b>x</b>").textFormat() == Qt.TextFormat.PlainText


def test_a_metric_card_shows_its_values_and_reports_its_action(qt_app):
    card = MetricCard("Ждут решения", "Открыть предложения")
    clicks: list[int] = []
    card.action_clicked.connect(lambda: clicks.append(1))

    card.set_values("37", "В главах: 19.")
    card.action_button.click()

    assert card.objectName() == "projectStatsCard"
    assert (card.value_label.text(), card.detail_label.text()) == ("37", "В главах: 19.")
    assert clicks == [1]


def test_a_metric_card_without_an_action_has_no_button(qt_app):
    assert MetricCard("Проверено").action_button is None


def test_the_empty_state_text_is_not_cut_to_one_line(qt_app):
    """Подпись с переносом, поставленная с флагом выравнивания, обрезалась до строки."""
    state = EmptyState(
        "Отчёт пока пуст",
        "Проверенные главы появятся здесь после первого прохода. Проверка идёт "
        "после каждой переведённой главы или по кнопке «Проверить все главы».",
    )
    state.resize(900, 500)
    state.show()
    qt_app.processEvents()
    try:
        label = state.text_label
        assert label.heightForWidth(label.width()) > label.fontMetrics().height()
        assert label.height() >= label.heightForWidth(label.width())
    finally:
        state.close()
        state.deleteLater()


@pytest.mark.parametrize("value", ["", "not a date"])
def test_an_unreadable_date_is_left_out(value):
    assert format_checked_at(value) == ""


def test_a_date_reads_the_way_it_does_in_a_russian_sentence():
    assert format_checked_at("2026-09-09T10:05:00") == "9 сентября 2026, 10:05"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_widgets.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named '...quality_widgets'`.

- [ ] **Step 3: Write the implementation**

Create `gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py`:

```python
# -*- coding: utf-8 -*-
"""Small building blocks of the quality window, made only of the theme's style hooks."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


STATUS_TONES = ("success", "warning", "danger", "neutral")
# Month names in the genitive: the form a date takes inside a Russian sentence.
_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
EMPTY_STATE_TEXT_WIDTH = 560


def make_label(text: str = "", name: str = "", *, wrap: bool = False, parent=None) -> QLabel:
    """A label styled by its name that never renders its text as markup."""
    label = QLabel(text, parent)
    if name:
        label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    return label


def make_button(text: str, name: str, parent=None) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName(name)
    return button


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a property the style rules select on changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def format_checked_at(value: str) -> str:
    """Say when something was checked the way a date reads in a Russian sentence."""
    try:
        moment = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}, {moment:%H:%M}"


class StatusChip(QLabel):
    """A short state in a pill; the words carry the meaning, the colour only helps."""

    def __init__(self, text: str = "", tone: str = "neutral", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("statusChip")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        value = tone if tone in STATUS_TONES else "neutral"
        if self.property("tone") == value:
            return
        self.setProperty("tone", value)
        repolish(self)

    def set_state(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)


class MetricCard(QFrame):
    """One book total: what it counts, the number, and one line of detail."""

    action_clicked = pyqtSignal()

    def __init__(self, title: str, action_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("projectStatsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self.title_label = make_label(title, "projectCardTitle", parent=self)
        self.value_label = make_label("0", "metricValueLabel", parent=self)
        self.detail_label = make_label("", "mutedLabel", wrap=True, parent=self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        self.action_button: QPushButton | None = None
        if action_text:
            self.action_button = make_button(action_text, "pathActionButton", self)
            self.action_button.clicked.connect(self.action_clicked.emit)
            layout.addWidget(self.action_button)
        layout.addStretch(1)

    def set_values(self, value: str, detail: str) -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class EmptyState(QFrame):
    """A whole-tab card that says why nothing is here and what will fill it."""

    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("projectPathCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(10)
        layout.addStretch(1)
        self.title_label = make_label(title, "heroTitle", parent=self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        self.text_label = make_label(text, "heroSubtitle", wrap=True, parent=self)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # A word-wrapped label added to a box layout with an alignment flag gets
        # no height-for-width and is cut to one line.  The text keeps a fixed
        # width, is centred by stretches, and reserves its wrapped height.
        self.text_label.setFixedWidth(EMPTY_STATE_TEXT_WIDTH)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.text_label)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self._fit_text()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_text()

    def _fit_text(self) -> None:
        self.text_label.ensurePolished()
        self.text_label.setMinimumHeight(
            self.text_label.heightForWidth(EMPTY_STATE_TEXT_WIDTH)
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_widgets.py -v`

Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py tests/qa/test_quality_widgets.py
git commit -m "feat(ui): building blocks for the quality window

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 7: The «Настройки» tab

**Files:**
- Create: `gemini_translator/ui/dialogs/validation_dialogs/quality_settings_view.py`
- Test: `tests/qa/test_quality_settings_view.py` (create)

The old dialog is not touched in this task. Task 9 swaps it for the new views and moves its remaining tests over.

**Interfaces:**
- Consumes:
  - `StatusChip`, `make_label` and `make_button` (Task 6).
  - `DEFAULT_EMBEDDING_MODELS` and `local_embedding_model_state` from `qa/assembly.py`.
  - `describe_cometkiwi_setup` and `usable_endpoint`.
  - `CAPABILITY_DESCRIPTIONS`, `QaCapabilityKey` and `QaCapabilitySettings`.
  - `MAX_LANGUAGE_CHUNK_CHARS`.
  - `QaSettings`.
- Produces `QualitySettingsView(settings=None, *, key_counter=None, parent=None)`:
  - The key counter's signature is `key_counter(provider_id: str, model_id: str) -> tuple[int, int]`.
  - Signals: `settings_changed(object)`, `embedding_test_requested(object)`.
  - Methods: `qa_settings() -> QaSettings`, `apply_settings(settings)`, `set_embedding_result(text)`, `_check_cometkiwi_endpoint()`.
  - Widgets for tests:
    - «После каждой главы»: `completeness_check`, `repair_omissions_check`, `language_check`, `repair_language_check`, `final_pass_check`, `language_chunk_spin`.
    - «Смысловое сравнение»: `embedding_provider_combo`, `embedding_keys_caption`, `embedding_keys_chip`, `embedding_keys_label`, `embedding_legacy_reset_button`, `embedding_base_url_edit`, `embedding_key_edit`, `embedding_model_combo`, `embedding_test_button`, `embedding_result_label`.
    - «Оценка на ПК (CometKiwi)»: `cometkiwi_enabled_check`, `cometkiwi_endpoint_edit`, `cometkiwi_check_button`, `cometkiwi_model_edit`, `cometkiwi_license_check`, `cometkiwi_status_label`.
    - «Дополнительные анализаторы»: `capability_checks` (keys `RAZDEL`, `LANGUAGE_TOOL`, `SLOVNET`), `language_tool_endpoint_edit`, `capability_status_label`.
  - Module constants: `COMETKIWI_CHECK_TIMEOUT_SECONDS = 5.0`, `COMETKIWI_MODEL_NAME_CHARS = 80`.

- [ ] **Step 1: Write the failing test**

Create `tests/qa/test_quality_settings_view.py`:

```python
"""The settings tab: four cards, provider-level keys, and every value round-trips."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QLineEdit

from gemini_translator.qa.capabilities import QaCapabilityKey, QaCapabilitySettings
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui.dialogs.validation_dialogs.quality_settings_view import (
    QualitySettingsView,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    import gemini_translator.api.config as api_config

    monkeypatch.setattr(
        api_config,
        "api_providers_view",
        lambda: {
            "gemini": {"display_name": "Google Gemini Free"},
            "openrouter": {"display_name": "OpenRouter"},
        },
    )


def _select(view: QualitySettingsView, provider: str) -> None:
    view.embedding_provider_combo.setCurrentIndex(
        view.embedding_provider_combo.findData(provider)
    )


def _published(view: QualitySettingsView) -> list[QaSettings]:
    published: list[QaSettings] = []
    view.settings_changed.connect(published.append)
    return published


def test_the_four_cards_come_in_order(qt_app):
    view = QualitySettingsView(QaSettings())

    titles = [
        label.text()
        for label in view.findChildren(QtWidgets.QLabel)
        if label.objectName() == "projectCardTitle"
    ]

    assert titles == [
        "После каждой главы",
        "Смысловое сравнение",
        "Оценка на ПК (CometKiwi)",
        "Дополнительные анализаторы",
    ]


def test_stage_switches_round_trip(qt_app):
    view = QualitySettingsView(
        QaSettings(
            check_completeness_after_chapter=False,
            auto_repair_confirmed_omissions=False,
            capabilities=QaCapabilitySettings(slovnet_enabled=True),
        )
    )

    assert view.completeness_check.isChecked() is False
    assert view.repair_omissions_check.isChecked() is False
    settings = view.qa_settings()
    assert settings.check_completeness_after_chapter is False
    assert settings.capabilities.slovnet_enabled is True
    assert settings.capabilities.razdel_enabled is True


def test_an_edit_is_published(qt_app):
    view = QualitySettingsView(QaSettings())
    published = _published(view)

    view.language_check.setChecked(False)

    assert published and published[-1].check_language_after_chapter is False


def test_loading_settings_publishes_nothing(qt_app):
    view = QualitySettingsView(QaSettings())
    published = _published(view)

    view.apply_settings(
        QaSettings(
            embedding_provider="openai_compatible",
            embedding_api_key="sk-1",
            embedding_base_url="https://example.test/v1",
        )
    )

    assert published == []
    assert view.embedding_key_edit.text() == "sk-1"


def test_the_gemini_key_chip_shows_what_the_counter_reports(qt_app):
    calls: list[tuple[str, str]] = []

    def counter(provider_id, model_id):
        calls.append((provider_id, model_id))
        return (5, 7)

    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini"),
        key_counter=counter,
    )

    assert view.embedding_keys_chip.text() == "5 из 7 работают"
    assert view.embedding_keys_chip.property("tone") == "success"
    assert not view.embedding_keys_chip.isHidden()
    assert view.embedding_keys_label.text() == "все рабочие ключи Gemini"
    assert calls[-1] == ("gemini", "gemini-embedding-001")


def test_no_working_gemini_key_turns_the_chip_red(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini"),
        key_counter=lambda provider_id, model_id: (0, 3),
    )

    assert view.embedding_keys_chip.text() == "0 из 3 работают"
    assert view.embedding_keys_chip.property("tone") == "danger"


def test_choosing_gemini_writes_the_provider_not_a_key(qt_app):
    view = QualitySettingsView(QaSettings(), key_counter=lambda provider_id, model_id: (1, 1))

    _select(view, "gemini")
    settings = view.qa_settings()

    assert (
        settings.embedding_provider,
        settings.embedding_key_provider,
        settings.embedding_api_key,
    ) == ("gemini", "gemini", "")
    assert settings.embedding_setup_problem() == ""


def test_openai_compatible_writes_its_own_key_and_address(qt_app):
    view = QualitySettingsView(QaSettings())

    _select(view, "openai_compatible")
    models = [
        view.embedding_model_combo.itemText(index)
        for index in range(view.embedding_model_combo.count())
    ]
    view.embedding_key_edit.setText("sk-own-key")
    view.embedding_base_url_edit.setText("https://api.openai.com/v1")
    view.embedding_model_combo.setEditText("text-embedding-3-large")
    settings = view.qa_settings()

    assert "text-embedding-3-small" in models
    assert not view.embedding_key_edit.isHidden()
    assert not view.embedding_base_url_edit.isHidden()
    assert settings.embedding_provider == "openai_compatible"
    assert settings.embedding_api_key == "sk-own-key"
    assert settings.embedding_key_provider == ""
    assert settings.embedding_base_url == "https://api.openai.com/v1"
    assert settings.embedding_model == "text-embedding-3-large"
    assert settings.embedding_setup_problem() == ""


def test_the_address_and_own_key_hide_for_other_providers(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="gemini")
    )

    assert view.embedding_key_edit.isHidden()
    assert view.embedding_base_url_edit.isHidden()


def test_the_own_key_is_typed_hidden(qt_app):
    view = QualitySettingsView(QaSettings())

    assert view.embedding_key_edit.echoMode() == QLineEdit.EchoMode.Password


def test_a_legacy_key_provider_is_kept_until_the_user_chooses(qt_app):
    """Ранее выбранные ключи другого провайдера не пропадают молча."""
    view = QualitySettingsView(
        QaSettings(embedding_provider="auto", embedding_key_provider="openrouter")
    )

    assert view.embedding_keys_label.text() == "ключи провайдера OpenRouter, настроено ранее"
    assert not view.embedding_legacy_reset_button.isHidden()
    view.language_check.setChecked(False)
    assert view.qa_settings().embedding_key_provider == "openrouter"

    _select(view, "gemini")

    assert view.qa_settings().embedding_key_provider == "gemini"
    assert view.embedding_legacy_reset_button.isHidden()


def test_typing_an_own_key_replaces_a_legacy_key_provider(qt_app):
    view = QualitySettingsView(
        QaSettings(
            embedding_provider="openai_compatible",
            embedding_key_provider="openrouter",
            embedding_base_url="https://openrouter.ai/api/v1",
        )
    )
    assert view.qa_settings().embedding_key_provider == "openrouter"

    view.embedding_key_edit.setText("sk-own")
    settings = view.qa_settings()

    assert (settings.embedding_key_provider, settings.embedding_api_key) == ("", "sk-own")


def test_the_reset_button_forgets_a_legacy_key_provider(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_key_provider="openrouter"),
        key_counter=lambda provider_id, model_id: (2, 2),
    )
    published = _published(view)

    view.embedding_legacy_reset_button.click()

    assert published[-1].embedding_key_provider == "gemini"
    assert view.embedding_keys_chip.text() == "2 из 2 работают"


def test_a_key_once_picked_for_gemini_is_replaced_on_the_first_edit(qt_app):
    view = QualitySettingsView(
        QaSettings(embedding_provider="gemini", embedding_api_key="AIza-picked-from-a-list")
    )
    published = _published(view)

    view.language_check.setChecked(False)

    assert published[-1].embedding_api_key == ""
    assert published[-1].embedding_key_provider == "gemini"


def test_auto_says_the_session_keys_are_used(qt_app):
    view = QualitySettingsView(QaSettings())

    assert view.embedding_keys_label.text() == "ключи текущей сессии перевода"
    assert view.embedding_keys_chip.isHidden()


def test_an_incomplete_setup_is_explained_in_the_card(qt_app):
    view = QualitySettingsView(QaSettings())

    _select(view, "openai_compatible")

    assert "ключ" in view.embedding_result_label.text().lower()


def test_the_probe_asks_with_the_current_settings_and_its_answer_lands_in_the_card(qt_app):
    view = QualitySettingsView(QaSettings())
    asked: list[QaSettings] = []
    view.embedding_test_requested.connect(asked.append)

    view.embedding_test_button.click()
    view.set_embedding_result("Подключение работает: gemini, модель x, 3 измерений.")

    assert asked and asked[-1].embedding_provider == "auto"
    assert view.embedding_result_label.text().startswith("Подключение работает")


def test_cometkiwi_lives_in_its_own_card_and_round_trips(qt_app):
    view = QualitySettingsView(
        QaSettings(
            capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
            cometkiwi_endpoint="http://192.168.1.50:8765",
            cometkiwi_model="wmt22-cometkiwi-da",
            cometkiwi_license_accepted=True,
        )
    )

    assert view.cometkiwi_enabled_check.isChecked()
    assert QaCapabilityKey.COMETKIWI not in view.capability_checks

    view.cometkiwi_enabled_check.setChecked(False)

    assert view.qa_settings().capabilities.cometkiwi_enabled is False


def test_values_the_window_does_not_show_survive_an_edit(qt_app):
    """Старое окно сбрасывало эти два значения к умолчаниям при каждой правке."""
    view = QualitySettingsView(
        QaSettings(batch_concurrency=3, auto_fix_language_categories=("typo",))
    )
    published = _published(view)

    view.final_pass_check.setChecked(False)

    assert published[-1].batch_concurrency == 3
    assert published[-1].auto_fix_language_categories == ("typo",)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_settings_view.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named '...quality_settings_view'`.

- [ ] **Step 3: Write the implementation**

Create `gemini_translator/ui/dialogs/validation_dialogs/quality_settings_view.py`. `_check_cometkiwi_endpoint` and its comments are carried over unchanged from `translation_quality_dialog.py` lines 722-810. Only the attribute owner changes.

```python
# -*- coding: utf-8 -*-
"""The «Настройки» tab of the quality window: four cards over one QaSettings."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ....qa.assembly import DEFAULT_EMBEDDING_MODELS, local_embedding_model_state
from ....qa.capabilities import (
    CAPABILITY_DESCRIPTIONS,
    QaCapabilityKey,
    QaCapabilitySettings,
)
from ....qa.estimators.cometkiwi_client import usable_endpoint
from ....qa.estimators.cometkiwi_model_manager import describe_cometkiwi_setup
from ....qa.language_validation import MAX_LANGUAGE_CHUNK_CHARS
from ....qa.settings import QaSettings
from .quality_widgets import StatusChip, make_button, make_label


EMBEDDING_PROVIDER_CHOICES = (
    ("Автоматически", "auto"),
    ("Gemini", "gemini"),
    ("OpenAI-совместимый", "openai_compatible"),
    ("Локальная модель", "local_onnx"),
)
EMBEDDING_MODEL_SUGGESTIONS = {
    "auto": ("gemini-embedding-001", "text-embedding-004"),
    "gemini": ("gemini-embedding-001", "text-embedding-004"),
    "openai_compatible": (
        "text-embedding-3-small",
        "text-embedding-3-large",
        "text-embedding-ada-002",
    ),
    "local_onnx": ("multilingual-e5-small", "multilingual-e5-base"),
}
# The analyzers card; CometKiwi has a card of its own.
ANALYZER_ORDER = (
    QaCapabilityKey.RAZDEL,
    QaCapabilityKey.LANGUAGE_TOOL,
    QaCapabilityKey.SLOVNET,
)
# The provider whose keys «Gemini» means.  Semantic checking draws on every
# healthy key of it, so the window names the provider and never one key.
GEMINI_KEY_PROVIDER = "gemini"

# How long «Проверить связь» waits for the scoring server. The check runs on the
# GUI thread, and a server that is up answers /health in milliseconds.
COMETKIWI_CHECK_TIMEOUT_SECONDS = 5.0
# How much of each model name the check's warning shows: one of the two names
# is whatever an unauthenticated server chose to send.
COMETKIWI_MODEL_NAME_CHARS = 80


class QualitySettingsView(QWidget):
    """Every quality setting the user decides on, in four cards."""

    settings_changed = pyqtSignal(object)
    embedding_test_requested = pyqtSignal(object)

    def __init__(
        self, settings: QaSettings | None = None, *, key_counter=None, parent=None
    ) -> None:
        super().__init__(parent)
        self._settings = settings or QaSettings()
        self._key_counter = key_counter
        # A key provider an earlier version of this window saved for another
        # provider than the one it now names; kept until the user decides.
        self._legacy_key_provider = ""
        # A key saved for «Автоматически» or the local model, which have no
        # key field any more: passed through untouched rather than dropped.
        self._kept_api_key = ""
        self._cometkiwi_model_status = None
        self._cometkiwi_last_seconds: float | None = None
        self._loading = True

        content = QWidget(self)
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 10, 0, 0)
        grid.setSpacing(10)
        grid.addWidget(self._build_stage_card(content), 0, 0)
        grid.addWidget(self._build_embedding_card(content), 0, 1)
        grid.addWidget(self._build_cometkiwi_card(content), 1, 0)
        grid.addWidget(self._build_analyzers_card(content), 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

        self.apply_settings(self._settings)

    # -- cards -------------------------------------------------------------

    @staticmethod
    def _card(parent, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("projectPathCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(make_label(title, "projectCardTitle", parent=card))
        return card, layout

    @staticmethod
    def _form() -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        return grid

    def _build_stage_card(self, parent) -> QFrame:
        card, layout = self._card(parent, "После каждой главы")
        self.language_check = QCheckBox("Проверять язык перевода", card)
        self.repair_language_check = QCheckBox(
            "Исправлять объективные языковые дефекты", card
        )
        self.completeness_check = QCheckBox("Проверять полноту перевода", card)
        self.repair_omissions_check = QCheckBox(
            "Допереводить подтверждённые пропуски", card
        )
        self.final_pass_check = QCheckBox(
            "Итоговый проход по книге в конце сессии", card
        )
        for widget in (
            self.language_check,
            self.repair_language_check,
            self.completeness_check,
            self.repair_omissions_check,
            self.final_pass_check,
        ):
            widget.toggled.connect(self._on_settings_edited)
            layout.addWidget(widget)

        # A chapter is diagnosed piece by piece, and the piece size is what the
        # check costs: a larger piece is fewer requests over the same text.
        chunk_row = QHBoxLayout()
        chunk_row.setSpacing(8)
        chunk_row.addWidget(make_label("Размер куска проверки", "mutedLabel", parent=card))
        self.language_chunk_spin = QSpinBox(card)
        self.language_chunk_spin.setRange(0, MAX_LANGUAGE_CHUNK_CHARS)
        self.language_chunk_spin.setSingleStep(1000)
        self.language_chunk_spin.setSuffix(" символов")
        # The lowest position is not a size but the absence of one: the check
        # then asks the project how much it translates in, and matches it.
        self.language_chunk_spin.setSpecialValueText("как при переводе")
        self.language_chunk_spin.setToolTip(
            "Сколько текста главы уходит в один запрос языковой проверки:\n"
            "перевод и оригинал вместе.\n"
            "«Как при переводе» — тот же размер, которым переводилась книга.\n"
            "Больше — меньше запросов на главу и дешевле проверка;\n"
            "меньше — модель разбирает каждый кусок внимательнее."
        )
        self.language_chunk_spin.valueChanged.connect(self._on_settings_edited)
        chunk_row.addWidget(self.language_chunk_spin)
        chunk_row.addStretch(1)
        layout.addLayout(chunk_row)
        layout.addStretch(1)
        return card

    def _build_embedding_card(self, parent) -> QFrame:
        card, layout = self._card(parent, "Смысловое сравнение")
        grid = self._form()

        self.embedding_provider_combo = QComboBox(card)
        for label, value in EMBEDDING_PROVIDER_CHOICES:
            self.embedding_provider_combo.addItem(label, value)
        self.embedding_provider_combo.currentIndexChanged.connect(
            self._on_embedding_provider_changed
        )
        grid.addWidget(make_label("Провайдер", "mutedLabel", parent=card), 0, 0)
        grid.addWidget(self.embedding_provider_combo, 0, 1)

        self.embedding_keys_caption = make_label("Ключи", "mutedLabel", parent=card)
        keys_row = QHBoxLayout()
        keys_row.setSpacing(8)
        self.embedding_keys_chip = StatusChip("", "neutral", card)
        self.embedding_keys_label = make_label("", "mutedLabel", wrap=True, parent=card)
        self.embedding_legacy_reset_button = make_button("Сбросить", "ghostActionButton", card)
        self.embedding_legacy_reset_button.clicked.connect(self._forget_legacy_key_provider)
        keys_row.addWidget(self.embedding_keys_chip)
        keys_row.addWidget(self.embedding_keys_label, 1)
        keys_row.addWidget(self.embedding_legacy_reset_button)
        grid.addWidget(self.embedding_keys_caption, 1, 0)
        grid.addLayout(keys_row, 1, 1)

        self.embedding_base_url_caption = make_label("Адрес сервиса", "mutedLabel", parent=card)
        self.embedding_base_url_edit = QLineEdit(card)
        self.embedding_base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        self.embedding_base_url_edit.textChanged.connect(self._on_settings_edited)
        grid.addWidget(self.embedding_base_url_caption, 2, 0)
        grid.addWidget(self.embedding_base_url_edit, 2, 1)

        self.embedding_key_caption = make_label("Свой ключ", "mutedLabel", parent=card)
        self.embedding_key_edit = QLineEdit(card)
        self.embedding_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.embedding_key_edit.setPlaceholderText("ключ сервиса эмбеддингов")
        self.embedding_key_edit.textChanged.connect(self._on_own_key_edited)
        grid.addWidget(self.embedding_key_caption, 3, 0)
        grid.addWidget(self.embedding_key_edit, 3, 1)

        self.embedding_model_combo = QComboBox(card)
        self.embedding_model_combo.setEditable(True)
        self.embedding_model_combo.currentTextChanged.connect(self._on_settings_edited)
        # Counting reads every key's status, so it follows a chosen or finished
        # model name rather than each keystroke.
        self.embedding_model_combo.currentIndexChanged.connect(self._refresh_embedding_keys)
        self.embedding_model_combo.lineEdit().editingFinished.connect(
            self._refresh_embedding_keys
        )
        grid.addWidget(make_label("Модель", "mutedLabel", parent=card), 4, 0)
        grid.addWidget(self.embedding_model_combo, 4, 1)
        layout.addLayout(grid)

        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        self.embedding_test_button = make_button(
            "Проверить подключение", "compactActionButton", card
        )
        self.embedding_test_button.clicked.connect(
            lambda: self.embedding_test_requested.emit(self.qa_settings())
        )
        self.embedding_result_label = make_label("", "helperLabel", wrap=True, parent=card)
        test_row.addWidget(self.embedding_test_button)
        test_row.addWidget(self.embedding_result_label, 1)
        layout.addLayout(test_row)
        layout.addStretch(1)
        return card

    def _build_cometkiwi_card(self, parent) -> QFrame:
        card, layout = self._card(parent, "Оценка на ПК (CometKiwi)")
        self.cometkiwi_enabled_check = QCheckBox(
            "Считать оценку качества на компьютере с видеокартой", card
        )
        self.cometkiwi_enabled_check.setToolTip(
            _capability_tooltip(CAPABILITY_DESCRIPTIONS[QaCapabilityKey.COMETKIWI])
        )
        self.cometkiwi_enabled_check.toggled.connect(self._on_settings_edited)
        layout.addWidget(self.cometkiwi_enabled_check)

        grid = self._form()
        address_row = QHBoxLayout()
        address_row.setSpacing(8)
        self.cometkiwi_endpoint_edit = QLineEdit(card)
        self.cometkiwi_endpoint_edit.setPlaceholderText(
            "http://192.168.1.50:8765 — пусто: считать на этом компьютере"
        )
        # Reported like every other editable field. Without it the readiness
        # labels, which read self._settings rather than the widgets, keep
        # calling CometKiwi unconfigured after an address is typed.
        self.cometkiwi_endpoint_edit.textChanged.connect(self._on_settings_edited)
        self.cometkiwi_check_button = make_button("Проверить связь", "compactActionButton", card)
        # Deliberately not tied to the CometKiwi checkbox: disabling the button
        # while the capability is off would make click() silently do nothing.
        self.cometkiwi_check_button.clicked.connect(self._check_cometkiwi_endpoint)
        address_row.addWidget(self.cometkiwi_endpoint_edit, 1)
        address_row.addWidget(self.cometkiwi_check_button)
        grid.addWidget(make_label("Адрес ПК", "mutedLabel", parent=card), 0, 0)
        grid.addLayout(address_row, 0, 1)

        # The model name and the licence are what unsatisfied_requirements() asks
        # of CometKiwi besides a runner or an address, and nothing else in the
        # application sets them.
        self.cometkiwi_model_edit = QLineEdit(card)
        self.cometkiwi_model_edit.setPlaceholderText("wmt22-cometkiwi-da")
        self.cometkiwi_model_edit.setToolTip(
            "Для счёта на этом компьютере — имя папки с весами.\n"
            "«Проверить связь» предупредит, если на ПК запущена другая модель."
        )
        self.cometkiwi_model_edit.textChanged.connect(self._on_settings_edited)
        grid.addWidget(make_label("Модель", "mutedLabel", parent=card), 1, 0)
        grid.addWidget(self.cometkiwi_model_edit, 1, 1)
        layout.addLayout(grid)

        self.cometkiwi_license_check = QCheckBox(
            "Принимаю лицензию модели CC BY-NC-SA 4.0 — "
            "только некоммерческое использование",
            card,
        )
        self.cometkiwi_license_check.toggled.connect(self._on_settings_edited)
        layout.addWidget(self.cometkiwi_license_check)

        # It repeats what the scoring server says about itself, and that server
        # is unauthenticated: make_label keeps it plain text, never markup.
        self.cometkiwi_status_label = make_label("", "helperLabel", wrap=True, parent=card)
        layout.addWidget(self.cometkiwi_status_label)
        layout.addStretch(1)
        return card

    def _build_analyzers_card(self, parent) -> QFrame:
        card, layout = self._card(parent, "Дополнительные анализаторы")
        self.capability_checks: dict[QaCapabilityKey, QCheckBox] = {}
        for key in ANALYZER_ORDER:
            description = CAPABILITY_DESCRIPTIONS[key]
            check = QCheckBox(description.title, card)
            check.setToolTip(_capability_tooltip(description))
            check.toggled.connect(self._on_settings_edited)
            layout.addWidget(check)
            layout.addWidget(make_label(description.summary, "mutedLabel", wrap=True, parent=card))
            self.capability_checks[key] = check

        endpoint_row = QHBoxLayout()
        endpoint_row.setSpacing(8)
        endpoint_row.addWidget(make_label("Адрес LanguageTool", "mutedLabel", parent=card))
        self.language_tool_endpoint_edit = QLineEdit(card)
        self.language_tool_endpoint_edit.setPlaceholderText(
            "например http://localhost:8081/v2/check"
        )
        self.language_tool_endpoint_edit.textChanged.connect(self._on_settings_edited)
        endpoint_row.addWidget(self.language_tool_endpoint_edit, 1)
        layout.addLayout(endpoint_row)
        self.capability_checks[QaCapabilityKey.LANGUAGE_TOOL].toggled.connect(
            self.language_tool_endpoint_edit.setEnabled
        )

        self.capability_status_label = make_label("", "helperLabel", wrap=True, parent=card)
        layout.addWidget(self.capability_status_label)
        layout.addStretch(1)
        return card

    # -- public API --------------------------------------------------------

    def apply_settings(self, settings: QaSettings) -> None:
        """Show one QaSettings in the widgets without reporting it as an edit."""
        self._loading = True
        try:
            self._settings = settings
            provider = settings.embedding_provider
            expected = GEMINI_KEY_PROVIDER if provider == "gemini" else ""
            self._legacy_key_provider = (
                settings.embedding_key_provider
                if settings.embedding_key_provider not in ("", expected)
                else ""
            )
            self._kept_api_key = (
                settings.embedding_api_key if provider in ("auto", "local_onnx") else ""
            )

            self.completeness_check.setChecked(settings.check_completeness_after_chapter)
            self.repair_omissions_check.setChecked(settings.auto_repair_confirmed_omissions)
            self.language_check.setChecked(settings.check_language_after_chapter)
            self.language_chunk_spin.setValue(settings.language_chunk_chars)
            self.repair_language_check.setChecked(
                settings.auto_repair_objective_language_issues
            )
            self.final_pass_check.setChecked(settings.final_book_pass)

            index = self.embedding_provider_combo.findData(provider)
            self.embedding_provider_combo.setCurrentIndex(max(index, 0))
            self._reload_model_choices(provider, settings.embedding_model)
            self.embedding_base_url_edit.setText(settings.embedding_base_url)
            self.embedding_key_edit.setText(
                settings.embedding_api_key if provider == "openai_compatible" else ""
            )

            for key, check in self.capability_checks.items():
                check.setChecked(getattr(settings.capabilities, f"{key.value}_enabled"))
            self.language_tool_endpoint_edit.setText(settings.language_tool_endpoint)
            self.language_tool_endpoint_edit.setEnabled(
                settings.capabilities.language_tool_enabled
            )
            self.cometkiwi_enabled_check.setChecked(settings.capabilities.cometkiwi_enabled)
            self.cometkiwi_endpoint_edit.setText(settings.cometkiwi_endpoint)
            self.cometkiwi_model_edit.setText(settings.cometkiwi_model)
            self.cometkiwi_license_check.setChecked(settings.cometkiwi_license_accepted)
        finally:
            self._loading = False
        self._refresh_embedding_rows()
        self._refresh_setup_warnings()

    def qa_settings(self) -> QaSettings:
        """Return the settings exactly as the widgets currently express them."""
        settings = self._settings
        provider = self._provider()
        if provider == "openai_compatible":
            api_key = self.embedding_key_edit.text().strip()
        elif provider == "gemini":
            # Every working Gemini key, never one picked by hand: a key chosen
            # from a list in an earlier version of this window ends here.
            api_key = ""
        else:
            api_key = self._kept_api_key
        key_provider = self._legacy_key_provider or (
            GEMINI_KEY_PROVIDER if provider == "gemini" else ""
        )
        return QaSettings(
            check_completeness_after_chapter=self.completeness_check.isChecked(),
            auto_repair_confirmed_omissions=self.repair_omissions_check.isChecked(),
            check_language_after_chapter=self.language_check.isChecked(),
            auto_repair_objective_language_issues=self.repair_language_check.isChecked(),
            auto_fix_language_categories=settings.auto_fix_language_categories,
            embedding_provider=provider,
            embedding_model=self.embedding_model_combo.currentText().strip(),
            embedding_api_key=api_key,
            embedding_key_provider=key_provider,
            embedding_base_url=self.embedding_base_url_edit.text().strip(),
            correction_model_mode=settings.correction_model_mode,
            correction_provider=settings.correction_provider,
            correction_model=settings.correction_model,
            final_book_pass=self.final_pass_check.isChecked(),
            batch_concurrency=settings.batch_concurrency,
            language_chunk_chars=self.language_chunk_spin.value(),
            capabilities=QaCapabilitySettings(
                razdel_enabled=self.capability_checks[QaCapabilityKey.RAZDEL].isChecked(),
                language_tool_enabled=self.capability_checks[
                    QaCapabilityKey.LANGUAGE_TOOL
                ].isChecked(),
                slovnet_enabled=self.capability_checks[QaCapabilityKey.SLOVNET].isChecked(),
                cometkiwi_enabled=self.cometkiwi_enabled_check.isChecked(),
            ),
            language_tool_endpoint=self.language_tool_endpoint_edit.text().strip(),
            language_tool_mode=settings.language_tool_mode,
            language_tool_disabled_rules=settings.language_tool_disabled_rules,
            slovnet_cpu_threads=settings.slovnet_cpu_threads,
            slovnet_batch_size=settings.slovnet_batch_size,
            cometkiwi_runner_path=settings.cometkiwi_runner_path,
            cometkiwi_model=self.cometkiwi_model_edit.text().strip(),
            cometkiwi_device=settings.cometkiwi_device,
            cometkiwi_endpoint=self.cometkiwi_endpoint_edit.text().strip(),
            cometkiwi_license_accepted=self.cometkiwi_license_check.isChecked(),
        )

    def set_embedding_result(self, text: str) -> None:
        """Show what the last connection check answered."""
        self.embedding_result_label.setText(str(text or ""))

    # -- embeddings --------------------------------------------------------

    def _provider(self) -> str:
        return str(self.embedding_provider_combo.currentData() or "auto")

    def _on_embedding_provider_changed(self) -> None:
        if not self._loading:
            # Choosing a provider is a decision about keys: whatever an older
            # version of this window saved stops applying from here on.
            self._legacy_key_provider = ""
            self._kept_api_key = ""
        self._reload_model_choices(
            self._provider(), self.embedding_model_combo.currentText().strip()
        )
        self._refresh_embedding_rows()
        self._on_settings_edited()

    def _on_own_key_edited(self, text: str) -> None:
        if text.strip() and not self._loading and self._legacy_key_provider:
            self._legacy_key_provider = ""
            self._refresh_embedding_rows()
        self._on_settings_edited()

    def _forget_legacy_key_provider(self) -> None:
        self._legacy_key_provider = ""
        self._refresh_embedding_rows()
        self._on_settings_edited()

    def _reload_model_choices(self, provider: str, selected_model: str) -> None:
        suggestions = EMBEDDING_MODEL_SUGGESTIONS.get(provider, ())
        self.embedding_model_combo.blockSignals(True)
        self.embedding_model_combo.clear()
        for name in suggestions:
            self.embedding_model_combo.addItem(name)
        # An empty model field would silently fall back to a default the user
        # never saw; show the one that will actually be used.
        self.embedding_model_combo.setEditText(
            selected_model or (suggestions[0] if suggestions else "")
        )
        self.embedding_model_combo.blockSignals(False)

    def _refresh_embedding_rows(self) -> None:
        openai = self._provider() == "openai_compatible"
        for widget in (
            self.embedding_base_url_caption,
            self.embedding_base_url_edit,
            self.embedding_key_caption,
            self.embedding_key_edit,
        ):
            widget.setVisible(openai)
        self.embedding_legacy_reset_button.setVisible(bool(self._legacy_key_provider))
        self._refresh_embedding_keys()

    def _refresh_embedding_keys(self, *_args) -> None:
        provider = self._provider()
        self.embedding_keys_chip.setVisible(False)
        self.embedding_keys_caption.setText("Ключи")
        if self._legacy_key_provider:
            self.embedding_keys_label.setText(
                f"ключи провайдера {_provider_display_name(self._legacy_key_provider)}, "
                "настроено ранее"
            )
            return
        if provider == "gemini":
            self.embedding_keys_label.setText("все рабочие ключи Gemini")
            counts = self._count_gemini_keys()
            if counts is not None:
                working, total = counts
                self.embedding_keys_chip.set_state(
                    f"{working} из {total} работают", "success" if working else "danger"
                )
                self.embedding_keys_chip.setVisible(True)
            return
        if provider == "openai_compatible":
            self.embedding_keys_label.setText("свой ключ и адрес сервиса")
            return
        if provider == "local_onnx":
            self.embedding_keys_caption.setText("Модель на диске")
            self.embedding_keys_label.setText(_local_model_state())
            return
        self.embedding_keys_label.setText("ключи текущей сессии перевода")

    def _count_gemini_keys(self) -> tuple[int, int] | None:
        if not callable(self._key_counter):
            return None
        model = (
            self.embedding_model_combo.currentText().strip()
            or DEFAULT_EMBEDDING_MODELS["gemini"]
        )
        try:
            working, total = self._key_counter(GEMINI_KEY_PROVIDER, model)
        except Exception:  # noqa: BLE001 - a key count never keeps the window closed
            return None
        return int(working), int(total)

    # -- edits and readiness -----------------------------------------------

    def _on_settings_edited(self, *_args) -> None:
        if self._loading:
            return
        self._settings = self.qa_settings()
        self._refresh_setup_warnings()
        self.settings_changed.emit(self._settings)

    def _refresh_setup_warnings(self) -> None:
        self.embedding_result_label.setText(self._settings.embedding_setup_problem())
        missing = self._settings.unsatisfied_requirements()
        self.capability_status_label.setText(
            "Не настроены и поэтому выключены: " + ", ".join(missing) if missing else ""
        )
        self.cometkiwi_status_label.setText(
            describe_cometkiwi_setup(
                self._settings,
                self._cometkiwi_model_status,
                self._cometkiwi_last_seconds,
            )
        )

    def _check_cometkiwi_endpoint(self) -> None:
        """Ask the scoring server what it is, without loading anything there."""
        endpoint = self.cometkiwi_endpoint_edit.text().strip()
        if not endpoint:
            self.cometkiwi_status_label.setText(
                "Адрес пуст: оценка будет считаться на этом компьютере."
            )
            return
        base_url = endpoint.rstrip("/")
        # The rule scoring itself applies. An address scoring refuses as
        # endpoint_invalid is named as such and never dialled: urllib would
        # read "192.168.1.50:8765" as an unknown scheme and blame the firewall.
        if not usable_endpoint(base_url):
            self.cometkiwi_status_label.setText(
                "Адрес не разобран: нужен вид http://host:port."
            )
            return
        import json
        import urllib.error
        import urllib.request

        # No proxy of any kind, the system's included. Scoring reaches the PC
        # through an aiohttp session that ignores them all; a check that took
        # another route could fail where scoring works, or pass where it fails.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(
                base_url + "/health", timeout=COMETKIWI_CHECK_TIMEOUT_SECONDS
            ) as response:
                raw = response.read(100_000)
        except urllib.error.HTTPError as error:
            # HTTPError subclasses URLError, so it must be caught first: a
            # server that answered with 404/500 is not the same failure as one
            # that never answered, and telling the user to check their
            # firewall for the wrong reason is worse than a vague message.
            self.cometkiwi_status_label.setText(
                f"Сервер ответил ошибкой {error.code}: по этому адресу отвечает "
                "не счётный сервер или не тот порт."
            )
            return
        except urllib.error.URLError:
            self.cometkiwi_status_label.setText(
                "Сервер не отвечает. Проверьте, запущен ли он на ПК, "
                "и открыт ли порт в брандмауэре."
            )
            return
        except TimeoutError:
            # urllib wraps a connection that never came up in URLError, but a
            # read that times out after the server accepted escapes it bare.
            self.cometkiwi_status_label.setText(
                "Сервер принял соединение, но не ответил за "
                f"{COMETKIWI_CHECK_TIMEOUT_SECONDS:g} с."
            )
            return
        except Exception:  # noqa: BLE001 - a failed check never breaks the dialog
            self.cometkiwi_status_label.setText("Проверка связи не удалась.")
            return
        try:
            health = json.loads(raw)
        except (ValueError, RecursionError):
            # json raises RecursionError, not ValueError, for nesting past the
            # recursion limit. This runs in a Qt slot, where an escaping
            # exception quits the whole application, and the body comes from
            # an unauthenticated service on the network.
            health = None
        if not isinstance(health, dict):
            self.cometkiwi_status_label.setText("Ответ сервера не разобран.")
            return
        loaded = "веса в памяти" if health.get("loaded") else "веса ещё не загружены"
        text = (
            f"Связь есть: {health.get('model', '?')} на "
            f"{health.get('device', '?')}, {loaded}."
        )
        server_model = health.get("model")
        configured_model = self._settings.cometkiwi_model
        if (
            isinstance(server_model, str)
            and server_model
            and configured_model
            and server_model != configured_model
        ):
            # The journal keeps no model name, so this is the one place where a
            # PC started under another model than the settings name shows up.
            text += (
                " Внимание: на ПК модель "
                f"{server_model[:COMETKIWI_MODEL_NAME_CHARS]}, а в настройках — "
                f"{configured_model[:COMETKIWI_MODEL_NAME_CHARS]}."
            )
        self.cometkiwi_status_label.setText(text)


def _capability_tooltip(description) -> str:
    return "\n".join(
        (
            description.summary,
            f"Нагрузка: {description.load_level} ({', '.join(description.resources)})",
            f"Скорость: {description.speed_impact}",
            f"Польза: {description.quality_benefit}",
            f"Риск: {description.quality_risk}",
            f"Сеть: {description.network_policy}",
        )
    )


def _provider_display_name(provider_id: str) -> str:
    """The provider's own name from the registry, or its id when that is unreadable."""
    try:
        from ....api import config as api_config

        provider_cfg = api_config.api_providers_view().get(provider_id) or {}
    except Exception:  # noqa: BLE001 - a settings card must open regardless
        return provider_id
    return str(provider_cfg.get("display_name") or provider_id)


def _local_model_state() -> str:
    """Say plainly whether the local model is present, and where it is sought."""
    try:
        installed, root = local_embedding_model_state()
    except Exception:  # noqa: BLE001 - the window must open regardless
        return "Состояние локальной модели неизвестно."
    if installed:
        return f"Модель найдена: {root}"
    return (
        "Модель не установлена. Положите model.onnx и tokenizer.json в "
        f"{root} — загрузка не выполняется автоматически."
    )
```

`_check_cometkiwi_endpoint` is the old dialog's method, moved unchanged. Its network tests move onto `dialog.settings_view` in Task 9 and prove the move.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_settings_view.py -v`

Expected: PASS, 20 tests.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/ui/dialogs/validation_dialogs/quality_settings_view.py tests/qa/test_quality_settings_view.py
git commit -m "feat(ui): quality settings as four cards with provider-level keys

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 8: The «Отчёт» tab

**Files:**
- Modify: `gemini_translator/qa/report_snapshot.py`:
  - `ChapterQaRow` gets `quality_score`;
  - `_row_for` fills it from metrics;
  - `BookQaReportSnapshot` gets three properties.
- Create: `gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py`
- Test: `tests/qa/test_quality_report_view.py` (create)

**Interfaces:**
- Consumes:
  - `BookQaReportSnapshot` and `CHAPTER_STATUS_LABELS` (Task 1);
  - `MetricCard`, `EmptyState`, `make_label`, `make_button`, `format_checked_at` (Task 6);
  - `theme_manager.color(name)`, where `success_text`, `warning_text` and `danger_text` come from Task 4;
  - `DECISION_LABELS` from `translation_quality_models.py`.
- Produces:
  - `ChapterQaRow.quality_score: float | None = None`.
  - New `BookQaReportSnapshot` properties: `has_scores -> bool`, `average_score -> float | None`, `last_checked_at -> str`.
  - `QualityReportView(parent=None)`:
    - Signals: `check_chapter_requested(str)`, `undo_chapter_requested(str)`, `undo_all_requested()`, `open_suggestions_requested()`.
    - Methods: `set_report(snapshot, *, scoring_enabled=False)`, `set_busy(busy)`, `selected_chapter_id() -> str`, `select_chapter(chapter_id) -> bool`.
    - Attributes:
      - summary cards: `stack`, `content`, `empty_state`, `checked_card`, `repaired_card`, `pending_card`, `score_card`;
      - table: `table` (objectName `qualityChapterTable`), `undo_all_button`;
      - chapter card: `chapter_card`, `chapter_layout`, `chapter_title_label`, `chapter_meta_label`, `chapter_details_label`, `check_chapter_button`, `undo_chapter_button`.
  - `report_columns(snapshot) -> tuple[tuple[str, str], ...]`.

Confirmation dialogs stay in the shell (Task 9). The view only asks.

- [ ] **Step 1: Write the failing test**

Create `tests/qa/test_quality_report_view.py`:

```python
"""The report tab: totals, a chapter list that fits the data, and the chosen chapter."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, QaChapterState
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot
from gemini_translator.ui.dialogs.validation_dialogs.quality_report_view import (
    QualityReportView,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _journal() -> QaJournal:
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id, status in (
        ("chapter-1", "checked"),
        ("chapter-2", "deferred"),
        ("chapter-3", "blocked"),
    ):
        journal.record_chapter_state(
            QaChapterState(
                chapter_id=chapter_id, status=status, updated_at="2026-09-09T10:05:00"
            )
        )
    journal.append_repair({"patch_id": "lang-1", "chapter_id": "chapter-1"})
    journal.append_repair({"patch_id": "lang-2", "chapter_id": "chapter-1"})
    return journal


def _headers(view: QualityReportView) -> list[str]:
    return [
        view.table.horizontalHeaderItem(index).text()
        for index in range(view.table.columnCount())
    ]


def test_the_totals_match_the_snapshot(qt_app):
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.checked_card.value_label.text() == "1 из 3"
    assert view.checked_card.detail_label.text() == "отложено 1, блокирует 1"
    assert view.repaired_card.value_label.text() == "2"
    assert view.repaired_card.detail_label.text() == "В главах: 1."
    assert view.pending_card.value_label.text() == "0"
    assert not view.pending_card.action_button.isEnabled()


def test_a_language_only_book_shows_the_four_base_columns(qt_app):
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert _headers(view) == ["Глава", "Статус", "Исправлено", "Ждут решения"]
    assert view.table.rowCount() == 3
    assert view.table.item(0, 1).text() == "Проверена"
    assert view.table.item(0, 2).text() == "2"
    assert view.table.item(1, 2).text() == ""


def test_completeness_and_score_columns_appear_only_with_their_data(qt_app):
    journal = _journal()
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-1",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=2900,
            quality_score=0.83,
            quality_score_status="scored",
        )
    )
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert _headers(view) == [
        "Глава",
        "Статус",
        "Исправлено",
        "Ждут решения",
        "Длина",
        "Пропуски",
        "Подтверждённые",
        "Книжная норма",
        "Оценка",
    ]
    assert view.table.item(0, 4).text() == "2.90"
    assert view.table.item(0, 8).text() == "0.83"
    assert view.table.item(1, 4).text() == "—"


def test_the_status_colour_is_the_readable_status_token(qt_app):
    from gemini_translator.ui import theme_manager

    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.table.item(0, 1).foreground().color().name() == theme_manager.color(
        "success_text"
    )
    assert view.table.item(2, 1).foreground().color().name() == theme_manager.color(
        "danger_text"
    )


def test_the_chapter_card_follows_the_selection(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.chapter_title_label.text() == "Глава не выбрана"
    assert view.select_chapter("chapter-1") is True
    assert view.selected_chapter_id() == "chapter-1"
    assert view.chapter_title_label.text() == "chapter-1"
    assert view.chapter_meta_label.text() == (
        "Проверена · 9 сентября 2026, 10:05 · риск: низкий · "
        "исправлено автоматически: 2"
    )

    view.select_chapter("chapter-2")

    assert view.chapter_title_label.text() == "chapter-2"
    assert view.select_chapter("chapter-404") is False


def test_a_blocked_chapter_says_why(qt_app):
    class _Gate:
        chapter_id = "chapter-3"
        reason = "подтверждённый пропуск"

    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal(), [_Gate()]))

    view.select_chapter("chapter-3")

    assert view.table.item(2, 1).text() == "⛔ Блокирует"
    assert "Перевод остановлен: подтверждённый пропуск" in view.chapter_details_label.text()


def test_actions_follow_the_selection_and_the_busy_state(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert not view.check_chapter_button.isEnabled()
    assert view.undo_all_button.isEnabled()
    view.select_chapter("chapter-2")
    assert view.check_chapter_button.isEnabled()
    assert not view.undo_chapter_button.isEnabled()
    view.select_chapter("chapter-1")
    assert view.undo_chapter_button.isEnabled()

    view.set_busy(True)

    assert not view.check_chapter_button.isEnabled()
    assert not view.undo_chapter_button.isEnabled()
    assert not view.undo_all_button.isEnabled()


def test_the_buttons_ask_for_what_is_selected(qt_app):
    view = QualityReportView()
    checks: list[str] = []
    undos: list[str] = []
    everything: list[int] = []
    opened: list[int] = []
    view.check_chapter_requested.connect(checks.append)
    view.undo_chapter_requested.connect(undos.append)
    view.undo_all_requested.connect(lambda: everything.append(1))
    view.open_suggestions_requested.connect(lambda: opened.append(1))
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    view.select_chapter("chapter-1")

    view.check_chapter_button.click()
    view.undo_chapter_button.click()
    view.undo_all_button.click()
    view.pending_card.action_clicked.emit()

    assert checks == ["chapter-1"]
    assert undos == ["chapter-1"]
    assert everything == [1]
    assert opened == [1]


def test_an_empty_report_shows_the_empty_state(qt_app):
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot())
    assert view.stack.currentWidget() is view.empty_state
    assert view.empty_state.title_label.text() == "Отчёт пока пуст"

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    assert view.stack.currentWidget() is view.content


def test_the_score_card_shows_only_when_scoring_is_on(qt_app):
    view = QualityReportView()
    snapshot = BookQaReportSnapshot.from_journal(_journal())

    view.set_report(snapshot)
    assert view.score_card.isHidden()

    view.set_report(snapshot, scoring_enabled=True)
    assert not view.score_card.isHidden()
    assert view.score_card.value_label.text() == "—"


def test_an_unchanged_report_does_not_rebuild_the_table(qt_app):
    """Проход обновляет отчёт каждые несколько секунд; пересборка на 600 глав — рывок."""
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    first = view.table.item(0, 0)

    view.set_report(BookQaReportSnapshot.from_journal(_journal()))

    assert view.table.item(0, 0) is first


def test_a_rebuilt_table_keeps_the_selected_chapter(qt_app):
    view = QualityReportView()
    view.set_report(BookQaReportSnapshot.from_journal(_journal()))
    view.select_chapter("chapter-2")
    journal = _journal()
    journal.append_repair({"patch_id": "lang-3", "chapter_id": "chapter-2"})

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert view.selected_chapter_id() == "chapter-2"
    assert view.table.item(1, 2).text() == "1"


def test_six_hundred_chapters_fill_the_table(qt_app):
    journal = QaJournal.empty(book_id="book-1")
    for index in range(600):
        journal.record_chapter_state(
            QaChapterState(chapter_id=f"chapter-{index}", status="checked")
        )
    view = QualityReportView()

    view.set_report(BookQaReportSnapshot.from_journal(journal))

    assert view.table.rowCount() == 600
    assert view.table.item(599, 0).text() == "chapter-599"


def test_only_a_snapshot_reaches_the_table(qt_app):
    """A live DataFrame from a background thread must never reach the table."""
    with pytest.raises(TypeError):
        QualityReportView().set_report({"rows": []})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_report_view.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named '...quality_report_view'`.

- [ ] **Step 3: Give the snapshot scores and the last check date**

In `gemini_translator/qa/report_snapshot.py`:

1. Add the last field of `ChapterQaRow`, after `has_completeness`:

```python
    quality_score: float | None = None
```

2. In `_row_for`, in the `ChapterQaRow(...)` built from metrics (the second one), add after `has_completeness=True,`:

```python
        quality_score=metrics.quality_score,
```

3. Add these properties to `BookQaReportSnapshot`, after `pending_suggestion_chapters`:

```python
    @property
    def has_scores(self) -> bool:
        return any(row.quality_score is not None for row in self.rows)

    @property
    def average_score(self) -> float | None:
        scores = [row.quality_score for row in self.rows if row.quality_score is not None]
        return sum(scores) / len(scores) if scores else None

    @property
    def last_checked_at(self) -> str:
        # One writer, one ISO format: the newest date is also the largest string.
        return max((row.checked_at for row in self.rows if row.checked_at), default="")
```

- [ ] **Step 4: Write the view**

Create `gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py`:

```python
# -*- coding: utf-8 -*-
"""The «Отчёт» tab: book totals, the chapter list, and the selected chapter."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....qa.report_snapshot import (
    CHAPTER_STATUS_LABELS,
    BookQaReportSnapshot,
    ChapterQaRow,
)
from ... import theme_manager
from .quality_widgets import (
    EmptyState,
    MetricCard,
    format_checked_at,
    make_button,
    make_label,
)
from .translation_quality_models import DECISION_LABELS


STATUS_TONES = {"checked": "success", "deferred": "warning", "blocked": "danger"}
BASE_COLUMNS = (
    ("Глава", "chapter_id"),
    ("Статус", "status"),
    ("Исправлено", "applied_repairs"),
    ("Ждут решения", "pending_suggestions"),
)
COMPLETENESS_COLUMNS = (
    ("Длина", "length_ratio"),
    ("Пропуски", "possible_gaps"),
    ("Подтверждённые", "confirmed_gaps"),
    ("Книжная норма", "book_position"),
)
SCORE_COLUMNS = (("Оценка", "quality_score"),)
REPORT_EMPTY_TITLE = "Отчёт пока пуст"
REPORT_EMPTY_TEXT = (
    "Проверенные главы появятся здесь после первого прохода. Проверка идёт после "
    "каждой переведённой главы или по кнопке «Проверить все главы»."
)
NO_CHAPTER_TITLE = "Глава не выбрана"
NO_CHAPTER_TEXT = "Выберите главу в списке слева."


def report_columns(snapshot: BookQaReportSnapshot) -> tuple[tuple[str, str], ...]:
    """The table's columns: completeness and score only where the book has them."""
    columns = BASE_COLUMNS
    if snapshot.has_completeness:
        columns += COMPLETENESS_COLUMNS
    if snapshot.has_scores:
        columns += SCORE_COLUMNS
    return columns


class QualityReportView(QWidget):
    """Show one report snapshot and ask for actions on what the user selected."""

    check_chapter_requested = pyqtSignal(str)
    undo_chapter_requested = pyqtSignal(str)
    undo_all_requested = pyqtSignal()
    open_suggestions_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._snapshot = BookQaReportSnapshot()
        self._busy = False
        self._scoring_enabled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)
        self.content = QWidget(self.stack)
        self.empty_state = EmptyState(REPORT_EMPTY_TITLE, REPORT_EMPTY_TEXT, self.stack)
        self.stack.addWidget(self.content)
        self.stack.addWidget(self.empty_state)

        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addLayout(self._build_totals())
        split = QHBoxLayout()
        split.setSpacing(10)
        split.addWidget(self._build_chapter_list(), 5)
        split.addWidget(self._build_chapter_card(), 6)
        content_layout.addLayout(split, 1)

        self.stack.setCurrentWidget(self.empty_state)
        self._update_actions()

    # -- building ----------------------------------------------------------

    def _build_totals(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.checked_card = MetricCard("Проверено", parent=self.content)
        self.repaired_card = MetricCard("Исправлено автоматически", parent=self.content)
        self.pending_card = MetricCard("Ждут решения", "Открыть предложения", self.content)
        self.pending_card.action_clicked.connect(self.open_suggestions_requested.emit)
        self.score_card = MetricCard("Оценка CometKiwi", parent=self.content)
        self.score_card.setVisible(False)
        row.addWidget(self.checked_card, 3)
        row.addWidget(self.repaired_card, 2)
        row.addWidget(self.pending_card, 2)
        row.addWidget(self.score_card, 2)
        return row

    def _build_chapter_list(self) -> QFrame:
        card = QFrame(self.content)
        card.setObjectName("projectPathCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(make_label("Главы", "projectCardTitle", parent=card))

        self.table = QTableWidget(0, len(BASE_COLUMNS), card)
        self.table.setObjectName("qualityChapterTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalHeaderLabels([title for title, _field in BASE_COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        undo_row = QHBoxLayout()
        self.undo_all_button = make_button(
            "Отменить все автоисправления книги", "dangerActionButton", card
        )
        self.undo_all_button.clicked.connect(self.undo_all_requested.emit)
        undo_row.addWidget(self.undo_all_button)
        undo_row.addStretch(1)
        layout.addLayout(undo_row)
        return card

    def _build_chapter_card(self) -> QFrame:
        self.chapter_card = QFrame(self.content)
        self.chapter_card.setObjectName("projectHeaderCard")
        self.chapter_layout = QVBoxLayout(self.chapter_card)
        self.chapter_layout.setContentsMargins(14, 12, 14, 12)
        self.chapter_layout.setSpacing(8)
        self.chapter_layout.addWidget(
            make_label("Глава", "sectionEyebrow", parent=self.chapter_card)
        )
        self.chapter_title_label = make_label(
            NO_CHAPTER_TITLE, "heroTitle", wrap=True, parent=self.chapter_card
        )
        self.chapter_meta_label = make_label(
            NO_CHAPTER_TEXT, "heroSubtitle", wrap=True, parent=self.chapter_card
        )
        self.chapter_details_label = make_label(
            "", "mutedLabel", wrap=True, parent=self.chapter_card
        )
        self.chapter_details_label.setVisible(False)
        self.chapter_layout.addWidget(self.chapter_title_label)
        self.chapter_layout.addWidget(self.chapter_meta_label)
        self.chapter_layout.addWidget(self.chapter_details_label)
        self.chapter_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.check_chapter_button = make_button(
            "Проверить главу", "compactActionButton", self.chapter_card
        )
        self.undo_chapter_button = make_button(
            "Отменить исправления главы", "compactActionButton", self.chapter_card
        )
        self.check_chapter_button.clicked.connect(self._request_check_chapter)
        self.undo_chapter_button.clicked.connect(self._request_undo_chapter)
        buttons.addWidget(self.check_chapter_button)
        buttons.addWidget(self.undo_chapter_button)
        buttons.addStretch(1)
        self.chapter_layout.addLayout(buttons)
        return self.chapter_card

    # -- public API --------------------------------------------------------

    def set_report(
        self, snapshot: BookQaReportSnapshot, *, scoring_enabled: bool = False
    ) -> None:
        """Show one immutable report; an unchanged chapter list is not rebuilt."""
        if not isinstance(snapshot, BookQaReportSnapshot):
            raise TypeError("snapshot must be a BookQaReportSnapshot")
        previous = self._snapshot
        self._snapshot = snapshot
        self._scoring_enabled = bool(scoring_enabled)
        self.stack.setCurrentWidget(self.content if snapshot.rows else self.empty_state)
        self._refresh_totals()
        if snapshot.rows != previous.rows or self.table.rowCount() != len(snapshot.rows):
            self._rebuild_table()
        self._refresh_chapter_card()
        self._update_actions()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._update_actions()

    def selected_chapter_id(self) -> str:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return ""
        item = self.table.item(indexes[0].row(), 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def select_chapter(self, chapter_id: str) -> bool:
        for index, row in enumerate(self._snapshot.rows):
            if row.chapter_id == chapter_id:
                self.table.selectRow(index)
                return True
        return False

    # -- internals ---------------------------------------------------------

    def _rebuild_table(self) -> None:
        selected = self.selected_chapter_id()
        columns = report_columns(self._snapshot)
        rows = self._snapshot.rows
        table = self.table
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        try:
            table.clearContents()
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels([title for title, _field in columns])
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, (_title, field_name) in enumerate(columns):
                    table.setItem(row_index, column_index, _item(row, field_name))
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)
        if selected:
            self.select_chapter(selected)

    def _refresh_totals(self) -> None:
        snapshot = self._snapshot
        self.checked_card.set_values(
            f"{snapshot.checked_count} из {len(snapshot.rows)}",
            f"отложено {snapshot.deferred_count}, блокирует {snapshot.blocking_count}",
        )
        self.repaired_card.set_values(
            str(snapshot.repair_count), f"В главах: {len(snapshot.repaired_chapters)}."
        )
        self.pending_card.set_values(
            str(snapshot.pending_suggestion_count),
            f"В главах: {len(snapshot.pending_suggestion_chapters)}.",
        )
        average = snapshot.average_score
        scored = sum(1 for row in snapshot.rows if row.quality_score is not None)
        self.score_card.set_values(
            f"{average:.2f}" if average is not None else "—", f"Оценено глав: {scored}."
        )
        self.score_card.setVisible(self._scoring_enabled)

    def _selected_row(self) -> ChapterQaRow | None:
        chapter_id = self.selected_chapter_id()
        return next(
            (row for row in self._snapshot.rows if row.chapter_id == chapter_id), None
        ) if chapter_id else None

    def _refresh_chapter_card(self) -> None:
        row = self._selected_row()
        if row is None:
            self.chapter_title_label.setText(NO_CHAPTER_TITLE)
            self.chapter_meta_label.setText(NO_CHAPTER_TEXT)
            self.chapter_details_label.clear()
            self.chapter_details_label.setVisible(False)
            return
        self.chapter_title_label.setText(row.chapter_id)
        self.chapter_meta_label.setText(_chapter_meta(row))
        details = _chapter_details(
            row, self._snapshot.decisions_by_chapter.get(row.chapter_id, ())
        )
        self.chapter_details_label.setText(details)
        self.chapter_details_label.setVisible(bool(details))

    def _on_selection_changed(self) -> None:
        self._refresh_chapter_card()
        self._update_actions()

    def _update_actions(self) -> None:
        chapter_id = self.selected_chapter_id()
        repaired = set(self._snapshot.repaired_chapters)
        idle = not self._busy
        self.check_chapter_button.setEnabled(bool(chapter_id) and idle)
        self.undo_chapter_button.setEnabled(
            bool(chapter_id) and chapter_id in repaired and idle
        )
        self.undo_all_button.setEnabled(bool(repaired) and idle)
        self.pending_card.action_button.setEnabled(
            self._snapshot.pending_suggestion_count > 0
        )

    def _request_check_chapter(self) -> None:
        chapter_id = self.selected_chapter_id()
        if chapter_id:
            self.check_chapter_requested.emit(chapter_id)

    def _request_undo_chapter(self) -> None:
        chapter_id = self.selected_chapter_id()
        if chapter_id:
            self.undo_chapter_requested.emit(chapter_id)


def _item(row: ChapterQaRow, field_name: str) -> QTableWidgetItem:
    item = QTableWidgetItem(_cell_text(row, field_name))
    if field_name == "chapter_id":
        item.setData(Qt.ItemDataRole.UserRole, row.chapter_id)
    elif field_name == "status":
        tone = STATUS_TONES.get(row.status)
        if tone:
            item.setForeground(QBrush(QColor(theme_manager.color(f"{tone}_text"))))
        if row.blocked_reason:
            item.setToolTip(f"Перевод остановлен: {row.blocked_reason}")
    else:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def _cell_text(row: ChapterQaRow, field_name: str) -> str:
    if field_name == "chapter_id":
        return row.chapter_id
    if field_name == "status":
        label = CHAPTER_STATUS_LABELS.get(row.status, row.status)
        # Colour is never the only signal: a blocked chapter says so in words.
        return f"⛔ {label}" if row.blocked_reason else label
    if field_name in ("applied_repairs", "pending_suggestions"):
        value = int(getattr(row, field_name))
        return str(value) if value else ""
    if field_name == "quality_score":
        return f"{row.quality_score:.2f}" if row.quality_score is not None else "—"
    if not row.has_completeness:
        return "—"
    if field_name == "length_ratio":
        return f"{row.length_ratio:.2f}"
    return str(getattr(row, field_name))


def _chapter_meta(row: ChapterQaRow) -> str:
    parts = [CHAPTER_STATUS_LABELS.get(row.status, row.status)]
    checked_at = format_checked_at(row.checked_at)
    if checked_at:
        parts.append(checked_at)
    if row.risk_label:
        parts.append(f"риск: {row.risk_label.lower()}")
    parts.append(f"исправлено автоматически: {row.applied_repairs}")
    return " · ".join(parts)


def _chapter_details(row: ChapterQaRow, decisions) -> str:
    lines: list[str] = []
    if row.blocked_reason:
        lines.append(f"Перевод остановлен: {row.blocked_reason}")
    if row.has_completeness:
        lines.append(
            f"{row.language_pair}, длина {row.length_ratio:.2f} — {row.profile_status}"
        )
        lines.append(f"Книжная норма: {row.book_position}")
        lines.append(
            f"Возможные пропуски: {row.possible_gaps}, подтверждённые: {row.confirmed_gaps}"
        )
        lines.append(
            f"Конфликты терминов: {row.glossary_conflicts}, остатки исходника: "
            f"{row.untranslated_fragments}, языковые дефекты: {row.language_issues}"
        )
    if row.quality_score is not None:
        lines.append(f"Оценка CometKiwi: {row.quality_score:.2f}")
    if decisions:
        lines.append(
            "Решения проверки: "
            + ", ".join(DECISION_LABELS.get(decision, decision) for decision in decisions)
        )
    return "\n".join(lines)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_report_view.py tests/qa/test_report_snapshot_states.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gemini_translator/qa/report_snapshot.py gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py tests/qa/test_quality_report_view.py
git commit -m "feat(ui): the quality report tab with totals, chapter list and chapter card

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 9: The window shell, and the page that opens it

**Files:**
- Rewrite: `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py` (whole file)
- Create: `gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py`. Stage 2 gives it only the empty state.
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_models.py`. `ChapterQaTableModel` goes.
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/__init__.py`
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_controller.py`:
  - add the `embedding_checked` signal;
  - `attach`, lines 71-88;
  - `test_embedding`, lines 250-268.
- Modify: `gemini_translator/ui/dialogs/validation.py`:
  - `open_translation_quality_dialog`, lines 2989-2998;
  - replace `_quality_api_keys`, lines 3024-3029.
- Test: `tests/qa/test_quality_window_shell.py` (create), `tests/qa/test_quality_window_wiring.py` (create).
- Test (migrate): `tests/qa/test_translation_quality_dialog.py`, `tests/qa/test_translation_quality_controller.py`, `tests/qa/test_translation_qa_performance.py`.

**Interfaces:**
- Consumes:
  - `QualityReportView` (Task 8) and `QualitySettingsView` (Task 7);
  - `StatusChip`, `EmptyState`, `make_label`, `make_button`, `format_checked_at` (Task 6);
  - `embedding_key_counts` (Task 5);
  - `BookQaReportSnapshot.last_checked_at` (Task 8).
- Produces:
  - `TranslationQualityDialog(parent=None, *, settings=None, key_counter=None, book_title="")`:
    - Every signal and method listed in Global Constraints.
    - New method `set_embedding_result(message)`.
    - Attributes: `report_view`, `suggestions_view`, `settings_view`, `tabs`, `log_view`, `progress`, `status_label`, `state_chip`, `title_label`, `subtitle_label`, `export_button`, `check_all_button`, `resume_button`, `cancel_button`, `close_button`.
    - Private helpers kept for tests: `_request_check_chapter()`, `_request_undo_chapter(chapter_id="")`, `_request_undo_all()`, `_confirm_undo(chapters) -> bool`.
  - `describe_checks(settings) -> str`.
  - `QualitySuggestionsView(parent=None)` with `empty_state`.
  - `TranslationQualityController.embedding_checked(str)`.
  - `TranslationValidatorPage._quality_key_counter(settings_manager)`, a static method that returns `count(provider_id, model_id) -> tuple[int, int]`.
  - `TranslationValidatorPage._quality_book_title() -> str`.

The page change is in this task because the constructor loses `api_keys`. Any commit in between would leave the page opening a window that no longer accepts it.

- [ ] **Step 1: Write the failing shell test**

Create `tests/qa/test_quality_window_shell.py`:

```python
"""The window shell: a header, four tabs, one primary action, and a honest busy state."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QMessageBox

from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import QaChapterState
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _snapshot() -> BookQaReportSnapshot:
    journal = QaJournal.empty(book_id="book-1")
    for chapter_id in ("chapter-1", "chapter-2"):
        journal.record_chapter_state(
            QaChapterState(
                chapter_id=chapter_id, status="checked", updated_at="2026-09-09T10:05:00"
            )
        )
    journal.append_repair({"patch_id": "lang-1", "chapter_id": "chapter-1"})
    return BookQaReportSnapshot.from_journal(journal)


def _dialog(**kwargs) -> TranslationQualityDialog:
    dialog = TranslationQualityDialog(**kwargs)
    dialog.set_report(_snapshot())
    return dialog


def test_the_window_offers_its_actions_and_tabs_by_name(qt_app):
    dialog = TranslationQualityDialog()

    assert dialog.check_all_button.text() == "Проверить все главы"
    assert dialog.resume_button.text() == "Продолжить проверку"
    assert dialog.export_button.text() == "Экспорт отчёта"
    assert dialog.cancel_button.text() == "Остановить проверку"
    assert dialog.close_button.text() == "Закрыть"
    assert dialog.report_view.check_chapter_button.text() == "Проверить главу"
    assert dialog.report_view.undo_chapter_button.text() == "Отменить исправления главы"
    assert dialog.report_view.undo_all_button.text() == "Отменить все автоисправления книги"
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "Отчёт",
        "Предложения",
        "Журнал правок",
        "Настройки",
    ]


def test_there_is_exactly_one_primary_action(qt_app):
    dialog = _dialog()

    primary = [
        button
        for button in dialog.findChildren(QtWidgets.QPushButton)
        if button.objectName() == "primaryActionButton"
    ]

    assert primary == [dialog.resume_button]


def test_a_running_pass_swaps_resume_for_stop_and_locks_the_rest(qt_app):
    dialog = _dialog()
    dialog.select_chapter("chapter-1")

    dialog.set_busy(True)

    assert dialog.resume_button.isHidden()
    assert not dialog.cancel_button.isHidden()
    assert dialog.cancel_button.isEnabled()
    assert not dialog.check_all_button.isEnabled()
    assert not dialog.export_button.isEnabled()
    assert not dialog.report_view.check_chapter_button.isEnabled()
    assert not dialog.report_view.undo_all_button.isEnabled()
    assert dialog.state_chip.text() == "Идёт проверка"
    assert dialog.state_chip.property("tone") == "warning"

    dialog.set_busy(False)

    assert not dialog.resume_button.isHidden()
    assert dialog.cancel_button.isHidden()
    assert dialog.report_view.check_chapter_button.isEnabled()
    assert dialog.state_chip.text() == "Готово к проверке"


def test_the_header_names_the_book_the_checks_and_the_last_pass(qt_app):
    dialog = _dialog(
        settings=QaSettings(check_completeness_after_chapter=False),
        book_title="Star Rail",
    )

    assert dialog.title_label.text() == "Star Rail"
    assert dialog.subtitle_label.text() == (
        "После каждой главы: язык. Последний проход: 9 сентября 2026, 10:05."
    )


def test_the_status_line_and_the_probe_answer_land_where_they_belong(qt_app):
    dialog = TranslationQualityDialog()

    dialog.set_status("Отчёт сохранён.")
    dialog.set_embedding_result("Подключение работает.")

    assert dialog.status_label.text() == "Отчёт сохранён."
    assert dialog.settings_view.embedding_result_label.text() == "Подключение работает."


def test_open_suggestions_switches_the_tab(qt_app):
    dialog = _dialog()

    dialog.report_view.open_suggestions_requested.emit()

    assert dialog.tabs.currentWidget() is dialog.suggestions_view


def test_an_edit_in_the_settings_tab_is_published_by_the_window(qt_app):
    dialog = TranslationQualityDialog(settings=QaSettings())
    published: list[QaSettings] = []
    dialog.settings_changed.connect(published.append)

    dialog.settings_view.language_check.setChecked(False)

    assert published[-1].check_language_after_chapter is False
    assert dialog.qa_settings().check_language_after_chapter is False
    assert dialog.subtitle_label.text().startswith("После каждой главы: полнота")


def test_turning_scoring_on_shows_the_score_card(qt_app):
    dialog = _dialog()
    assert dialog.report_view.score_card.isHidden()

    dialog.settings_view.cometkiwi_enabled_check.setChecked(True)

    assert not dialog.report_view.score_card.isHidden()


def test_undo_asks_before_it_restores(qt_app, monkeypatch):
    dialog = _dialog()
    dialog.select_chapter("chapter-1")
    undone: list[str] = []
    dialog.undo_chapter_requested.connect(undone.append)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    dialog.report_view.undo_chapter_button.click()
    assert undone == []

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    dialog.report_view.undo_chapter_button.click()
    assert undone == ["chapter-1"]


def test_the_suggestions_tab_says_why_it_is_empty(qt_app):
    dialog = TranslationQualityDialog()

    assert dialog.suggestions_view.empty_state.title_label.text() == "Непринятых правок нет"


def test_the_log_sits_in_a_card_and_stays_bounded(qt_app):
    dialog = TranslationQualityDialog()

    assert dialog.log_view.parentWidget().objectName() == "projectPathCard"
    assert dialog.log_view.document().maximumBlockCount() == 4000
```

- [ ] **Step 2: Write the failing wiring test**

Create `tests/qa/test_quality_window_wiring.py`:

```python
"""The validation page opens the window with a key counter and the book's name."""

from __future__ import annotations

import inspect
from types import SimpleNamespace


class _Manager:
    def load_key_statuses(self):
        return [
            {"provider": "gemini", "key": "g-1"},
            {"provider": "gemini", "key": "g-2"},
        ]

    def is_key_limit_active(self, key_info, model_id):
        return key_info.get("key") == "g-2"


def test_the_key_counter_counts_through_the_settings_manager():
    from gemini_translator.ui.dialogs import validation

    counter = validation.TranslationValidatorPage._quality_key_counter(_Manager())

    assert counter("gemini", "gemini-embedding-001") == (1, 2)


def test_the_book_title_is_the_project_folder_name():
    from gemini_translator.ui.dialogs import validation

    page = SimpleNamespace(project_manager=SimpleNamespace(project_folder="/books/Star Rail/"))

    assert validation.TranslationValidatorPage._quality_book_title(page) == "Star Rail"
    assert validation.TranslationValidatorPage._quality_book_title(SimpleNamespace()) == ""


def test_the_window_is_opened_without_a_list_of_keys():
    from gemini_translator.ui.dialogs import validation

    source = inspect.getsource(
        validation.TranslationValidatorPage.open_translation_quality_dialog
    )

    assert "api_keys" not in source
    assert "key_counter=self._quality_key_counter(settings_manager)" in source
    assert "book_title=self._quality_book_title()" in source
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_window_shell.py tests/qa/test_quality_window_wiring.py -v`

Expected: FAIL. The dialog has no `report_view` (`AttributeError`), and `TranslationValidatorPage` has no `_quality_key_counter`.

- [ ] **Step 4: Write the suggestions tab's stage 2 form**

Create `gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py`:

```python
# -*- coding: utf-8 -*-
"""The «Предложения» tab: language fixes the check proposed but did not apply."""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .quality_widgets import EmptyState


SUGGESTIONS_EMPTY_TITLE = "Непринятых правок нет"
SUGGESTIONS_EMPTY_TEXT = (
    "Правки, которые проверка не приняла, появятся здесь после следующего прохода. "
    "Прошлые проходы их не сохраняли."
)


class QualitySuggestionsView(QWidget):
    """Until suggestions are recorded, the tab says why it is empty."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        self.empty_state = EmptyState(SUGGESTIONS_EMPTY_TITLE, SUGGESTIONS_EMPTY_TEXT, self)
        layout.addWidget(self.empty_state)
```

- [ ] **Step 5: Rewrite the shell**

Replace the whole of `translation_quality_dialog.py` with:

```python
# -*- coding: utf-8 -*-
"""The «Качество перевода» window: a header, four tabs and one action bar."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ....qa.report_snapshot import BookQaReportSnapshot
from ....qa.settings import QaSettings
from .quality_report_view import QualityReportView
from .quality_settings_view import QualitySettingsView
from .quality_suggestions_view import QualitySuggestionsView
from .quality_widgets import StatusChip, format_checked_at, make_button, make_label


# The log keeps the newest chapters; a six-hundred-chapter book would otherwise
# grow one document until the window slows down.
LOG_MAX_BLOCKS = 4000


def describe_checks(settings: QaSettings) -> str:
    """Name the checks that run after each chapter, the way the header says it."""
    checks = []
    if settings.check_language_after_chapter:
        checks.append("язык")
    if settings.check_completeness_after_chapter:
        checks.append("полнота")
    if settings.capabilities.cometkiwi_enabled:
        checks.append("оценка CometKiwi")
    if not checks:
        return "Проверки после глав выключены."
    return "После каждой главы: " + ", ".join(checks) + "."


class TranslationQualityDialog(QDialog):
    """Show what quality control found and let the user act on it."""

    check_chapter_requested = pyqtSignal(str)
    check_all_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    undo_chapter_requested = pyqtSignal(str)
    undo_all_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    settings_changed = pyqtSignal(object)
    embedding_test_requested = pyqtSignal(object)
    export_requested = pyqtSignal(str)

    def __init__(
        self,
        parent=None,
        *,
        settings: QaSettings | None = None,
        key_counter=None,
        book_title: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Качество перевода")
        self.setMinimumSize(1040, 640)
        self._settings = settings or QaSettings()
        self._snapshot = BookQaReportSnapshot()
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(self._build_header(book_title))

        self.report_view = QualityReportView(self)
        self.suggestions_view = QualitySuggestionsView(self)
        self.settings_view = QualitySettingsView(
            self._settings, key_counter=key_counter, parent=self
        )
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.report_view, "Отчёт")
        self.tabs.addTab(self.suggestions_view, "Предложения")
        self.tabs.addTab(self._build_log_tab(), "Журнал правок")
        self.tabs.addTab(self.settings_view, "Настройки")
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self._build_action_bar())

        self.report_view.check_chapter_requested.connect(self.check_chapter_requested.emit)
        self.report_view.undo_chapter_requested.connect(self._request_undo_chapter)
        self.report_view.undo_all_requested.connect(self._request_undo_all)
        self.report_view.open_suggestions_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.suggestions_view)
        )
        self.settings_view.settings_changed.connect(self._on_settings_changed)
        self.settings_view.embedding_test_requested.connect(
            self.embedding_test_requested.emit
        )

        self._refresh_header()
        self._update_action_state()

    # -- building ----------------------------------------------------------

    def _build_header(self, book_title: str) -> QFrame:
        header = QFrame(self)
        header.setObjectName("projectHeaderCard")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)
        intro = QVBoxLayout()
        intro.setSpacing(2)
        intro.addWidget(make_label("Качество перевода", "sectionEyebrow", parent=header))
        self.title_label = make_label(
            book_title or "Книга без названия", "heroTitle", wrap=True, parent=header
        )
        self.subtitle_label = make_label("", "heroSubtitle", wrap=True, parent=header)
        intro.addWidget(self.title_label)
        intro.addWidget(self.subtitle_label)
        row.addLayout(intro, 1)
        self.state_chip = StatusChip("Готово к проверке", "success", header)
        row.addWidget(self.state_chip, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_log_tab(self) -> QWidget:
        """The running account of what the check changed, chapter by chapter.

        The report is rebuilt from the journal; a pass over a book takes hours,
        and this is what can be read while it runs.
        """
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 10, 0, 0)
        card = QFrame(page)
        card.setObjectName("projectPathCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        self.log_view = QTextEdit(card)
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText(
            "Здесь появится каждая глава: что найдено, что исправлено и что "
            "осталось предложением."
        )
        # A long book would otherwise grow the document without limit.
        self.log_view.document().setMaximumBlockCount(LOG_MAX_BLOCKS)
        card_layout.addWidget(self.log_view)
        page_layout.addWidget(card)
        return page

    def _build_action_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("actionBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.status_label = make_label("", "helperLabel", wrap=True, parent=bar)
        row.addWidget(self.status_label, 1)
        self.progress = QProgressBar(bar)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumWidth(220)
        self.progress.setVisible(False)
        row.addWidget(self.progress)

        self.export_button = make_button("Экспорт отчёта", "compactActionButton", bar)
        self.check_all_button = make_button("Проверить все главы", "compactActionButton", bar)
        self.resume_button = make_button("Продолжить проверку", "primaryActionButton", bar)
        self.resume_button.setToolTip(
            "Проверить только те главы, которые ещё не проверялись, были "
            "отложены, остались с неустранённым риском или изменились после "
            "проверки. Уже улаженные главы не перепроверяются."
        )
        # Takes the primary button's place while a pass runs: the one thing to
        # do then is stop it.
        self.cancel_button = make_button("Остановить проверку", "dangerActionButton", bar)
        self.close_button = make_button("Закрыть", "ghostActionButton", bar)

        self.export_button.clicked.connect(self._request_export)
        self.check_all_button.clicked.connect(self.check_all_requested.emit)
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.close_button.clicked.connect(self.reject)
        for button in (
            self.export_button,
            self.check_all_button,
            self.resume_button,
            self.cancel_button,
            self.close_button,
        ):
            row.addWidget(button)
        return bar

    # -- public API --------------------------------------------------------

    def set_report(self, snapshot: BookQaReportSnapshot) -> None:
        """Replace the report with an immutable snapshot from the journal."""
        self.report_view.set_report(
            snapshot, scoring_enabled=self._settings.capabilities.cometkiwi_enabled
        )
        self._snapshot = snapshot
        self._refresh_header()
        self._update_action_state()

    def set_busy(self, busy: bool) -> None:
        """Disable everything a running check must own exclusively."""
        self._busy = bool(busy)
        self.progress.setVisible(self._busy)
        self.report_view.set_busy(self._busy)
        self._refresh_header()
        self._update_action_state()

    def set_progress(self, checked: int, total: int, chapter_id: str = "") -> None:
        """Show honest progress of a whole-book pass."""
        total = max(int(total), 0)
        self.progress.setVisible(True)
        self.progress.setRange(0, total or 0)
        self.progress.setValue(min(int(checked), total) if total else 0)
        suffix = f" — {chapter_id}" if chapter_id else ""
        self.progress.setFormat(f"Проверено %v из %m{suffix}")

    def append_log(self, html: str) -> None:
        """Add one finished chapter to the log and keep the newest in view."""
        text = str(html or "").strip()
        if not text:
            return
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)
        self.log_view.insertHtml(text + "<hr>")
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_status(self, message: str) -> None:
        """Report one short outcome or failure without touching the report."""
        self.status_label.setText(str(message or ""))

    def set_embedding_result(self, message: str) -> None:
        """Show what the connection check answered next to the embedding settings."""
        self.settings_view.set_embedding_result(message)

    def selected_chapter_id(self) -> str:
        """Return the chapter the user is acting on, if any."""
        return self.report_view.selected_chapter_id()

    def select_chapter(self, chapter_id: str) -> bool:
        """Move the report to one chapter; used when navigating from a finding."""
        return self.report_view.select_chapter(chapter_id)

    def qa_settings(self) -> QaSettings:
        """Return the settings exactly as the settings tab currently expresses them."""
        return self.settings_view.qa_settings()

    # -- internals ---------------------------------------------------------

    def _on_settings_changed(self, settings: QaSettings) -> None:
        self._settings = settings
        self.report_view.set_report(
            self._snapshot, scoring_enabled=settings.capabilities.cometkiwi_enabled
        )
        self._refresh_header()
        self.settings_changed.emit(settings)

    def _refresh_header(self) -> None:
        parts = [describe_checks(self._settings)]
        last_pass = format_checked_at(self._snapshot.last_checked_at)
        if last_pass:
            parts.append(f"Последний проход: {last_pass}.")
        self.subtitle_label.setText(" ".join(parts))
        if self._busy:
            self.state_chip.set_state("Идёт проверка", "warning")
        else:
            self.state_chip.set_state("Готово к проверке", "success")

    def _update_action_state(self) -> None:
        busy = self._busy
        self.export_button.setEnabled(bool(self._snapshot.rows) and not busy)
        self.check_all_button.setEnabled(not busy)
        self.resume_button.setEnabled(not busy)
        self.resume_button.setVisible(not busy)
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setVisible(busy)

    def _request_export(self) -> None:
        """Ask where to write the report bundle, then hand the path over."""
        directory = QFileDialog.getExistingDirectory(self, "Куда сохранить отчёт", "")
        if directory:
            self.export_requested.emit(directory)

    def _request_check_chapter(self) -> None:
        chapter_id = self.selected_chapter_id()
        if chapter_id:
            self.check_chapter_requested.emit(chapter_id)

    def _request_undo_chapter(self, chapter_id: str = "") -> None:
        chapter_id = chapter_id or self.selected_chapter_id()
        if chapter_id and self._confirm_undo([chapter_id]):
            self.undo_chapter_requested.emit(chapter_id)

    def _request_undo_all(self) -> None:
        chapters = list(self._snapshot.repaired_chapters)
        if chapters and self._confirm_undo(chapters):
            self.undo_all_requested.emit()

    def _confirm_undo(self, chapters) -> bool:
        listing = "\n".join(f"  • {chapter}" for chapter in chapters[:20])
        if len(chapters) > 20:
            listing += f"\n  … и ещё {len(chapters) - 20}"
        answer = QMessageBox.question(
            self,
            "Отменить автоматические исправления",
            "Будут восстановлены исходные версии глав:\n"
            f"{listing}\n\nГлавы, изменённые вручную после исправления, "
            "останутся нетронутыми.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
```

- [ ] **Step 6: Retire the table model**

1. Replace the whole of `translation_quality_models.py` with:

```python
# -*- coding: utf-8 -*-
"""Labels and snapshot types the quality window shares with its controller."""

from __future__ import annotations

from ....qa.report_snapshot import (
    CHAPTER_STATUS_LABELS,
    RELATIVE_RISK_LABELS,
    RISK_LABELS,
    BookQaReportSnapshot,
    ChapterQaRow,
)


DECISION_LABELS = {
    "fixed": "Исправлено",
    "repair_rejected": "Исправление отклонено",
    "warning": "Предупреждение",
    "hallucinated_addition": "Добавленный факт",
    "no_gap": "Пропусков нет",
    "missing_content": "Потерян фрагмент",
    "covered": "Смысл передан",
    "intentional_foreign": "Намеренный иностранный текст",
    "ambiguous": "Неоднозначно",
    "excluded": "Исключено",
    "error": "Ошибка",
    "cancelled": "Отменено",
}

__all__ = (
    "BookQaReportSnapshot",
    "CHAPTER_STATUS_LABELS",
    "ChapterQaRow",
    "DECISION_LABELS",
    "RELATIVE_RISK_LABELS",
    "RISK_LABELS",
)
```

2. In `validation_dialogs/__init__.py`, replace the block from `from .translation_quality_models import (` to its `)` with the lines below, and delete the line `'ChapterQaTableModel',` from `__all__`.

```python
from .translation_quality_models import (
    BookQaReportSnapshot,
    ChapterQaRow,
)
```

- [ ] **Step 7: Send the probe's answer to the settings card**

In `translation_quality_controller.py`:

1. Add after `chapter_logged = pyqtSignal(str)`:

```python
    # The answer of «Проверить подключение», shown next to the embedding settings
    # as well as in the window's status line.
    embedding_checked = pyqtSignal(str)
```

2. In `attach`, add after the `append_log` hookup:

```python
        if hasattr(dialog, "set_embedding_result"):
            self.embedding_checked.connect(dialog.set_embedding_result)
```

3. Replace the body of `test_embedding` with:

```python
        problem = qa_settings.embedding_setup_problem()
        if problem:
            self.status_changed.emit(problem)
            self.embedding_checked.emit(problem)
            return
        self.status_changed.emit("Проверяем подключение…")
        self.embedding_checked.emit("Проверяем подключение…")

        # Прокси приложения читаем здесь, в GUI-потоке: SettingsManager не
        # предназначен для чтения из фонового потока, а проба обязана ходить тем
        # же маршрутом, что и боевой QA-прогон (trust_env=False у сессии —
        # другого источника прокси нет).
        proxy_settings = _current_proxy_settings()

        def run() -> None:
            message = _probe_embedding(qa_settings, proxy_settings=proxy_settings)
            self.status_changed.emit(message)
            self.embedding_checked.emit(message)

        threading.Thread(target=run, name="qa-embedding-probe", daemon=True).start()
```

4. In `tests/qa/test_translation_quality_controller.py`:

   a. In `test_attaching_a_dialog_connects_both_directions`, replace `assert dialog.table_model.rowCount() == 1` with `assert dialog.report_view.table.rowCount() == 1`.

   b. Append:

```python
def test_the_probe_answer_also_goes_to_the_settings_card(qt_app):
    from gemini_translator.qa.settings import QaSettings

    controller = _controller(_Coordinator())
    answers: list[str] = []
    controller.embedding_checked.connect(answers.append)

    controller.test_embedding(QaSettings(embedding_provider="openai_compatible"))

    assert answers and "ключ" in answers[-1].lower()
```

- [ ] **Step 8: Open the window with a key counter and the book's name**

In `gemini_translator/ui/dialogs/validation.py`:

1. In `open_translation_quality_dialog`, replace the dialog construction and the first `set_status` call with:

```python
        dialog = TranslationQualityDialog(
            self,
            settings=qa_settings,
            key_counter=self._quality_key_counter(settings_manager),
            book_title=self._quality_book_title(),
        )
        dialog.settings_changed.connect(settings_manager.save_qa_settings)
        dialog.set_status(qa_settings.embedding_setup_problem() or "Готово.")
```

2. Replace the static method `_quality_api_keys` with:

```python
    @staticmethod
    def _quality_key_counter(settings_manager):
        """Count a provider's working embedding keys for the quality window."""
        from ...qa.assembly import embedding_key_counts

        def count(provider_id: str, model_id: str) -> tuple[int, int]:
            return embedding_key_counts(settings_manager, provider_id, model_id)

        return count

    def _quality_book_title(self) -> str:
        """The project folder's name, which is the book's name on disk."""
        project_manager = getattr(self, "project_manager", None)
        folder = str(getattr(project_manager, "project_folder", "") or "")
        return os.path.basename(os.path.normpath(folder)) if folder else ""
```

- [ ] **Step 9: Move the old dialog tests onto the new views**

Save this helper as `/private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/drop_defs.py`:

```python
"""Delete named top-level functions and classes from a test module, decorators included."""

import ast
import sys
from pathlib import Path

path = Path(sys.argv[1])
names = set(sys.argv[2:])
source = path.read_text(encoding="utf-8")
lines = source.splitlines(keepends=True)
spans = []
found = set()
for node in ast.parse(source).body:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
        found.add(node.name)
        start = min([node.lineno, *(item.lineno for item in node.decorator_list)]) - 1
        end = node.end_lineno
        while end < len(lines) and not lines[end].strip():
            end += 1
        spans.append((start, end))
missing = names - found
if missing:
    raise SystemExit(f"not found: {sorted(missing)}")
for start, end in sorted(spans, reverse=True):
    del lines[start:end]
path.write_text("".join(lines), encoding="utf-8")
```

Then run:

```bash
SCRATCH=/private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad
.venv/bin/python "$SCRATCH/drop_defs.py" tests/qa/test_translation_quality_dialog.py \
  _Gate \
  test_dialog_exposes_the_four_actions \
  test_a_running_check_disables_conflicting_actions \
  test_actions_require_the_state_they_act_on \
  test_selecting_a_chapter_shows_its_decisions \
  test_report_summary_names_blocked_chapters \
  test_embedding_provider_choice_offers_its_own_models_and_key \
  test_incomplete_embedding_setup_is_explained_not_silently_accepted \
  test_keys_are_never_shown_in_full \
  test_stage_switches_round_trip_through_the_dialog \
  test_settings_changes_are_published_once_edited \
  test_table_model_rejects_anything_but_a_snapshot \
  _language_only_snapshot \
  _column \
  test_a_language_only_book_fills_the_table_with_statuses \
  test_completeness_columns_hide_until_a_chapter_has_metrics \
  test_a_chapter_without_metrics_shows_its_status_not_zero_ratios
.venv/bin/python "$SCRATCH/drop_defs.py" tests/qa/test_translation_qa_performance.py \
  test_the_report_table_updates_with_one_reset_not_one_signal_per_cell
.venv/bin/python - <<'EOF'
import re
from pathlib import Path

path = Path("tests/qa/test_translation_quality_dialog.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    "    BookQaReportSnapshot,\n    ChapterQaTableModel,\n    TranslationQualityDialog,\n"
    "    translation_quality_dialog as dialog_module,\n",
    "    BookQaReportSnapshot,\n    TranslationQualityDialog,\n"
    "    quality_settings_view as settings_module,\n",
)
text = text.replace("dialog_module", "settings_module")
text = re.sub(
    r"dialog\.(cometkiwi_\w+|capability_status_label|language_chunk_spin|_check_cometkiwi_endpoint)",
    r"dialog.settings_view.\1",
    text,
)
assert "ChapterQaTableModel" not in text and "dialog_module" not in text
path.write_text(text, encoding="utf-8")
EOF
.venv/bin/python -m ruff check tests/qa/test_translation_quality_dialog.py tests/qa/test_translation_qa_performance.py
```

Expected:
- The helper exits 0 both times.
- The assertion holds.
- ruff prints `All checks passed!`. If it reports an import that only the deleted tests used, delete that import.

- [ ] **Step 10: Run everything the window touches**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_window_shell.py tests/qa/test_quality_window_wiring.py tests/qa/test_translation_quality_dialog.py tests/qa/test_translation_quality_controller.py tests/qa/test_quality_pass_log.py tests/qa/test_quality_window_presentation.py tests/qa/test_translation_qa_performance.py tests/qa/test_quality_report_view.py tests/qa/test_quality_settings_view.py tests/qa/test_manual_qa_session_settings.py -q`

Expected: PASS. The CometKiwi network tests now run against `dialog.settings_view` and prove the method moved intact.

- [ ] **Step 11: Commit**

```bash
git add gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_models.py gemini_translator/ui/dialogs/validation_dialogs/__init__.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_controller.py gemini_translator/ui/dialogs/validation.py tests/qa/test_quality_window_shell.py tests/qa/test_quality_window_wiring.py tests/qa/test_translation_quality_dialog.py tests/qa/test_translation_quality_controller.py tests/qa/test_translation_qa_performance.py
git commit -m "feat(ui): rebuild the quality window as a shell over report, suggestions and settings

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 10: The real window, drawn in both themes, cuts no caption

**Files:**
- Test: `tests/qa/test_quality_window_render.py` (create)
- Modify (only if the test finds a cut caption): the view that owns the label.

**Interfaces:**
- Consumes: `theme_manager.apply(app, mode=..., manual_colors=...)` and every view from Tasks 6-9.
- Produces: a regression test and nothing else.

- [ ] **Step 1: Write the test**

Create `tests/qa/test_quality_window_render.py`:

```python
"""The real window, drawn offscreen in both themes, never cuts a wrapped caption."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.qa.capabilities import QaCapabilitySettings
from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, QaChapterState
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot
from gemini_translator.qa.settings import QaSettings
from gemini_translator.ui import theme_manager
from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog


_THEME_ATTRIBUTES = ("_theme_palette", "_active_theme_mode", "_glass_active")


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def themed(qt_app):
    """Apply a theme for one test and leave the application as it found it."""

    def apply(mode: str) -> None:
        theme_manager.apply(qt_app, mode=mode, manual_colors={"accent": "#d87a3a"})

    yield apply
    qt_app.setStyleSheet("")
    for name in _THEME_ATTRIBUTES:
        if hasattr(qt_app, name):
            delattr(qt_app, name)


def _journal() -> QaJournal:
    journal = QaJournal.empty(book_id="book-1")
    for index in range(1, 13):
        journal.record_chapter_state(
            QaChapterState(
                chapter_id=f"chapter-{index}",
                status="deferred" if index == 3 else "checked",
                updated_at="2026-09-09T10:05:00",
            )
        )
    for index in range(1, 6):
        journal.append_repair({"patch_id": f"lang-{index}", "chapter_id": f"chapter-{index}"})
    journal.upsert_metrics(
        ChapterMetrics(
            chapter_id="chapter-2",
            source_language="zh",
            target_language="ru",
            source_chars=1000,
            translated_chars=2900,
            quality_score=0.81,
            quality_score_status="scored",
        )
    )
    return journal


def _cut_captions(dialog, qt_app) -> list[tuple]:
    cut = []
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        qt_app.processEvents()
        for label in dialog.findChildren(QtWidgets.QLabel):
            if not (label.wordWrap() and label.isVisible() and label.text()):
                continue
            needed = label.heightForWidth(label.width())
            if label.height() < needed:
                cut.append(
                    (dialog.tabs.tabText(index), label.objectName(), label.text()[:40], label.height(), needed)
                )
    return cut


def _show(dialog, qt_app) -> None:
    dialog.resize(1180, 860)
    dialog.show()
    qt_app.processEvents()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_no_wrapped_caption_is_cut_in_a_full_window(qt_app, themed, mode):
    themed(mode)
    dialog = TranslationQualityDialog(
        settings=QaSettings(
            embedding_provider="gemini",
            embedding_key_provider="gemini",
            capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
        ),
        key_counter=lambda provider_id, model_id: (5, 7),
        book_title="Выиграв счастливую звезду, я попал в мир Star Rail",
    )
    dialog.set_report(BookQaReportSnapshot.from_journal(_journal()))
    dialog.set_status(
        "Проверено глав: 12 из 12. Ключи для проверки больше недоступны — "
        "продолжите проверку, когда они восстановятся."
    )
    try:
        _show(dialog, qt_app)
        dialog.select_chapter("chapter-2")
        assert _cut_captions(dialog, qt_app) == []
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_no_wrapped_caption_is_cut_in_an_empty_window(qt_app, themed, mode):
    themed(mode)
    dialog = TranslationQualityDialog(book_title="AI")
    dialog.set_report(BookQaReportSnapshot())
    try:
        _show(dialog, qt_app)
        assert _cut_captions(dialog, qt_app) == []
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_window_render.py -v`

Expected: PASS, 4 tests.

If a caption is reported cut, fix the layout that holds it, never the test. The known cause in this code base is a word-wrapped `QLabel` added to a box layout with an alignment flag. Remove the flag, or give the label a fixed width and `setMinimumHeight(label.heightForWidth(width))`, as `EmptyState` does. Then rerun.

- [ ] **Step 3: Run the theme tests after it, in the same process**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_window_render.py tests/test_theme_semantic_tokens.py tests/test_log_widget_batching.py -q`

Expected: PASS. The fixture must leave no theme behind for the tests that follow.

- [ ] **Step 4: Commit**

```bash
git add tests/qa/test_quality_window_render.py
git commit -m "test(ui): the quality window cuts no wrapped caption in either theme

Co-Authored-By: <the model that wrote this commit>"
```

If Step 2 needed a layout fix, stage that view file by name in the same commit.

---

### Task 11: Verify stage 2, show it, and fast-forward main

**Files:** none changed, unless a check fails.

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider`

Expected: every test passes.

- [ ] **Step 2: Lint the stage's files**

Run:

```bash
.venv/bin/python -m ruff check gemini_translator/ui/themes.py gemini_translator/qa/assembly.py gemini_translator/qa/report_snapshot.py gemini_translator/ui/dialogs/validation.py gemini_translator/ui/dialogs/validation_dialogs/ tests/qa/test_quality_widgets.py tests/qa/test_quality_settings_view.py tests/qa/test_quality_report_view.py tests/qa/test_quality_window_shell.py tests/qa/test_quality_window_wiring.py tests/qa/test_quality_window_render.py tests/qa/test_embedding_key_counts.py tests/test_theme_semantic_tokens.py tests/qa/test_translation_quality_dialog.py
python3 ~/.claude/ux-ui-agent-skills/scripts/lint_hardcodes.py --ext .py gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py gemini_translator/ui/dialogs/validation_dialogs/quality_settings_view.py gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py; echo "lint_hardcodes exit=$?"
```

Expected:
- ruff prints `All checks passed!`. If `validation.py` reports findings, list the ones that already existed with `git show e08fa4d:gemini_translator/ui/dialogs/validation.py | .venv/bin/python -m ruff check --stdin-filename validation.py -`. Only findings new in this stage have to be fixed.
- `lint_hardcodes exit=0`. If it flags a line, read it: the accent passed to `theme_manager.apply` in tests is the one allowed hex, and it lives in tests, not in these files.

- [ ] **Step 3: Mutation checks — the rebuild guard, the busy swap, the readable token**

```bash
mutate() {  # file, old, new, test selection
  .venv/bin/python - "$1" "$2" "$3" <<'EOF'
import sys
from pathlib import Path
path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
assert text.count(old) == 1, f"{old!r} must occur once"
path.write_text(text.replace(old, new), encoding="utf-8")
EOF
  .venv/bin/python -m pytest -q $4
  git restore "$1"
}
mutate gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py \
  "if snapshot.rows != previous.rows or self.table.rowCount() != len(snapshot.rows):" "if True:" \
  "tests/qa/test_quality_report_view.py::test_an_unchanged_report_does_not_rebuild_the_table"
mutate gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py \
  "self.resume_button.setVisible(not busy)" "self.resume_button.setVisible(True)" \
  "tests/qa/test_quality_window_shell.py::test_a_running_pass_swaps_resume_for_stop_and_locks_the_rest"
mutate gemini_translator/ui/themes.py \
  '"success_text": success_text,' '"success_text": success,' \
  "tests/test_theme_semantic_tokens.py"
git status --short
```

Expected:
- Each of the three pytest runs reports at least one failure.
- The final `git status --short` prints nothing: every mutation is restored.

- [ ] **Step 4: Draw the real window for a look**

Save as `/private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/render_quality_window.py`:

```python
"""Render the real quality window offscreen: every tab, both themes, idle and busy."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from gemini_translator.qa.capabilities import QaCapabilitySettings  # noqa: E402
from gemini_translator.qa.journal import QaJournal  # noqa: E402
from gemini_translator.qa.models import QaChapterState  # noqa: E402
from gemini_translator.qa.report_snapshot import BookQaReportSnapshot  # noqa: E402
from gemini_translator.qa.settings import QaSettings  # noqa: E402
from gemini_translator.ui import theme_manager  # noqa: E402
from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
app = QtWidgets.QApplication([])
journal = QaJournal.empty(book_id="book-1")
for index in range(1, 41):
    chapter_id = f"Глава {index}"
    journal.record_chapter_state(
        QaChapterState(
            chapter_id=chapter_id,
            status="deferred" if index == 11 else "checked",
            updated_at="2026-09-09T10:05:00",
        )
    )
    if index % 3 == 0:
        journal.append_repair({"patch_id": f"lang-{index}", "chapter_id": chapter_id})
snapshot = BookQaReportSnapshot.from_journal(journal)

for mode in ("light", "dark"):
    theme_manager.apply(app, mode=mode, manual_colors={"accent": "#d87a3a"})
    dialog = TranslationQualityDialog(
        settings=QaSettings(
            embedding_provider="gemini",
            embedding_key_provider="gemini",
            capabilities=QaCapabilitySettings(cometkiwi_enabled=True),
            cometkiwi_endpoint="http://192.168.1.176:8765",
            cometkiwi_model="wmt22-cometkiwi-da",
            cometkiwi_license_accepted=True,
        ),
        key_counter=lambda provider_id, model_id: (5, 7),
        book_title="Выиграв счастливую звезду, я попал в мир Star Rail",
    )
    dialog.set_report(snapshot)
    dialog.set_status("Готово.")
    dialog.resize(1180, 860)
    dialog.show()
    app.processEvents()
    dialog.select_chapter("Глава 12")
    for index, name in enumerate(("report", "suggestions", "log", "settings")):
        dialog.tabs.setCurrentIndex(index)
        app.processEvents()
        dialog.grab().save(str(out / f"quality-{mode}-{name}.png"))
    dialog.set_busy(True)
    dialog.set_progress(12, 40, "Глава 13")
    dialog.tabs.setCurrentIndex(0)
    app.processEvents()
    dialog.grab().save(str(out / f"quality-{mode}-busy.png"))
    dialog.close()
print("saved to", out)
```

Run: `.venv/bin/python /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/render_quality_window.py /private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/stage2-shots`

Expected: `saved to …` and ten PNG files.

1. Read every image.
2. Compare each against the approved mockups, `mock-report.png`, `mock-suggestions-empty.png` and `mock-settings.png` in the scratchpad. List every visible difference: layout, clipping, colour of the danger button, the header chip.
3. Send the light report, the light settings, the dark report and the light busy images to the owner with SendUserFile.
4. In one line each, say what differs from the mockups and why.

- [ ] **Step 5: Get one adversarial design review**

Dispatch one `design-critic` agent. Give it the ten image paths from Step 4, the four approved mockup paths, and this brief: "Judge the redesigned PyQt6 «Качество перевода» window against the approved mockups and the app's style vocabulary. Flag misalignment, clipping, weak hierarchy, unreadable text, a second primary action, or anything that reads as a different app. Answer in Russian, most severe first."

Fix every finding you agree with, each fix with its own failing test where behaviour is involved. Tell the owner about any finding you reject and why.

- [ ] **Step 6: Fast-forward main**

Run the four checks from Task 3 Step 4 again, with the same expectations. Then run:

`git -C /Users/rasreo/dev/translatorFork_MOD merge --ff-only feature/quality-window-redesign`

Expected: `Fast-forward`. Do not push.

---

# Stage 3. The fixes the check refused

### Task 12: The suggestion model

**Files:**
- Modify: `gemini_translator/qa/models.py`:
  - import `hashlib`;
  - add `QaSuggestion` right before `class GlossaryObservation`.
- Test: `tests/qa/test_qa_suggestion_model.py` (create)

**Interfaces:**
- Consumes: `_require_nonempty_string`, `_require_string`, `QaModelValidationError`.
- Produces: `QaSuggestion`, a frozen dataclass.
  - Fields, in this order: `suggestion_id`, `chapter_id`, `block_id`, `category`, `original_text`, `replacement_text=""`, `reason=""`, `explanation=""`, `created_at=""`, `status="pending"`, `status_note=""`.
  - `QaSuggestion.identity(chapter_id, block_id, original_text, replacement_text) -> str`. The result is `"sg"` plus 20 hex characters.
  - `.awaits_decision -> bool`: the status is `pending` or `stale`.
  - `.applicable -> bool`: the status is `pending` and the replacement is non-empty.
  - `.to_dict() -> dict[str, str]`.
  - `QaSuggestion.from_dict(payload)`. It is strict: it wants exactly the field set.

- [ ] **Step 1: Write the failing test**

Create `tests/qa/test_qa_suggestion_model.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_qa_suggestion_model.py -v`

Expected: FAIL with `ImportError: cannot import name 'QaSuggestion'`.

- [ ] **Step 3: Write the implementation**

In `gemini_translator/qa/models.py`:

1. Add `import hashlib` after `from enum import StrEnum`.

2. Insert right before the `@dataclass(frozen=True, slots=True)` line that decorates `class GlossaryObservation`:

```python
_SUGGESTION_STATUSES = frozenset({"pending", "applied", "dismissed", "stale"})
_UNDECIDED_SUGGESTION_STATUSES = frozenset({"pending", "stale"})


@dataclass(frozen=True, slots=True)
class QaSuggestion:
    """One language fix the check proposed but did not apply, kept for a person.

    Nothing is recomputed later: applying exactly what was proposed, or
    refusing to because the chapter has changed, is the whole contract.
    """

    suggestion_id: str
    chapter_id: str
    block_id: str
    category: str
    original_text: str
    replacement_text: str = ""
    reason: str = ""
    explanation: str = ""
    created_at: str = ""
    status: str = "pending"
    status_note: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "suggestion_id",
            "chapter_id",
            "block_id",
            "category",
            "original_text",
        ):
            _require_nonempty_string(getattr(self, field_name), field_name)
        for field_name in (
            "replacement_text",
            "reason",
            "explanation",
            "created_at",
            "status_note",
        ):
            _require_string(getattr(self, field_name), field_name)
        if self.status not in _SUGGESTION_STATUSES:
            raise QaModelValidationError("unsupported suggestion status")

    @staticmethod
    def identity(
        chapter_id: str, block_id: str, original_text: str, replacement_text: str
    ) -> str:
        """The same proposal on the same text gets the same id on every pass."""
        joined = "\x1f".join((chapter_id, block_id, original_text, replacement_text))
        return "sg" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]

    @property
    def awaits_decision(self) -> bool:
        return self.status in _UNDECIDED_SUGGESTION_STATUSES

    @property
    def applicable(self) -> bool:
        """Only an exact, non-empty replacement can be written into the chapter."""
        return self.status == "pending" and bool(self.replacement_text.strip())

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, payload: object) -> "QaSuggestion":
        if not isinstance(payload, Mapping):
            raise QaModelValidationError("suggestion must be an object")
        if set(payload) != set(cls.__dataclass_fields__):
            raise QaModelValidationError("suggestion has an invalid schema")
        try:
            return cls(**dict(payload))
        except (TypeError, ValueError) as exc:
            raise QaModelValidationError("invalid suggestion") from exc


```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/qa/test_qa_suggestion_model.py tests/qa/test_qa_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/qa/models.py tests/qa/test_qa_suggestion_model.py
git commit -m "feat(qa): a typed record of a language fix the check refused

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 13: Journal version 3 keeps suggestions

**Files:**
- Modify: `gemini_translator/qa/journal.py`
- Test: `tests/qa/test_qa_journal.py`: update the v2 round trip and append new tests.
- Test: `tests/qa/test_translation_qa_quality_corpus.py:359`: the saved version becomes 3.

**Interfaces:**
- Consumes: `QaSuggestion` (Task 12).
- Produces:
  - `QaJournal.SCHEMA_VERSION == 3`.
  - `QaJournal.suggestions: list[QaSuggestion]`.
  - `QaJournal(..., suggestions=None)`.
  - `QaJournal.suggestion(suggestion_id) -> QaSuggestion | None`.
  - `QaJournal.replace_suggestions(chapter_id, suggestions) -> None`.
  - `QaJournal.set_suggestion_status(suggestion_id, status, note="") -> QaSuggestion`. It raises `QaJournalError` for an unknown id and `QaModelValidationError` for an unknown status.
  - `QaJournal.record_chapter_result(..., suggestions=None)`:
    - `None` leaves the chapter's suggestions alone.
    - A tuple needs `state` for the same chapter.

- [ ] **Step 1: Update the round-trip test and write the failing tests**

In `tests/qa/test_qa_journal.py`:

1. Rename `test_journal_round_trip_uses_v2_json_and_dataframe_schema` to `test_journal_round_trip_uses_v3_json_and_dataframe_schema`.
2. In its docstring, replace `v2` with `v3`.
3. Change `assert payload["schema_version"] == 2` to `assert payload["schema_version"] == 3`.
4. Add `"suggestions",` after `"repairs",` in the asserted key set.
5. Append:

```python
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
```

In `tests/qa/test_translation_qa_quality_corpus.py`, change `assert saved["schema_version"] == 2` to `assert saved["schema_version"] == 3`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/qa/test_qa_journal.py tests/qa/test_translation_qa_quality_corpus.py -v`

Expected: FAIL. The version is still 2, and `record_chapter_result()` gets an unexpected keyword argument `suggestions`.

- [ ] **Step 3: Write the implementation**

In `gemini_translator/qa/journal.py`:

1. Change the models import to:

```python
from .models import (
    ChapterMetrics,
    GlossaryObservation,
    QaChapterState,
    QaJournalEntry,
    QaModelValidationError,
    QaSuggestion,
)
```

2. Add `from dataclasses import replace` after `from copy import deepcopy`.

3. Replace the class constants from `SCHEMA_VERSION = 2` through `_ROOT_KEYS_BY_VERSION = {1: _V1_ROOT_KEYS, 2: _ROOT_KEYS}` with:

```python
    SCHEMA_VERSION = 3
    _V1_ROOT_KEYS = frozenset(
        {
            "schema_version",
            "book_id",
            "updated_at",
            "metrics",
            "candidates",
            "repairs",
            "glossary_observations",
        }
    )
    # v2 adds the per-chapter check state the final book pass selects on.
    _V2_ROOT_KEYS = _V1_ROOT_KEYS | {"chapter_states"}
    # v3 keeps the language fixes a check refused, for a person to decide.
    _ROOT_KEYS = _V2_ROOT_KEYS | {"suggestions"}
    _ROOT_KEYS_BY_VERSION = {1: _V1_ROOT_KEYS, 2: _V2_ROOT_KEYS, 3: _ROOT_KEYS}
```

4. In `__init__`:

   a. Add the parameter `suggestions: Iterable[QaSuggestion] | None = None,` after `chapter_states`.

   b. Add after `self.chapter_states = dict(chapter_states or {})`:

```python
        self.suggestions = list(suggestions or [])
        if any(not isinstance(item, QaSuggestion) for item in self.suggestions):
            raise QaJournalError("suggestions must use the typed schema")
```

5. In `load`:

   a. Replace `required_lists = ("metrics", "candidates", "repairs", "glossary_observations")` with:

```python
        required_lists = ["metrics", "candidates", "repairs", "glossary_observations"]
        if version >= 3:
            required_lists.append("suggestions")
```

   b. Inside the `try:` block, after the `states = [...]` statement, add:

```python
            # Versions 1 and 2 kept no suggestions; they simply start empty.
            suggestions = [
                QaSuggestion.from_dict(item) for item in payload.get("suggestions", [])
            ]
```

   c. Add `suggestions=suggestions,` to the `return cls(...)` call.

6. Add these methods after `record_chapter_state`:

```python
    def suggestion(self, suggestion_id: str) -> QaSuggestion | None:
        """Find one suggestion by its id, whatever its state."""
        return next(
            (item for item in self.suggestions if item.suggestion_id == suggestion_id),
            None,
        )

    def replace_suggestions(
        self, chapter_id: str, suggestions: Iterable[QaSuggestion]
    ) -> None:
        """Swap a chapter's undecided suggestions for a new pass's own.

        What a person already decided stays decided: an applied or dismissed
        suggestion never comes back, even when the new pass proposes it again.
        """
        fresh = list(suggestions)
        if any(
            not isinstance(item, QaSuggestion) or item.chapter_id != chapter_id
            for item in fresh
        ):
            raise QaJournalError("suggestions must be typed and belong to the chapter")
        decided = {
            item.suggestion_id
            for item in self.suggestions
            if item.chapter_id == chapter_id and not item.awaits_decision
        }
        kept = [
            item
            for item in self.suggestions
            if item.chapter_id != chapter_id or not item.awaits_decision
        ]
        seen: set[str] = set()
        for item in fresh:
            if item.suggestion_id in decided or item.suggestion_id in seen:
                continue
            seen.add(item.suggestion_id)
            kept.append(item)
        self.suggestions = kept
        self._mark_updated()

    def set_suggestion_status(
        self, suggestion_id: str, status: str, note: str = ""
    ) -> QaSuggestion:
        """Record a person's decision, or why a suggestion no longer applies."""
        for index, item in enumerate(self.suggestions):
            if item.suggestion_id == suggestion_id:
                updated = replace(item, status=status, status_note=note)
                self.suggestions[index] = updated
                self._mark_updated()
                return updated
        raise QaJournalError(f"unknown suggestion: {suggestion_id}")
```

7. Replace `record_chapter_result` with:

```python
    def record_chapter_result(
        self,
        *,
        metrics: ChapterMetrics | None = None,
        entries: Iterable[QaJournalEntry] = (),
        repairs: Iterable[Mapping[str, Any]] = (),
        state: QaChapterState | None = None,
        suggestions: Iterable[QaSuggestion] | None = None,
    ) -> None:
        """Fold one chapter QA pass into the journal in a single step.

        ``suggestions=None`` means the pass produced no verdict on them, so the
        chapter keeps what it had; any other value replaces its undecided ones.
        """
        if suggestions is not None:
            if state is None:
                raise QaJournalError("suggestions are recorded with the chapter state")
            suggestions = tuple(suggestions)
            if any(not isinstance(item, QaSuggestion) for item in suggestions):
                raise QaJournalError("suggestions must use the typed schema")
        if metrics is not None:
            self.upsert_metrics(metrics)
        if state is not None:
            self.record_chapter_state(state)
        for entry in entries:
            if not isinstance(entry, QaJournalEntry):
                raise QaJournalError("journal entries must use the typed schema")
            self.append(entry)
        for repair in repairs:
            self.append_repair(repair)
        if suggestions is not None:
            self.replace_suggestions(state.chapter_id, suggestions)
```

8. In `_payload`, add after the `"repairs"` entry:

```python
            "suggestions": [
                item.to_dict()
                for item in sorted(
                    self.suggestions,
                    key=lambda item: (item.chapter_id, item.created_at, item.suggestion_id),
                )
            ],
```

- [ ] **Step 4: Run the journal users**

Run: `.venv/bin/python -m pytest tests/qa/test_qa_journal.py tests/qa/test_translation_qa_quality_corpus.py tests/qa/test_translation_quality_service.py tests/qa/test_chapter_qa_coordinator.py tests/qa/test_report_snapshot_states.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/qa/journal.py tests/qa/test_qa_journal.py tests/qa/test_translation_qa_quality_corpus.py
git commit -m "feat(qa): journal version 3 keeps the fixes a check refused

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 14: A check records the fixes it refused

**Files:**
- Modify: `gemini_translator/qa/service.py`:
  - add `QaSuggestion` to the import from `.models`;
  - pass `suggestions=` in `_record`, lines 1107-1145;
  - add `_suggestions_for` after `_chapter_status`, around line 1206.
- Test: `tests/qa/test_translation_quality_service.py` (append)

**Interfaces:**
- Consumes:
  - `LanguageQaResult.suggestions: tuple[LanguageIssue, ...]` and `LanguageQaResult.refusals: Mapping[str, str]`;
  - `QaSuggestion.identity` (Task 12);
  - `record_chapter_result(..., suggestions=)` (Task 13).
- Produces: `_suggestions_for(result: ChapterQaResult) -> tuple[QaSuggestion, ...] | None`. It returns `None` when the language check did not run.

- [ ] **Step 1: Write the failing test**

Append to `tests/qa/test_translation_quality_service.py`:

```python
def test_refused_language_fixes_are_kept_for_a_person_to_decide(tmp_path, chapter):
    """Отвергнутые правки видели только в живом журнале прохода и теряли навсегда."""
    from gemini_translator.qa.language_validation import LanguageQaResult
    from gemini_translator.qa.llm.schemas import LanguageIssue

    class _Language:
        async def check_chapter(self, request, *, rule_candidates=(), nlp_analysis=None):
            blocks = build_translation_payload(request.document_model)["blocks"]
            calque = LanguageIssue(
                issue_id="issue-1",
                category="calque",
                block_id=blocks[-1]["id"],
                original_text="сразу ушёл",
                replacement_text="тут же ушёл",
                objective=False,
                confidence=0.9,
                explanation="Калька с английского.",
            )
            deletion = LanguageIssue(
                issue_id="issue-2",
                category="repetition",
                block_id=blocks[0]["id"],
                original_text="открыл",
                replacement_text=None,
                objective=False,
                confidence=0.9,
                explanation="Повтор.",
            )
            return LanguageQaResult(
                chapter_id=request.chapter_id,
                issues=(calque, deletion),
                suggestions=(calque, deletion),
                refusals={"issue-1": "validation_declined", "issue-2": "no_replacement"},
            )

    service, _journal, journal_path = _service(
        tmp_path, aligner=_CleanAligner(), language=_Language()
    )

    _check(service, _request(chapter))

    saved = {
        item["original_text"]: item
        for item in json.loads(journal_path.read_text(encoding="utf-8"))["suggestions"]
    }
    assert saved["сразу ушёл"]["replacement_text"] == "тут же ушёл"
    assert saved["сразу ушёл"]["reason"] == "validation_declined"
    assert saved["сразу ушёл"]["category"] == "calque"
    assert saved["сразу ушёл"]["explanation"] == "Калька с английского."
    assert saved["сразу ушёл"]["status"] == "pending"
    assert saved["открыл"]["replacement_text"] == ""
    assert saved["открыл"]["reason"] == "no_replacement"
    assert chapter.read_text(encoding="utf-8") == _CHAPTER_HTML


def test_a_pass_without_the_language_check_leaves_suggestions_alone(tmp_path, chapter):
    from gemini_translator.qa.models import QaChapterState, QaSuggestion

    service, journal, _path = _service(tmp_path, aligner=_CleanAligner())
    existing = QaSuggestion(
        suggestion_id=QaSuggestion.identity("chapter-1", "n.1", "сразу ушёл", "тут же ушёл"),
        chapter_id="chapter-1",
        block_id="n.1",
        category="calque",
        original_text="сразу ушёл",
        replacement_text="тут же ушёл",
    )
    journal.record_chapter_result(
        state=QaChapterState(chapter_id="chapter-1", status="checked"),
        suggestions=(existing,),
    )

    _check(service, _request(chapter))

    assert journal.suggestions == [existing]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_translation_quality_service.py -k "refused_language_fixes or leaves_suggestions_alone" -v`

Expected:
- The first test FAILs with `KeyError: 'сразу ушёл'`: the saved `suggestions` list is empty.
- The second test PASSes already. That is the "None keeps them" contract, so it stays green on purpose and guards the mutation in Task 19.

- [ ] **Step 3: Write the implementation**

In `gemini_translator/qa/service.py`:

1. Add `QaSuggestion,` to the `from .models import (...)` list, after `QaModelValidationError,`.

2. In `_record`, add as the last argument of `self._journal.record_chapter_result(...)`, after the `state=QaChapterState(...)` argument:

```python
            suggestions=_suggestions_for(result),
```

3. Add right after the `_chapter_status` function:

```python
def _suggestions_for(result: ChapterQaResult) -> tuple[QaSuggestion, ...] | None:
    """The language fixes this pass refused, in the form the journal keeps.

    None when the language check did not run for the chapter: whatever an
    earlier pass left for the user then stays exactly as it was.
    """
    language = result.language
    if language is None:
        return None
    refusals = dict(getattr(language, "refusals", {}) or {})
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    suggestions: dict[str, QaSuggestion] = {}
    for issue in getattr(language, "suggestions", ()) or ():
        replacement = issue.replacement_text or ""
        suggestion_id = QaSuggestion.identity(
            result.chapter_id, issue.block_id, issue.original_text, replacement
        )
        suggestions.setdefault(
            suggestion_id,
            QaSuggestion(
                suggestion_id=suggestion_id,
                chapter_id=result.chapter_id,
                block_id=issue.block_id,
                category=issue.category,
                original_text=issue.original_text,
                replacement_text=replacement,
                reason=str(refusals.get(issue.issue_id, "")),
                explanation=issue.explanation,
                created_at=created_at,
            ),
        )
    return tuple(suggestions.values())
```

- [ ] **Step 4: Run the service tests**

Run: `.venv/bin/python -m pytest tests/qa/test_translation_quality_service.py tests/qa/test_quality_pass_log.py tests/qa/test_translation_qa_quality_corpus.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/qa/service.py tests/qa/test_translation_quality_service.py
git commit -m "feat(qa): record the language fixes a check refused

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 15: The report counts the suggestions waiting for a decision

**Files:**
- Modify: `gemini_translator/qa/report_snapshot.py`
- Test: `tests/qa/test_report_snapshot_suggestions.py` (create)

**Interfaces:**
- Consumes: `QaJournal.suggestions` and `QaSuggestion.awaits_decision` (Tasks 12-13).
- Produces:
  - `BookQaReportSnapshot.suggestions: tuple[QaSuggestion, ...]`. These are pending and stale suggestions, in natural chapter order, then by creation time and id.
  - `BookQaReportSnapshot.suggestions_for(chapter_id) -> tuple[QaSuggestion, ...]`.
  - `ChapterQaRow.pending_suggestions` is now filled.
  - A chapter known only from its suggestions gets a row.

- [ ] **Step 1: Write the failing test**

Create `tests/qa/test_report_snapshot_suggestions.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_report_snapshot_suggestions.py -v`

Expected: FAIL. `pending_suggestions` is 0 everywhere, and the snapshot has no attribute `suggestions`.

- [ ] **Step 3: Write the implementation**

In `gemini_translator/qa/report_snapshot.py`:

1. Change the models import to `from .models import ChapterMetrics, QaSuggestion, RiskLevel`.

2. Add a field to `BookQaReportSnapshot`, after `limited_mode_chapters`:

```python
    # Suggestions a person still has to decide on: pending, or stale because
    # the chapter changed.  Decided ones stay in the journal, not in the report.
    suggestions: tuple[QaSuggestion, ...] = ()
```

3. Add a method after the `last_checked_at` property:

```python
    def suggestions_for(self, chapter_id: str) -> tuple[QaSuggestion, ...]:
        return tuple(item for item in self.suggestions if item.chapter_id == chapter_id)
```

4. In `from_journal`:

   a. After the `repairs_by_chapter` loop, add:

```python
        waiting = [
            item
            for item in getattr(journal, "suggestions", ()) or ()
            if getattr(item, "awaits_decision", False)
        ]
        pending_by_chapter: dict[str, int] = {}
        for item in waiting:
            pending_by_chapter[item.chapter_id] = pending_by_chapter.get(item.chapter_id, 0) + 1
```

   b. Change the `chapter_ids` union to `set(metrics_by_chapter) | set(states) | set(repairs_by_chapter) | set(pending_by_chapter)`.

   c. Add `pending_by_chapter.get(chapter_id, 0),` as the last argument of the `_row_for(...)` call.

   d. Add to the `return cls(...)` call:

```python
            suggestions=tuple(
                sorted(
                    waiting,
                    key=lambda item: (
                        natural_sort_key(item.chapter_id),
                        item.created_at,
                        item.suggestion_id,
                    ),
                )
            ),
```

5. Give `_row_for` a last parameter, `pending_suggestions: int,`. Pass `pending_suggestions=pending_suggestions,` to both `ChapterQaRow(...)` constructions in it.

- [ ] **Step 4: Run the report tests**

Run: `.venv/bin/python -m pytest tests/qa/test_report_snapshot_suggestions.py tests/qa/test_report_snapshot_states.py tests/qa/test_quality_report_view.py tests/qa/test_limited_mode_alert.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/qa/report_snapshot.py tests/qa/test_report_snapshot_suggestions.py
git commit -m "feat(qa): the report counts suggestions waiting for a decision

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 16: Apply or dismiss one suggestion

**Files:**
- Modify: `gemini_translator/qa/service.py`:
  - add names to the imports;
  - add `SuggestionOutcome` before `class TranslationQualityService`;
  - add three methods and a helper after `undo_session`.
- Test: `tests/qa/test_translation_quality_service.py` (append)

**Interfaces:**
- Consumes:
  - `apply_language_replacements`, `LanguageReplacement` and `LanguageRepairConflict` from `language_validation.py` (imported, not modified);
  - `build_html_document_model` and `render_document_html`;
  - `RepairStore.backup_chapter`, `AppliedRepair`, `record_applied`, `atomic_write_bytes`, `content_digest`;
  - `QaJournal.suggestion`, `set_suggestion_status`, `append_repair`, `record_chapter_state`;
  - `chapter_fingerprint`.
- Produces:
  - `SuggestionOutcome(status: str, suggestion_id: str, chapter_id: str = "", detail: str = "")`, a frozen dataclass. `status` is one of `"applied"`, `"stale"`, `"failed"`, `"missing"`, `"dismissed"`.
  - `TranslationQualityService.suggestion(suggestion_id) -> QaSuggestion | None`.
  - `async TranslationQualityService.apply_suggestion(suggestion_id, translated_path: Path | str | None) -> SuggestionOutcome`.
  - `async TranslationQualityService.dismiss_suggestion(suggestion_id) -> SuggestionOutcome`.

The outcomes follow the spec's failure table:

| Situation | Status | Detail | The chapter file |
|---|---|---|---|
| The span is not found exactly once, or it crosses markup | `stale` | «глава изменилась после проверки» | untouched |
| The path is `None` or unreadable | `stale` | «перевод главы не найден» | untouched |
| The backup or the write fails | `failed` | the reason | untouched |
| The repair store refuses the record | `failed` | the reason | rolled back |
| The replacement is empty | `failed` | no replacement text | untouched; the suggestion stays pending |
| The suggestion is not pending | `missing` | — | untouched |

- [ ] **Step 1: Write the failing test**

Append to `tests/qa/test_translation_quality_service.py`:

```python
def _pending_suggestion(journal, *, block_id="n.1", original="сразу ушёл", replacement="тут же ушёл"):
    """A suggestion recorded for the chapter fixture, as a language check leaves it."""
    from gemini_translator.qa.models import QaChapterState, QaSuggestion

    suggestion = QaSuggestion(
        suggestion_id=QaSuggestion.identity("chapter-1", block_id, original, replacement),
        chapter_id="chapter-1",
        block_id=block_id,
        category="calque",
        original_text=original,
        replacement_text=replacement,
        reason="validation_declined",
    )
    journal.record_chapter_result(
        state=QaChapterState(chapter_id="chapter-1", status="checked", fingerprint="sha256:old"),
        suggestions=(suggestion,),
    )
    return suggestion


def test_an_applied_suggestion_is_written_and_undo_brings_the_chapter_back(tmp_path, chapter):
    """Применённая вручную правка откатывается той же кнопкой, что и автоисправления."""
    original = chapter.read_bytes()
    service, journal, journal_path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal)

    outcome = asyncio.run(service.apply_suggestion(suggestion.suggestion_id, chapter))

    assert (outcome.status, outcome.chapter_id) == ("applied", "chapter-1")
    assert "тут же ушёл" in chapter.read_text(encoding="utf-8")
    assert journal.suggestion(suggestion.suggestion_id).status == "applied"
    saved = json.loads(journal_path.read_text(encoding="utf-8"))
    assert any(entry["candidate_id"] == "suggestion" for entry in saved["repairs"])
    assert journal.chapter_states["chapter-1"].fingerprint == (
        "sha256:" + hashlib.sha256(chapter.read_bytes()).hexdigest()
    )

    undo = asyncio.run(service.undo_chapter("chapter-1"))

    assert undo.status == "restored"
    assert chapter.read_bytes() == original


def test_a_chapter_that_changed_is_left_alone_and_the_suggestion_goes_stale(tmp_path, chapter):
    service, journal, _path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal)
    chapter.write_text("<p>Он открыл дверь.</p><p>Он ушёл.</p>", encoding="utf-8")
    edited = chapter.read_bytes()

    outcome = asyncio.run(service.apply_suggestion(suggestion.suggestion_id, chapter))

    assert (outcome.status, outcome.detail) == ("stale", "глава изменилась после проверки")
    assert chapter.read_bytes() == edited
    recorded = journal.suggestion(suggestion.suggestion_id)
    assert (recorded.status, recorded.status_note) == ("stale", "глава изменилась после проверки")


def test_a_missing_translation_makes_the_suggestion_stale(tmp_path, chapter):
    service, journal, _path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal)

    outcome = asyncio.run(service.apply_suggestion(suggestion.suggestion_id, tmp_path / "gone.html"))

    assert (outcome.status, outcome.detail) == ("stale", "перевод главы не найден")


def test_no_translation_path_at_all_makes_the_suggestion_stale(tmp_path, chapter):
    service, journal, _path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal)

    outcome = asyncio.run(service.apply_suggestion(suggestion.suggestion_id, None))

    assert (outcome.status, outcome.detail) == ("stale", "перевод главы не найден")
    assert chapter.read_text(encoding="utf-8") == _CHAPTER_HTML


def test_a_fix_the_repair_store_cannot_record_is_rolled_back(tmp_path, chapter):
    """Правка, которую нельзя откатить, хуже, чем никакой правки."""
    original = chapter.read_bytes()
    service, journal, _path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal)

    def broken(applied):
        raise OSError("repair store is not writable")

    service._store.record_applied = broken  # noqa: SLF001 - exercising the failure

    outcome = asyncio.run(service.apply_suggestion(suggestion.suggestion_id, chapter))

    assert outcome.status == "failed"
    assert chapter.read_bytes() == original
    assert journal.suggestion(suggestion.suggestion_id).status == "pending"


def test_a_suggestion_without_a_replacement_is_never_written(tmp_path, chapter):
    service, journal, _path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal, block_id="n.0", original="открыл", replacement="")

    outcome = asyncio.run(service.apply_suggestion(suggestion.suggestion_id, chapter))

    assert outcome.status == "failed"
    assert chapter.read_text(encoding="utf-8") == _CHAPTER_HTML
    assert journal.suggestion(suggestion.suggestion_id).status == "pending"


def test_a_decision_is_made_once(tmp_path, chapter):
    service, journal, journal_path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal)

    first = asyncio.run(service.dismiss_suggestion(suggestion.suggestion_id))
    again = asyncio.run(service.dismiss_suggestion(suggestion.suggestion_id))
    applied_after = asyncio.run(service.apply_suggestion(suggestion.suggestion_id, chapter))
    unknown = asyncio.run(service.dismiss_suggestion("sg-unknown"))

    assert (first.status, again.status, applied_after.status, unknown.status) == (
        "dismissed",
        "missing",
        "missing",
        "missing",
    )
    assert chapter.read_text(encoding="utf-8") == _CHAPTER_HTML
    saved = json.loads(journal_path.read_text(encoding="utf-8"))
    assert saved["suggestions"][0]["status"] == "dismissed"


def test_a_stale_suggestion_can_still_be_taken_off_the_list(tmp_path, chapter):
    service, journal, _path = _service(tmp_path, aligner=_CleanAligner())
    suggestion = _pending_suggestion(journal)
    journal.set_suggestion_status(suggestion.suggestion_id, "stale", "глава изменилась после проверки")

    outcome = asyncio.run(service.dismiss_suggestion(suggestion.suggestion_id))

    assert outcome.status == "dismissed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/qa/test_translation_quality_service.py -k "suggestion" -v`

Expected: FAIL with `AttributeError: 'TranslationQualityService' object has no attribute 'apply_suggestion'`.

- [ ] **Step 3: Write the implementation**

In `gemini_translator/qa/service.py`:

1. Change the `from .language_validation import (...)` block to:

```python
from .language_validation import (
    DEFAULT_AUTO_FIX_CATEGORIES,
    DEFAULT_LANGUAGE_CHUNK_CHARS,
    LanguageQaRequest,
    LanguageQaResult,
    LanguageRepairConflict,
    LanguageReplacement,
    LanguageRuleIssue,
    RussianNlpAnalysis,
    apply_language_replacements,
)
```

2. Insert right before `class TranslationQualityService:`:

```python
@dataclass(frozen=True, slots=True)
class SuggestionOutcome:
    """What became of one suggestion a person chose to apply or dismiss."""

    status: str
    suggestion_id: str
    chapter_id: str = ""
    detail: str = ""


_SUGGESTION_ALREADY_DECIDED = "правка уже решена или не найдена"
```

3. Insert right after the `undo_session` method:

```python
    def suggestion(self, suggestion_id: str) -> QaSuggestion | None:
        """Find one recorded suggestion, whatever its state."""
        return self._journal.suggestion(suggestion_id)

    async def apply_suggestion(
        self, suggestion_id: str, translated_path: Path | str | None
    ) -> SuggestionOutcome:
        """Write one suggestion into its chapter the way an automatic fix is written.

        It is backed up first and recorded in the repair store, so «Отменить
        исправления главы» reverts it like any other fix.  A chapter that has
        changed since the check is left untouched and the suggestion goes stale.
        """
        suggestion = self._journal.suggestion(suggestion_id)
        if suggestion is None or suggestion.status != "pending":
            return SuggestionOutcome(
                "missing",
                suggestion_id,
                getattr(suggestion, "chapter_id", ""),
                _SUGGESTION_ALREADY_DECIDED,
            )
        chapter_id = suggestion.chapter_id
        if not suggestion.applicable:
            return SuggestionOutcome(
                "failed",
                suggestion_id,
                chapter_id,
                "нет текста замены: такую правку вносит человек",
            )
        path = Path(translated_path) if translated_path else None
        try:
            if path is None:
                raise FileNotFoundError(chapter_id)
            before = path.read_bytes()
        except OSError:
            return self._suggestion_went_stale(suggestion, "перевод главы не найден")
        try:
            model = build_html_document_model(before.decode("utf-8"), document_id=chapter_id)
            edited = apply_language_replacements(
                model,
                (
                    LanguageReplacement(
                        issue_id=suggestion_id,
                        block_id=suggestion.block_id,
                        original_text=suggestion.original_text,
                        replacement_text=suggestion.replacement_text,
                    ),
                ),
            )
        except (LanguageRepairConflict, ValueError):
            return self._suggestion_went_stale(suggestion, "глава изменилась после проверки")
        payload = render_document_html(edited).encode("utf-8")
        try:
            backup = self._store.backup_chapter(chapter_id, path)
            atomic_write_bytes(path, payload)
        except (OSError, RepairStoreError) as error:
            return SuggestionOutcome(
                "failed", suggestion_id, chapter_id, f"не удалось записать главу: {error}"
            )
        patch_id = "sug" + hashlib.sha256(suggestion_id.encode("utf-8")).hexdigest()[:20]
        applied = AppliedRepair(
            patch_id=patch_id,
            chapter_id=chapter_id,
            session_id=self._store.session_id,
            chapter_path=path,
            backup_path=backup.path,
            before_sha256=content_digest(before),
            after_sha256=content_digest(payload),
            inserted_text=suggestion.replacement_text[:500],
        )
        try:
            self._store.record_applied(applied)
        except Exception as error:  # noqa: BLE001 - a written fix must stay recorded or undone
            try:
                atomic_write_bytes(path, before)
            except OSError:
                pass
            return SuggestionOutcome(
                "failed",
                suggestion_id,
                chapter_id,
                f"исправление не записано в хранилище правок: {error}",
            )
        self._journal.append_repair(
            {
                "patch_id": patch_id,
                "chapter_id": chapter_id,
                "candidate_id": "suggestion",
                "session_id": self._store.session_id,
                "fragment": applied.inserted_text,
            }
        )
        self._journal.set_suggestion_status(suggestion_id, "applied")
        state = self._journal.chapter_states.get(chapter_id)
        if state is not None:
            # The chapter changed on purpose: «Продолжить проверку» must not
            # take this one accepted edit as a reason to check it again.
            self._journal.record_chapter_state(
                replace(state, fingerprint=chapter_fingerprint(path))
            )
        self._save_journal()
        return SuggestionOutcome("applied", suggestion_id, chapter_id)

    async def dismiss_suggestion(self, suggestion_id: str) -> SuggestionOutcome:
        """Take one suggestion off the list; the chapter is not touched."""
        suggestion = self._journal.suggestion(suggestion_id)
        if suggestion is None or not suggestion.awaits_decision:
            return SuggestionOutcome(
                "missing",
                suggestion_id,
                getattr(suggestion, "chapter_id", ""),
                _SUGGESTION_ALREADY_DECIDED,
            )
        self._journal.set_suggestion_status(suggestion_id, "dismissed")
        self._save_journal()
        return SuggestionOutcome("dismissed", suggestion_id, suggestion.chapter_id)

    def _suggestion_went_stale(
        self, suggestion: QaSuggestion, note: str
    ) -> SuggestionOutcome:
        self._journal.set_suggestion_status(suggestion.suggestion_id, "stale", note)
        self._save_journal()
        return SuggestionOutcome("stale", suggestion.suggestion_id, suggestion.chapter_id, note)
```

- [ ] **Step 4: Run the service tests**

Run: `.venv/bin/python -m pytest tests/qa/test_translation_quality_service.py tests/qa/test_translation_qa_quality_corpus.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemini_translator/qa/service.py tests/qa/test_translation_quality_service.py
git commit -m "feat(qa): apply or dismiss a refused fix through the repair store

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 17: The coordinator and the controller carry the decision

**Files:**
- Modify: `gemini_translator/core/chapter_qa_coordinator.py`: add two methods after `undo_all`, around line 493.
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_controller.py`:
  - add `SUGGESTION_MESSAGES` after `RECHECK_REASONS`;
  - add two actions after `undo_all`;
  - add `_finish_suggestion` after `_finish_undo`;
  - extend `attach`.
- Test: `tests/qa/test_chapter_qa_coordinator.py` (append), `tests/qa/test_translation_quality_controller.py` (append).

**Interfaces:**
- Consumes:
  - `service.suggestion(suggestion_id)`, `service.apply_suggestion(suggestion_id, translated_path)`, `service.dismiss_suggestion(suggestion_id)` (Task 16);
  - `SuggestionOutcome`.
- Produces:
  - `async ChapterQaCoordinator.apply_suggestion(suggestion_id) -> SuggestionOutcome`, which finds the path through `_book_events()`.
  - `async ChapterQaCoordinator.dismiss_suggestion(suggestion_id) -> SuggestionOutcome`.
  - `TranslationQualityController.apply_suggestion(suggestion_id)` and `dismiss_suggestion(suggestion_id)`.
  - `attach` connects the dialog's `apply_suggestion_requested` and `dismiss_suggestion_requested`, when the dialog has them (Task 18).

- [ ] **Step 1: Write the failing tests**

Append to `tests/qa/test_chapter_qa_coordinator.py`:

```python
def test_a_suggestion_is_applied_to_its_chapters_translation():
    class _Suggestion:
        chapter_id = "chapter-2"

    class _Service(_ServiceStub):
        def __init__(self) -> None:
            super().__init__()
            self.applied: list[tuple[str, object]] = []
            self.dismissed: list[str] = []

        def suggestion(self, suggestion_id):
            return _Suggestion() if suggestion_id == "sg-1" else None

        async def apply_suggestion(self, suggestion_id, translated_path):
            self.applied.append((suggestion_id, translated_path))
            return "applied"

        async def dismiss_suggestion(self, suggestion_id):
            self.dismissed.append(suggestion_id)
            return "dismissed"

    service = _Service()
    coordinator = ChapterQaCoordinator(
        service=service,
        task_manager=None,
        request_builder=lambda event: event.chapter_id,
        book_events_provider=lambda: (_event("chapter-1"), _event("chapter-2")),
    )

    assert asyncio.run(coordinator.apply_suggestion("sg-1")) == "applied"
    assert asyncio.run(coordinator.apply_suggestion("sg-404")) == "applied"
    assert asyncio.run(coordinator.dismiss_suggestion("sg-1")) == "dismissed"
    assert service.applied == [("sg-1", "/tmp/chapter-2"), ("sg-404", None)]
    assert service.dismissed == ["sg-1"]
```

Append to `tests/qa/test_translation_quality_controller.py`:

```python
class _SuggestionCoordinator(_Coordinator):
    def __init__(self, outcome) -> None:
        super().__init__()
        self.outcome = outcome
        self.applied: list[str] = []
        self.dismissed: list[str] = []

    async def apply_suggestion(self, suggestion_id):
        self.applied.append(suggestion_id)
        return self.outcome

    async def dismiss_suggestion(self, suggestion_id):
        self.dismissed.append(suggestion_id)
        return self.outcome


def test_applying_a_suggestion_says_what_happened_and_refreshes(qt_app):
    from gemini_translator.qa.service import SuggestionOutcome

    coordinator = _SuggestionCoordinator(SuggestionOutcome("applied", "sg-1", "chapter-1"))
    controller = _controller(coordinator)
    statuses, busy, reports = [], [], []
    controller.status_changed.connect(statuses.append)
    controller.busy_changed.connect(busy.append)
    controller.report_ready.connect(reports.append)

    controller.apply_suggestion("sg-1")

    assert coordinator.applied == ["sg-1"]
    assert busy == [True, False]
    assert statuses[-1] == (
        "Правка применена в главе «chapter-1». Откатить её можно кнопкой "
        "«Отменить исправления главы»."
    )
    assert reports


def test_a_stale_suggestion_says_the_chapter_was_not_touched(qt_app):
    from gemini_translator.qa.service import SuggestionOutcome

    coordinator = _SuggestionCoordinator(
        SuggestionOutcome("stale", "sg-1", "chapter-1", "глава изменилась после проверки")
    )
    controller = _controller(coordinator)
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.apply_suggestion("sg-1")

    assert statuses[-1] == (
        "Правка устарела: глава изменилась после проверки. Файл главы не тронут."
    )


def test_dismissing_a_suggestion_goes_through_the_coordinator(qt_app):
    from gemini_translator.qa.service import SuggestionOutcome

    coordinator = _SuggestionCoordinator(SuggestionOutcome("dismissed", "sg-1", "chapter-1"))
    controller = _controller(coordinator)
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.dismiss_suggestion("sg-1")

    assert coordinator.dismissed == ["sg-1"]
    assert statuses[-1] == "Правка отклонена."


def test_a_crash_while_applying_is_reported_and_releases_the_window(qt_app):
    class _Crashing(_Coordinator):
        async def apply_suggestion(self, suggestion_id):
            raise RuntimeError("disk full")

    controller = _controller(_Crashing())
    statuses, busy = [], []
    controller.status_changed.connect(statuses.append)
    controller.busy_changed.connect(busy.append)

    controller.apply_suggestion("sg-1")

    assert busy == [True, False]
    assert "disk full" in statuses[-1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/qa/test_chapter_qa_coordinator.py tests/qa/test_translation_quality_controller.py -k "suggestion" -v`

Expected: FAIL with `AttributeError: ... has no attribute 'apply_suggestion'`.

- [ ] **Step 3: Add the coordinator methods**

In `gemini_translator/core/chapter_qa_coordinator.py`, insert after `undo_all`:

```python
    async def apply_suggestion(self, suggestion_id: str):
        """Write one suggestion the user accepted into its chapter's translation."""
        suggestion = self._service.suggestion(suggestion_id)
        chapter_id = str(getattr(suggestion, "chapter_id", "") or "")
        translated_path = (
            next(
                (
                    event.translated_path
                    for event in self._book_events()
                    if event.chapter_id == chapter_id
                ),
                None,
            )
            if chapter_id
            else None
        )
        return await self._service.apply_suggestion(suggestion_id, translated_path)

    async def dismiss_suggestion(self, suggestion_id: str):
        """Take one suggestion off the list without touching the chapter."""
        return await self._service.dismiss_suggestion(suggestion_id)
```

- [ ] **Step 4: Add the controller actions**

In `translation_quality_controller.py`:

1. After `RECHECK_REASONS`, add:

```python
# What the user reads after acting on one suggestion.
SUGGESTION_MESSAGES = {
    "applied": (
        "Правка применена в главе «{chapter}». Откатить её можно кнопкой "
        "«Отменить исправления главы»."
    ),
    "dismissed": "Правка отклонена.",
    "stale": "Правка устарела: {detail}. Файл главы не тронут.",
    "failed": "Правка не применена: {detail}.",
    "missing": "Правка уже решена или не найдена.",
}
```

2. In `attach`, add after the `embedding_checked` hookup:

```python
        if hasattr(dialog, "apply_suggestion_requested"):
            dialog.apply_suggestion_requested.connect(self.apply_suggestion)
        if hasattr(dialog, "dismiss_suggestion_requested"):
            dialog.dismiss_suggestion_requested.connect(self.dismiss_suggestion)
```

3. After `undo_all`, add:

```python
    def apply_suggestion(self, suggestion_id: str) -> None:
        """Write one accepted suggestion into its chapter, off the interface thread."""
        coordinator = self._coordinator()
        if coordinator is None:
            return
        self._set_busy(True)
        coordinator.run_background(
            lambda: coordinator.apply_suggestion(suggestion_id),
            lambda result, error: self._finish_suggestion(result, error),
        )

    def dismiss_suggestion(self, suggestion_id: str) -> None:
        """Take one suggestion off the list."""
        coordinator = self._coordinator()
        if coordinator is None:
            return
        self._set_busy(True)
        coordinator.run_background(
            lambda: coordinator.dismiss_suggestion(suggestion_id),
            lambda result, error: self._finish_suggestion(result, error),
        )
```

4. After `_finish_undo`, add:

```python
    def _finish_suggestion(self, result, error) -> None:
        if error is not None:
            self.status_changed.emit(f"Не удалось обработать правку: {error}")
        else:
            status = str(getattr(result, "status", "") or "")
            template = SUGGESTION_MESSAGES.get(status, "Правка обработана.")
            self.status_changed.emit(
                template.format(
                    chapter=getattr(result, "chapter_id", ""),
                    detail=getattr(result, "detail", ""),
                )
            )
        self._set_busy(False)
        self.refresh_report()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/qa/test_chapter_qa_coordinator.py tests/qa/test_translation_quality_controller.py tests/qa/test_quality_pass_log.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add gemini_translator/core/chapter_qa_coordinator.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_controller.py tests/qa/test_chapter_qa_coordinator.py tests/qa/test_translation_quality_controller.py
git commit -m "feat(qa): carry a suggestion decision from the window to the chapter

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 18: The «Предложения» tab and the chapter card's suggestions

**Files:**
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py`: add `CATEGORY_LABELS`, `category_label`, `pending_caption` and `SuggestionCard`.
- Rewrite: `gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py`
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py`: the chapter card lists that chapter's suggestions.
- Modify: `gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py`: two signals, the tab counter, the busy state.
- Test: `tests/qa/test_quality_suggestions.py` (create), `tests/qa/test_quality_window_shell.py` (append), `tests/qa/test_translation_quality_controller.py` (append), `tests/qa/test_quality_window_render.py` (extend `_journal`).

**Interfaces:**
- Consumes:
  - `QaSuggestion` (Task 12);
  - `BookQaReportSnapshot.suggestions` and `suggestions_for` (Task 15);
  - `describe_refusal` and `LANGUAGE_ISSUE_CATEGORIES` (read only);
  - `highlight_pair` from `qa/text_diff.py`;
  - the controller's `attach` hookups (Task 17).
- Produces:
  - `category_label(code) -> str` and `pending_caption(count) -> str`.
  - `SuggestionCard(suggestion, *, show_chapter=True, parent=None)`:
    - signals `apply_requested(str)`, `dismiss_requested(str)`;
    - attributes `suggestion`, `category_chip`, `reason_label`, `before_label`, `after_label`, `note_label`, `dismiss_button`, `apply_button` (`None` for a stale suggestion);
    - method `set_busy(busy)`.
  - `QualitySuggestionsView`:
    - signals `apply_requested(str)`, `dismiss_requested(str)`;
    - methods `set_suggestions(suggestions)`, `set_busy(busy)`, `visible_suggestions()`;
    - attributes `stack`, `content`, `empty_state`, `chapter_filter`, `category_filter`, `counter_label`, `cards`, `more_button`.
  - `QualityReportView`:
    - signals `apply_suggestion_requested(str)`, `dismiss_suggestion_requested(str)`;
    - attributes `pending_title_label`, `pending_area`, `pending_cards`.
  - `TranslationQualityDialog`: signals `apply_suggestion_requested(str)` and `dismiss_suggestion_requested(str)`.

A long list is shown 50 cards at a time. A pass refreshes the report every few seconds, and hundreds of cards, each a dozen widgets, would freeze the window.

- [ ] **Step 1: Write the failing tests for the card and the tab**

Create `tests/qa/test_quality_suggestions.py`:

```python
"""A refused fix is shown with its reason and both texts, and decided in one click."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.qa.language_validation import LANGUAGE_ISSUE_CATEGORIES
from gemini_translator.qa.models import QaSuggestion
from gemini_translator.ui.dialogs.validation_dialogs.quality_suggestions_view import (
    QualitySuggestionsView,
)
from gemini_translator.ui.dialogs.validation_dialogs.quality_widgets import (
    SuggestionCard,
    category_label,
    pending_caption,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _suggestion(
    chapter_id="chapter-12",
    original="— Спросил он.",
    replacement="— спросил он.",
    category="punctuation",
    status="pending",
    reason="validation_declined",
    note="",
) -> QaSuggestion:
    return QaSuggestion(
        suggestion_id=QaSuggestion.identity(chapter_id, "n.1", original, replacement),
        chapter_id=chapter_id,
        block_id="n.1",
        category=category,
        original_text=original,
        replacement_text=replacement,
        reason=reason,
        status=status,
        status_note=note,
    )


def test_every_known_category_reads_in_russian_and_an_unknown_one_stays_as_is():
    for code in LANGUAGE_ISSUE_CATEGORIES:
        assert category_label(code) != code
    assert category_label("new_code") == "new_code"


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "1 правка ждёт решения"),
        (3, "3 правки ждут решения"),
        (5, "5 правок ждут решения"),
        (11, "11 правок ждут решения"),
        (21, "21 правка ждёт решения"),
        (37, "37 правок ждут решения"),
    ],
)
def test_the_counter_agrees_with_its_number(count, text):
    assert pending_caption(count) == text


def test_a_card_shows_where_what_why_and_both_texts(qt_app):
    card = SuggestionCard(_suggestion())

    texts = [label.text() for label in card.findChildren(QtWidgets.QLabel)]

    assert "chapter-12" in texts
    assert card.category_chip.text() == "пунктуация"
    assert card.reason_label.text() == "не принято: модель-проверщик не подтвердила правку"
    assert "Спросил" in card.before_label.text()
    assert "спросил" in card.after_label.text()
    assert card.dismiss_button.text() == "Отклонить"
    assert card.apply_button.text() == "Применить"


def test_card_buttons_ask_by_the_suggestions_id(qt_app):
    suggestion = _suggestion()
    card = SuggestionCard(suggestion)
    applied: list[str] = []
    dismissed: list[str] = []
    card.apply_requested.connect(applied.append)
    card.dismiss_requested.connect(dismissed.append)

    card.apply_button.click()
    card.dismiss_button.click()

    assert applied == [suggestion.suggestion_id]
    assert dismissed == [suggestion.suggestion_id]


def test_a_stale_card_only_offers_to_take_it_off_the_list(qt_app):
    card = SuggestionCard(
        _suggestion(status="stale", note="глава изменилась после проверки")
    )

    assert card.apply_button is None
    assert card.dismiss_button.text() == "Убрать из списка"
    assert card.note_label.text() == "устарело: глава изменилась после проверки"


def test_a_card_without_a_replacement_cannot_be_applied(qt_app):
    card = SuggestionCard(_suggestion(original="очень-очень", replacement="", reason="no_replacement"))

    assert not card.apply_button.isEnabled()
    assert "вносит человек" in card.note_label.text()
    assert "удалить фрагмент" in card.after_label.text()


def test_model_text_is_never_rendered_as_markup(qt_app):
    card = SuggestionCard(_suggestion(original="<b>x</b> и", replacement="<i>y</i> и"))

    assert "&lt;b&gt;" in card.before_label.text()
    assert "<b>" not in card.before_label.text()


def test_a_busy_window_locks_a_card(qt_app):
    card = SuggestionCard(_suggestion())

    card.set_busy(True)
    assert not card.apply_button.isEnabled()
    assert not card.dismiss_button.isEnabled()

    card.set_busy(False)
    assert card.apply_button.isEnabled()
    assert card.dismiss_button.isEnabled()


def _view(*suggestions) -> QualitySuggestionsView:
    view = QualitySuggestionsView()
    view.set_suggestions(suggestions)
    return view


def test_filters_narrow_the_cards_and_the_counter_counts_them_all(qt_app):
    view = _view(
        _suggestion("chapter-2", "a а", "b б", "punctuation"),
        _suggestion("chapter-2", "c в", "d г", "calque"),
        _suggestion("chapter-10", "e д", "f е", "punctuation"),
    )

    assert view.counter_label.text() == "3 правки ждут решения"
    assert [view.chapter_filter.itemText(i) for i in range(view.chapter_filter.count())] == [
        "Все главы",
        "chapter-2",
        "chapter-10",
    ]
    assert len(view.cards) == 3

    view.chapter_filter.setCurrentIndex(view.chapter_filter.findData("chapter-2"))
    assert [card.suggestion.chapter_id for card in view.cards] == ["chapter-2", "chapter-2"]

    view.category_filter.setCurrentIndex(view.category_filter.findData("calque"))
    assert [card.suggestion.category for card in view.cards] == ["calque"]
    assert view.counter_label.text() == "3 правки ждут решения"


def test_a_filter_survives_a_refresh_while_its_chapter_still_waits(qt_app):
    first = _suggestion("chapter-2", "a а", "b б")
    view = _view(first, _suggestion("chapter-10", "e д", "f е"))
    view.chapter_filter.setCurrentIndex(view.chapter_filter.findData("chapter-2"))

    view.set_suggestions((first, _suggestion("chapter-2", "c в", "d г"), _suggestion("chapter-10", "e д", "f е")))

    assert view.chapter_filter.currentData() == "chapter-2"
    assert len(view.cards) == 2


def test_no_suggestions_shows_the_empty_state(qt_app):
    view = _view()

    assert view.stack.currentWidget() is view.empty_state
    assert view.empty_state.title_label.text() == "Непринятых правок нет"


def test_a_long_list_is_shown_fifty_cards_at_a_time(qt_app):
    view = _view(*[_suggestion(f"chapter-{i}", f"a{i} а", f"b{i} б") for i in range(120)])

    assert len(view.cards) == 50
    assert view.more_button.text() == "Показать ещё 50 из 70"

    view.more_button.click()
    assert len(view.cards) == 100

    view.more_button.click()
    assert len(view.cards) == 120
    assert view.more_button.isHidden()


def test_the_tab_asks_for_decisions_by_id_and_locks_while_busy(qt_app):
    suggestion = _suggestion()
    view = _view(suggestion)
    applied: list[str] = []
    view.apply_requested.connect(applied.append)

    view.cards[0].apply_button.click()
    view.set_busy(True)

    assert applied == [suggestion.suggestion_id]
    assert not view.cards[0].apply_button.isEnabled()
```

- [ ] **Step 2: Append the failing window and controller tests**

Append to `tests/qa/test_quality_window_shell.py`:

```python
def _snapshot_with_suggestions():
    from gemini_translator.qa.models import QaSuggestion

    journal = QaJournal.empty(book_id="book-1")
    suggestions = tuple(
        QaSuggestion(
            suggestion_id=QaSuggestion.identity("chapter-1", "n.1", before, after),
            chapter_id="chapter-1",
            block_id="n.1",
            category="punctuation",
            original_text=before,
            replacement_text=after,
            reason="validation_declined",
        )
        for before, after in (("— Спросил он.", "— спросил он."), ("Он очень-очень устал.", "Он очень устал."))
    )
    journal.record_chapter_result(
        state=QaChapterState(chapter_id="chapter-1", status="checked"),
        suggestions=suggestions,
    )
    journal.record_chapter_state(QaChapterState(chapter_id="chapter-2", status="checked"))
    return BookQaReportSnapshot.from_journal(journal), suggestions


def test_the_tab_counts_the_suggestions_waiting(qt_app):
    snapshot, _suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()

    dialog.set_report(snapshot)
    assert dialog.tabs.tabText(1) == "Предложения (2)"
    assert len(dialog.suggestions_view.cards) == 2

    dialog.set_report(BookQaReportSnapshot())
    assert dialog.tabs.tabText(1) == "Предложения"


def test_the_chapter_card_lists_that_chapters_suggestions(qt_app):
    snapshot, _suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()
    dialog.set_report(snapshot)

    dialog.select_chapter("chapter-1")
    assert dialog.report_view.pending_title_label.text() == "Ждут решения: 2"
    assert len(dialog.report_view.pending_cards) == 2

    dialog.select_chapter("chapter-2")
    assert dialog.report_view.pending_title_label.isHidden()
    assert dialog.report_view.pending_cards == []


def test_both_tabs_ask_the_window_to_apply_or_dismiss(qt_app):
    snapshot, suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()
    dialog.set_report(snapshot)
    applied: list[str] = []
    dismissed: list[str] = []
    dialog.apply_suggestion_requested.connect(applied.append)
    dialog.dismiss_suggestion_requested.connect(dismissed.append)

    dialog.suggestions_view.cards[0].apply_button.click()
    dialog.select_chapter("chapter-1")
    dialog.report_view.pending_cards[1].dismiss_button.click()

    assert applied == [dialog.suggestions_view.cards[0].suggestion.suggestion_id]
    assert dismissed == [dialog.report_view.pending_cards[1].suggestion.suggestion_id]
    assert set(applied + dismissed) <= {item.suggestion_id for item in suggestions}


def test_a_running_pass_locks_every_suggestion_button(qt_app):
    snapshot, _suggestions = _snapshot_with_suggestions()
    dialog = TranslationQualityDialog()
    dialog.set_report(snapshot)
    dialog.select_chapter("chapter-1")

    dialog.set_busy(True)

    cards = dialog.suggestions_view.cards + dialog.report_view.pending_cards
    assert cards
    assert not any(card.apply_button.isEnabled() or card.dismiss_button.isEnabled() for card in cards)
```

Append to `tests/qa/test_translation_quality_controller.py`:

```python
def test_the_windows_suggestion_buttons_reach_the_controller(qt_app):
    from gemini_translator.qa.service import SuggestionOutcome
    from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog

    coordinator = _SuggestionCoordinator(SuggestionOutcome("dismissed", "sg-1", "chapter-1"))
    controller = _controller(coordinator)
    dialog = TranslationQualityDialog()
    controller.attach(dialog)

    dialog.apply_suggestion_requested.emit("sg-1")
    dialog.dismiss_suggestion_requested.emit("sg-2")

    assert coordinator.applied == ["sg-1"]
    assert coordinator.dismissed == ["sg-2"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_suggestions.py tests/qa/test_quality_window_shell.py tests/qa/test_translation_quality_controller.py -v`

Expected: FAIL with `ImportError: cannot import name 'SuggestionCard'`. The shell tests fail on the tab text `Предложения`.

- [ ] **Step 4: Add the card and its wording to the building blocks**

In `quality_widgets.py`:

1. Add after `from datetime import datetime`:

```python
from html import escape
```

2. Add after the `PyQt6.QtWidgets` import:

```python
from ....qa.language_validation import describe_refusal
from ....qa.models import QaSuggestion
from ....qa.text_diff import highlight_pair
```

3. Add after `EMPTY_STATE_TEXT_WIDTH = 560`:

```python
# How a suggestion's category reads on its chip; an unknown code is shown as is.
CATEGORY_LABELS = {
    "typo": "опечатка",
    "grammar": "грамматика",
    "punctuation": "пунктуация",
    "calque": "калька",
    "repetition": "повтор",
    "meta_comment": "служебный комментарий",
    "hallucinated_addition": "добавленный факт",
    "style_suggestion": "стиль",
}


def category_label(code: str) -> str:
    return CATEGORY_LABELS.get(code, code)


def pending_caption(count: int) -> str:
    """«N правок ждут решения», agreeing with the number the way Russian does."""
    tail = abs(count) % 100
    if 11 <= tail <= 19:
        words = "правок ждут"
    elif tail % 10 == 1:
        words = "правка ждёт"
    elif 2 <= tail % 10 <= 4:
        words = "правки ждут"
    else:
        words = "правок ждут"
    return f"{count} {words} решения"
```

4. Append at the end of the file:

```python
class SuggestionCard(QFrame):
    """One refused fix: where, what kind, why it was not applied, and both texts."""

    apply_requested = pyqtSignal(str)
    dismiss_requested = pyqtSignal(str)

    def __init__(
        self, suggestion: QaSuggestion, *, show_chapter: bool = True, parent=None
    ) -> None:
        super().__init__(parent)
        self.suggestion = suggestion
        self.setObjectName("statusSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        if show_chapter:
            top.addWidget(make_label(suggestion.chapter_id, "projectCardTitle", parent=self))
        self.category_chip = StatusChip(category_label(suggestion.category), "neutral", self)
        top.addWidget(self.category_chip)
        reason = (
            f"не принято: {describe_refusal(suggestion.reason)}"
            if suggestion.reason
            else "не принято"
        )
        self.reason_label = make_label(reason, "mutedLabel", wrap=True, parent=self)
        top.addWidget(self.reason_label, 1)
        layout.addLayout(top)

        if suggestion.replacement_text:
            before_html, after_html = highlight_pair(
                suggestion.original_text, suggestion.replacement_text
            )
        else:
            before_html, after_html = escape(suggestion.original_text), "удалить фрагмент"
        self.before_label = self._text_row(layout, "было", before_html)
        self.after_label = self._text_row(layout, "стало", after_html)
        if suggestion.explanation:
            layout.addWidget(
                make_label(suggestion.explanation, "mutedLabel", wrap=True, parent=self)
            )

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.note_label = make_label("", "helperLabel", wrap=True, parent=self)
        actions.addWidget(self.note_label, 1)
        stale = suggestion.status == "stale"
        self.dismiss_button = make_button(
            "Убрать из списка" if stale else "Отклонить", "ghostActionButton", self
        )
        self.dismiss_button.clicked.connect(
            lambda: self.dismiss_requested.emit(self.suggestion.suggestion_id)
        )
        actions.addWidget(self.dismiss_button)
        self.apply_button: QPushButton | None = None
        if stale:
            note = suggestion.status_note
            self.note_label.setText(f"устарело: {note}" if note else "устарело")
        else:
            self.apply_button = make_button("Применить", "compactActionButton", self)
            self.apply_button.clicked.connect(
                lambda: self.apply_requested.emit(self.suggestion.suggestion_id)
            )
            actions.addWidget(self.apply_button)
            if not suggestion.applicable:
                self.note_label.setText("Нет текста замены: такую правку вносит человек.")
        layout.addLayout(actions)
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.dismiss_button.setEnabled(not busy)
        if self.apply_button is not None:
            self.apply_button.setEnabled(not busy and self.suggestion.applicable)

    def _text_row(self, layout: QVBoxLayout, caption: str, html_text: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(10)
        caption_label = make_label(caption, "mutedLabel", parent=self)
        caption_label.setFixedWidth(42)
        # The caption never wraps, so the alignment flag costs it nothing.
        row.addWidget(caption_label, 0, Qt.AlignmentFlag.AlignTop)
        # Rich text only for the diff marks: highlight_pair escapes both texts.
        text_label = QLabel(html_text, self)
        text_label.setTextFormat(Qt.TextFormat.RichText)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(text_label, 1)
        layout.addLayout(row)
        return text_label
```

- [ ] **Step 5: Rewrite the suggestions tab**

Replace the whole of `quality_suggestions_view.py` with:

```python
# -*- coding: utf-8 -*-
"""The «Предложения» tab: language fixes the check proposed but did not apply."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ....qa.models import QaSuggestion
from .quality_widgets import (
    EmptyState,
    SuggestionCard,
    category_label,
    make_button,
    make_label,
    pending_caption,
)


SUGGESTIONS_EMPTY_TITLE = "Непринятых правок нет"
SUGGESTIONS_EMPTY_TEXT = (
    "Правки, которые проверка не приняла, появятся здесь после следующего прохода. "
    "Прошлые проходы их не сохраняли."
)
# Cards are built this many at a time: a pass refreshes the report every few
# seconds, and hundreds of cards of a dozen widgets each would stall it.
SUGGESTION_PAGE_SIZE = 50


class QualitySuggestionsView(QWidget):
    """Every suggestion awaiting a decision, filterable by chapter and category."""

    apply_requested = pyqtSignal(str)
    dismiss_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._suggestions: tuple[QaSuggestion, ...] = ()
        self._busy = False
        self._shown_limit = SUGGESTION_PAGE_SIZE
        self.cards: list[SuggestionCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)
        self.content = QWidget(self.stack)
        self.empty_state = EmptyState(SUGGESTIONS_EMPTY_TITLE, SUGGESTIONS_EMPTY_TEXT, self.stack)
        self.stack.addWidget(self.content)
        self.stack.addWidget(self.empty_state)

        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        filters = QFrame(self.content)
        filters.setObjectName("projectPathCard")
        filter_row = QHBoxLayout(filters)
        filter_row.setContentsMargins(12, 8, 12, 8)
        filter_row.setSpacing(10)
        filter_row.addWidget(make_label("Глава", "mutedLabel", parent=filters))
        self.chapter_filter = QComboBox(filters)
        self.chapter_filter.setMinimumWidth(180)
        filter_row.addWidget(self.chapter_filter)
        filter_row.addWidget(make_label("Категория", "mutedLabel", parent=filters))
        self.category_filter = QComboBox(filters)
        self.category_filter.setMinimumWidth(180)
        filter_row.addWidget(self.category_filter)
        filter_row.addStretch(1)
        self.counter_label = make_label("", "helperLabel", parent=filters)
        filter_row.addWidget(self.counter_label)
        content_layout.addWidget(filters)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.more_button = make_button("", "compactActionButton", self.cards_container)
        self.more_button.clicked.connect(self._show_more)
        area = QScrollArea(self.content)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(self.cards_container)
        content_layout.addWidget(area, 1)

        self.chapter_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.category_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.stack.setCurrentWidget(self.empty_state)

    def set_suggestions(self, suggestions) -> None:
        """Show the suggestions awaiting a decision; an unchanged list is kept as is."""
        suggestions = tuple(suggestions)
        if suggestions == self._suggestions:
            return
        self._suggestions = suggestions
        self._reload_filters()
        self._shown_limit = SUGGESTION_PAGE_SIZE
        self.stack.setCurrentWidget(self.content if suggestions else self.empty_state)
        self._render_cards()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        for card in self.cards:
            card.set_busy(self._busy)

    def visible_suggestions(self) -> tuple[QaSuggestion, ...]:
        chapter = self.chapter_filter.currentData() or ""
        category = self.category_filter.currentData() or ""
        return tuple(
            item
            for item in self._suggestions
            if (not chapter or item.chapter_id == chapter)
            and (not category or item.category == category)
        )

    def _reload_filters(self) -> None:
        chapters = list(dict.fromkeys(item.chapter_id for item in self._suggestions))
        categories = sorted({item.category for item in self._suggestions}, key=category_label)
        for combo, everything, values, label in (
            (self.chapter_filter, "Все главы", chapters, str),
            (self.category_filter, "Все категории", categories, category_label),
        ):
            current = combo.currentData() or ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(everything, "")
            for value in values:
                combo.addItem(label(value), value)
            combo.setCurrentIndex(max(combo.findData(current), 0))
            combo.blockSignals(False)

    def _on_filter_changed(self, *_args) -> None:
        self._shown_limit = SUGGESTION_PAGE_SIZE
        self._render_cards()

    def _show_more(self) -> None:
        self._shown_limit += SUGGESTION_PAGE_SIZE
        self._render_cards()

    def _render_cards(self) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        while self.cards_layout.count():
            self.cards_layout.takeAt(0)
        visible = self.visible_suggestions()
        for suggestion in visible[: self._shown_limit]:
            card = SuggestionCard(suggestion, parent=self.cards_container)
            card.apply_requested.connect(self.apply_requested.emit)
            card.dismiss_requested.connect(self.dismiss_requested.emit)
            card.set_busy(self._busy)
            self.cards_layout.addWidget(card)
            self.cards.append(card)
        hidden = len(visible) - len(self.cards)
        self.more_button.setText(
            f"Показать ещё {min(hidden, SUGGESTION_PAGE_SIZE)} из {hidden}"
        )
        self.more_button.setVisible(hidden > 0)
        self.cards_layout.addWidget(self.more_button)
        self.cards_layout.addStretch(1)
        self.counter_label.setText(pending_caption(len(self._suggestions)))
```

- [ ] **Step 6: List a chapter's suggestions in the report's chapter card**

In `quality_report_view.py`:

1. Add `QScrollArea` to the `PyQt6.QtWidgets` import, and `SuggestionCard` to the `.quality_widgets` import.

2. Add two signals after `open_suggestions_requested = pyqtSignal()`:

```python
    apply_suggestion_requested = pyqtSignal(str)
    dismiss_suggestion_requested = pyqtSignal(str)
```

3. In `_build_chapter_card`, replace the single line `self.chapter_layout.addStretch(1)` with:

```python
        self.pending_title_label = make_label(
            "", "projectCardTitle", parent=self.chapter_card
        )
        self.pending_title_label.setVisible(False)
        self.chapter_layout.addWidget(self.pending_title_label)
        self.pending_container = QWidget()
        self.pending_layout = QVBoxLayout(self.pending_container)
        self.pending_layout.setContentsMargins(0, 0, 0, 0)
        self.pending_layout.setSpacing(8)
        self.pending_layout.addStretch(1)
        self.pending_area = QScrollArea(self.chapter_card)
        self.pending_area.setWidgetResizable(True)
        self.pending_area.setFrameShape(QFrame.Shape.NoFrame)
        self.pending_area.setWidget(self.pending_container)
        self.pending_area.setVisible(False)
        self.chapter_layout.addWidget(self.pending_area, 1)
        self.pending_cards: list[SuggestionCard] = []
        self._pending_suggestions: tuple = ()
        self.chapter_layout.addStretch(1)
```

4. In `_refresh_chapter_card`:

   a. In the `if row is None:` branch, add `self._refresh_pending("")` before its `return`.

   b. Add `self._refresh_pending(row.chapter_id)` as the method's last line.

5. Replace `set_busy` with:

```python
    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        for card in self.pending_cards:
            card.set_busy(self._busy)
        self._update_actions()
```

6. Add after `_refresh_chapter_card`:

```python
    def _refresh_pending(self, chapter_id: str) -> None:
        suggestions = self._snapshot.suggestions_for(chapter_id) if chapter_id else ()
        if suggestions != self._pending_suggestions:
            for card in self.pending_cards:
                card.setParent(None)
                card.deleteLater()
            self.pending_cards = []
            for suggestion in suggestions:
                card = SuggestionCard(
                    suggestion, show_chapter=False, parent=self.pending_container
                )
                card.apply_requested.connect(self.apply_suggestion_requested.emit)
                card.dismiss_requested.connect(self.dismiss_suggestion_requested.emit)
                self.pending_layout.insertWidget(self.pending_layout.count() - 1, card)
                self.pending_cards.append(card)
            self._pending_suggestions = suggestions
        for card in self.pending_cards:
            card.set_busy(self._busy)
        self.pending_title_label.setText(f"Ждут решения: {len(suggestions)}")
        self.pending_title_label.setVisible(bool(suggestions))
        self.pending_area.setVisible(bool(suggestions))
```

- [ ] **Step 7: Carry the decisions and the counter through the shell**

In `translation_quality_dialog.py`:

1. Add two signals after `export_requested = pyqtSignal(str)`:

```python
    apply_suggestion_requested = pyqtSignal(str)
    dismiss_suggestion_requested = pyqtSignal(str)
```

2. In `__init__`, after the `open_suggestions_requested` connection, add:

```python
        self.report_view.apply_suggestion_requested.connect(
            self.apply_suggestion_requested.emit
        )
        self.report_view.dismiss_suggestion_requested.connect(
            self.dismiss_suggestion_requested.emit
        )
        self.suggestions_view.apply_requested.connect(self.apply_suggestion_requested.emit)
        self.suggestions_view.dismiss_requested.connect(
            self.dismiss_suggestion_requested.emit
        )
```

3. In `set_report`, add after `self._snapshot = snapshot`:

```python
        self.suggestions_view.set_suggestions(snapshot.suggestions)
        waiting = len(snapshot.suggestions)
        self.tabs.setTabText(
            self.tabs.indexOf(self.suggestions_view),
            f"Предложения ({waiting})" if waiting else "Предложения",
        )
```

4. In `set_busy`, add after `self.report_view.set_busy(self._busy)`:

```python
        self.suggestions_view.set_busy(self._busy)
```

- [ ] **Step 8: Make the render test draw suggestion cards too**

In `tests/qa/test_quality_window_render.py`, add at the end of `_journal()`, before `return journal`:

```python
    from gemini_translator.qa.models import QaSuggestion

    samples = (
        ("— Спросил он, глядя в окно.", "— спросил он, глядя в окно.", "pending", "validation_declined"),
        ("Он очень-очень устал после долгой дороги.", "", "pending", "no_replacement"),
        ("Трое из них был ранены.", "Трое из них были ранены.", "stale", "low_confidence (0.62 < 0.85)"),
    )
    suggestions = tuple(
        QaSuggestion(
            suggestion_id=QaSuggestion.identity("chapter-2", "n.1", before, after),
            chapter_id="chapter-2",
            block_id="n.1",
            category="punctuation",
            original_text=before,
            replacement_text=after,
            reason=reason,
            explanation="Модель считает правку спорной и оставляет решение человеку.",
            status=status,
            status_note="глава изменилась после проверки" if status == "stale" else "",
        )
        for before, after, status, reason in samples
    )
    journal.suggestions.extend(suggestions)
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/qa/test_quality_suggestions.py tests/qa/test_quality_window_shell.py tests/qa/test_translation_quality_controller.py tests/qa/test_quality_report_view.py tests/qa/test_quality_window_render.py tests/qa/test_quality_widgets.py -v`

Expected: PASS. If the render test reports a cut caption on a suggestion card, fix the card's layout as described in Task 10 Step 2 and rerun.

- [ ] **Step 10: Commit**

```bash
git add gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py tests/qa/test_quality_suggestions.py tests/qa/test_quality_window_shell.py tests/qa/test_translation_quality_controller.py tests/qa/test_quality_window_render.py
git commit -m "feat(ui): decide on refused fixes in the suggestions tab and the chapter card

Co-Authored-By: <the model that wrote this commit>"
```

---

### Task 19: Verify stage 3, show it, and fast-forward main

**Files:** none changed, unless a check fails.

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider`

Expected: every test passes.

- [ ] **Step 2: Lint**

Run:

```bash
.venv/bin/python -m ruff check gemini_translator/qa/models.py gemini_translator/qa/journal.py gemini_translator/qa/service.py gemini_translator/qa/report_snapshot.py gemini_translator/core/chapter_qa_coordinator.py gemini_translator/ui/dialogs/validation_dialogs/ tests/qa/test_qa_suggestion_model.py tests/qa/test_qa_journal.py tests/qa/test_translation_quality_service.py tests/qa/test_report_snapshot_suggestions.py tests/qa/test_chapter_qa_coordinator.py tests/qa/test_translation_quality_controller.py tests/qa/test_quality_suggestions.py tests/qa/test_quality_window_shell.py tests/qa/test_quality_window_render.py
python3 ~/.claude/ux-ui-agent-skills/scripts/lint_hardcodes.py --ext .py gemini_translator/ui/dialogs/validation_dialogs/quality_widgets.py gemini_translator/ui/dialogs/validation_dialogs/quality_suggestions_view.py gemini_translator/ui/dialogs/validation_dialogs/quality_report_view.py gemini_translator/ui/dialogs/validation_dialogs/translation_quality_dialog.py; echo "lint_hardcodes exit=$?"
```

Expected: `All checks passed!` and `lint_hardcodes exit=0`.

- [ ] **Step 3: Mutation checks — decisions stay decided, silence keeps suggestions, rollback, the right chapter**

Define `mutate` exactly as in Task 11 Step 3, then run:

```bash
mutate gemini_translator/qa/journal.py \
  "if item.suggestion_id in decided or item.suggestion_id in seen:" "if item.suggestion_id in seen:" \
  "tests/qa/test_qa_journal.py::test_a_new_pass_replaces_undecided_suggestions_and_never_revives_decided_ones"
mutate gemini_translator/qa/service.py \
  "    if language is None:
        return None" "    if language is None:
        return ()" \
  "tests/qa/test_translation_quality_service.py::test_a_pass_without_the_language_check_leaves_suggestions_alone"
mutate gemini_translator/qa/service.py \
  "                atomic_write_bytes(path, before)
            except OSError:
                pass" "                pass
            except OSError:
                pass" \
  "tests/qa/test_translation_quality_service.py::test_a_fix_the_repair_store_cannot_record_is_rolled_back"
mutate gemini_translator/core/chapter_qa_coordinator.py \
  "if event.chapter_id == chapter_id" "if event.chapter_id" \
  "tests/qa/test_chapter_qa_coordinator.py::test_a_suggestion_is_applied_to_its_chapters_translation"
git status --short
```

Expected:
- Each of the four runs reports a failure.
- `git status --short` prints nothing.

- [ ] **Step 4: Apply a suggestion end to end on a copy of a real chapter**

This runs the real service against a real HTML file in the scratchpad and never touches a book:

```bash
.venv/bin/python - <<'EOF'
import asyncio
import shutil
from pathlib import Path

from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import QaChapterState, QaSuggestion
from gemini_translator.qa.repair_store import RepairStore
from gemini_translator.utils.epub_json import build_html_document_model, build_translation_payload

scratch = Path("/private/tmp/claude-501/-Users-rasreo-dev-translatorFork-MOD/e2bcd293-1ab9-49c0-bf29-e482b5dd69a7/scratchpad/e2e-suggestion")
shutil.rmtree(scratch, ignore_errors=True)
scratch.mkdir(parents=True)
chapter = scratch / "chapter-1.html"
chapter.write_text(
    "<html><head><title>t</title></head><body><h1>Глава 1</h1>"
    "<p>— Спросил он, глядя в окно.</p><p>Он <i>сразу</i> ушёл.</p></body></html>",
    encoding="utf-8",
)
original = chapter.read_bytes()
blocks = build_translation_payload(build_html_document_model(chapter.read_text(encoding="utf-8"), document_id="chapter-1"))["blocks"]
block_id = next(block["id"] for block in blocks if "Спросил" in "".join(i.get("text", "") for i in block["inlines"]))

import sys

sys.path.insert(0, str(Path("tests/qa").resolve()))
import test_translation_quality_service as helpers  # tests/ is not a package
service, journal, path = helpers._service(scratch, aligner=helpers._CleanAligner())
suggestion = QaSuggestion(
    suggestion_id=QaSuggestion.identity("chapter-1", block_id, "— Спросил", "— спросил"),
    chapter_id="chapter-1", block_id=block_id, category="punctuation",
    original_text="— Спросил", replacement_text="— спросил", reason="punctuation_rewrite",
)
journal.record_chapter_result(state=QaChapterState(chapter_id="chapter-1", status="checked"), suggestions=(suggestion,))
print("apply:", asyncio.run(service.apply_suggestion(suggestion.suggestion_id, chapter)))
print("after:", chapter.read_text(encoding="utf-8"))
print("undo:", asyncio.run(service.undo_chapter("chapter-1")))
print("restored byte for byte:", chapter.read_bytes() == original)
EOF
```

Expected:
- `apply: SuggestionOutcome(status='applied', …)`.
- The `after:` HTML contains `— спросил`, and `<h1>`, `<title>` and the `<i>` markup are still there.
- `undo:` reports `status='restored'`.
- `restored byte for byte: True`.

- [ ] **Step 5: Draw the window with suggestions and show it**

Add these lines to `render_quality_window.py`, right after the repair loop and before `snapshot = BookQaReportSnapshot.from_journal(journal)`:

```python
from gemini_translator.qa.models import QaSuggestion  # noqa: E402

for chapter_id, category, before, after, reason, status in (
    ("Глава 12", "punctuation", "— Спросил он, глядя в окно.", "— спросил он, глядя в окно.", "punctuation_rewrite", "pending"),
    ("Глава 12", "repetition", "Он очень-очень устал.", "", "no_replacement", "pending"),
    ("Глава 14", "calque", "Он сделал глубокий вдох и шагнул вперёд.", "Он глубоко вдохнул и шагнул вперёд.", "validation_declined", "pending"),
    ("Глава 19", "grammar", "Трое из них был ранены.", "Трое из них были ранены.", "low_confidence (0.62 < 0.85)", "stale"),
):
    journal.suggestions.append(
        QaSuggestion(
            suggestion_id=QaSuggestion.identity(chapter_id, "n.1", before, after),
            chapter_id=chapter_id,
            block_id="n.1",
            category=category,
            original_text=before,
            replacement_text=after,
            reason=reason,
            status=status,
            status_note="глава изменилась после проверки" if status == "stale" else "",
        )
    )
```

Run it with the output directory `.../scratchpad/stage3-shots`, as in Task 11 Step 4.

1. Read every image.
2. Compare the report and suggestions tabs with `mock-report.png` and `mock-suggestions.png`.
3. Send the light report, the light suggestions and the dark suggestions images to the owner with SendUserFile.
4. List the visible differences from the mockups in one line each.

- [ ] **Step 6: Fast-forward main**

1. Run the four checks from Task 3 Step 4 again.
2. Tell the owner, in one sentence, that from this merge on the journal is written as version 3, and an application build older than this merge refuses to open it.
3. Run `git -C /Users/rasreo/dev/translatorFork_MOD merge --ff-only feature/quality-window-redesign`.

Expected: `Fast-forward`. Do not push.
