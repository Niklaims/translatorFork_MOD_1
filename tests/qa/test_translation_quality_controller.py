"""The quality section must drive the QA runtime and report honestly."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from gemini_translator.core.chapter_qa_coordinator import (
    BookQaResult,
    TranslationReadyEvent,
)
from gemini_translator.qa.journal import QaJournal
from gemini_translator.qa.models import ChapterMetrics, RiskLevel
from gemini_translator.qa.repair_store import UndoResult
from gemini_translator.qa.service import ChapterQaResult
from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller import (
    TranslationQualityController,
)


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Coordinator:
    """Runs the same coroutines the real one does, but on this thread."""

    def __init__(self, *, book_result=None, undo_result=None, error=None) -> None:
        self.book_result = book_result
        self.undo_result = undo_result or UndoResult("restored", ("chapter-1",))
        self.error = error
        self.cancelled = False
        self.reset_calls = 0
        self.checked: list[str] = []

    def run_background(self, factory, on_done=None):
        try:
            result = asyncio.run(factory())
            error = None
        except Exception as failure:  # noqa: BLE001 - mirrors the real callback
            result, error = None, failure
        if on_done is not None:
            on_done(result, error)

    def reset_cancellation(self):
        self.reset_calls += 1

    def cancel(self):
        self.cancelled = True

    async def check_chapter_now(self, event, options=None):
        if self.error is not None:
            raise self.error
        self.checked.append(event.chapter_id)
        return ChapterQaResult(
            chapter_id=event.chapter_id,
            risk_level=RiskLevel.LOW,
            may_continue_translation=True,
            coverage_mode="semantic_alignment",
        )

    async def check_all_now(self, events, options=None, on_progress=None, on_chapter=None):
        if self.error is not None:
            raise self.error
        self.checked.extend(event.chapter_id for event in events)
        for index, event in enumerate(events, start=1):
            if callable(on_progress):
                on_progress(index, len(events), event.chapter_id)
        return self.book_result or BookQaResult(
            results=tuple(
                ChapterQaResult(
                    chapter_id=event.chapter_id,
                    risk_level=RiskLevel.LOW,
                    may_continue_translation=True,
                    coverage_mode="semantic_alignment",
                )
                for event in events
            )
        )

    async def undo_chapter(self, chapter_id):
        return self.undo_result

    async def undo_all(self):
        return self.undo_result


def _journal() -> QaJournal:
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
    return journal


def _event(chapter_id: str) -> TranslationReadyEvent:
    return TranslationReadyEvent(
        task_id="manual",
        chapter_id=chapter_id,
        source_path=chapter_id,
        translated_path=f"/tmp/{chapter_id}.html",
        source_language="auto",
        target_language="ru",
    )


def _controller(coordinator, *, events=("chapter-1",), journal_loader=None):
    return TranslationQualityController(
        coordinator_provider=lambda: coordinator,
        journal_loader=journal_loader or _journal,
        gates_provider=lambda: (),
        event_builder=lambda chapter_ids: tuple(
            _event(chapter_id)
            for chapter_id in (chapter_ids or events)
            if chapter_id in events
        ),
    )


def test_a_line_from_the_running_check_lands_in_the_log_without_its_tag(qt_app):
    """Ключи, сервер, сбой — то, что проверка говорит между главами."""
    controller = _controller(_Coordinator())
    logged = []
    controller.chapter_logged.connect(logged.append)

    controller.note(
        "[QA] Ключ …1234 отдыхает 60 с по просьбе сервиса, проверка берёт следующий."
    )

    assert logged == [
        "<p>Ключ …1234 отдыхает 60 с по просьбе сервиса, проверка берёт следующий.</p>"
    ]


def test_a_line_from_the_running_check_is_text_not_markup(qt_app):
    controller = _controller(_Coordinator())
    logged = []
    controller.chapter_logged.connect(logged.append)

    controller.note("Ошибка сервера (500): <html>")
    controller.note("   ")

    assert logged == ["<p>Ошибка сервера (500): &lt;html&gt;</p>"]


def test_report_is_rebuilt_from_the_journal(qt_app):
    """The report must come from the durable record, not from memory."""
    controller = _controller(_Coordinator())
    snapshots = []
    controller.report_ready.connect(snapshots.append)

    controller.refresh_report()

    assert snapshots
    assert [row.chapter_id for row in snapshots[-1].rows] == ["chapter-1"]


def test_a_broken_journal_is_reported_not_swallowed(qt_app):
    """A damaged decision history must be visible, not an empty report."""

    def broken():
        raise RuntimeError("journal is corrupted")

    controller = _controller(_Coordinator(), journal_loader=broken)
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.refresh_report()

    assert statuses and "corrupted" in statuses[-1]


def test_checking_one_chapter_runs_and_refreshes(qt_app):
    """One manual check must use the same cascade and update the report."""
    coordinator = _Coordinator()
    controller = _controller(coordinator)
    statuses, busy = [], []
    controller.status_changed.connect(statuses.append)
    controller.busy_changed.connect(busy.append)

    controller.check_chapter("chapter-1")

    assert coordinator.checked == ["chapter-1"]
    assert busy == [True, False]
    assert "chapter-1" in statuses[-1]


def test_checking_a_chapter_without_a_translation_costs_nothing(qt_app):
    """A chapter with no saved translation must not start a pass."""
    coordinator = _Coordinator()
    controller = _controller(coordinator)
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.check_chapter("chapter-404")

    assert coordinator.checked == []
    assert "нет сохранённого перевода" in statuses[-1]


def test_book_pass_reports_counts_and_blocked_chapters(qt_app):
    """A whole-book pass must say what it did and what still needs a decision."""
    coordinator = _Coordinator(
        book_result=BookQaResult(
            results=(
                ChapterQaResult(
                    chapter_id="chapter-1",
                    risk_level=RiskLevel.HIGH,
                    may_continue_translation=False,
                    coverage_mode="semantic_alignment",
                ),
            ),
            skipped=("chapter-2",),
        )
    )
    controller = _controller(coordinator, events=("chapter-1", "chapter-2"))
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.check_all()

    assert coordinator.reset_calls == 1
    assert "Проверено глав: 1 из 2" in statuses[-1]
    assert "Пропущено: 1" in statuses[-1]
    assert "chapter-1" in statuses[-1]


def test_book_pass_says_the_rest_of_the_book_waits_for_keys(qt_app):
    """Главы, до которых не дошли из-за ключей, раньше тонули в «Пропущено: N»."""
    coordinator = _Coordinator(
        book_result=BookQaResult(
            results=(
                ChapterQaResult(
                    chapter_id="chapter-1",
                    risk_level=RiskLevel.LOW,
                    may_continue_translation=True,
                    coverage_mode="semantic_alignment",
                ),
            ),
            skipped=("chapter-2", "chapter-3"),
            stopped=("chapter-2", "chapter-3"),
        )
    )
    controller = _controller(
        coordinator, events=("chapter-1", "chapter-2", "chapter-3")
    )
    statuses, logged = [], []
    controller.status_changed.connect(statuses.append)
    controller.chapter_logged.connect(logged.append)

    controller.check_all()

    assert "Ключи для проверки больше недоступны" in statuses[-1]
    assert "продолжите проверку" in statuses[-1]
    notes = [line for line in logged if "Ключи для проверки больше недоступны" in line]
    assert len(notes) == 1
    assert "не проверено глав: 2" in notes[0]


def test_unreadable_chapters_are_not_blamed_on_the_keys(qt_app):
    coordinator = _Coordinator(
        book_result=BookQaResult(results=(), skipped=("chapter-1",))
    )
    controller = _controller(coordinator)
    statuses, logged = [], []
    controller.status_changed.connect(statuses.append)
    controller.chapter_logged.connect(logged.append)

    controller.check_all()

    assert "Пропущено: 1" in statuses[-1]
    assert "Ключи" not in statuses[-1]
    assert not any("Ключи" in line for line in logged)


def test_a_failing_pass_is_reported_and_clears_busy(qt_app):
    """A crash inside QA must release the interface and say what happened."""
    controller = _controller(_Coordinator(error=RuntimeError("boom")))
    statuses, busy = [], []
    controller.status_changed.connect(statuses.append)
    controller.busy_changed.connect(busy.append)

    controller.check_chapter("chapter-1")

    assert busy == [True, False]
    assert "boom" in statuses[-1]


def test_undo_reports_restored_and_conflicting_chapters(qt_app):
    """Undo must distinguish what it restored from what a human had edited."""
    coordinator = _Coordinator(
        undo_result=UndoResult("manual_edit_conflict", ("chapter-1",))
    )
    controller = _controller(coordinator)
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.undo_chapter("chapter-1")

    assert "вручную" in statuses[-1]
    assert "chapter-1" in statuses[-1]


def test_cancel_stops_the_runtime_and_the_busy_state(qt_app):
    """Cancelling must reach the runtime, not only the interface."""
    coordinator = _Coordinator()
    controller = _controller(coordinator)
    controller.check_all()

    controller.cancel()

    assert coordinator.cancelled is True


def test_missing_setup_is_explained_instead_of_failing_silently(qt_app):
    """Without a configured QA runtime the user must learn what to set up."""
    controller = TranslationQualityController(
        coordinator_provider=lambda: None,
        journal_loader=_journal,
        event_builder=lambda chapter_ids: (_event("chapter-1"),),
    )
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.check_all()

    assert "Проверка недоступна" in statuses[-1]
    assert "модель проверки" in statuses[-1]


def test_attaching_a_dialog_connects_both_directions(qt_app):
    """The dialog's actions and the controller's report must be wired once."""
    from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog

    coordinator = _Coordinator()
    controller = _controller(coordinator)
    dialog = TranslationQualityDialog()

    controller.attach(dialog)

    assert dialog.report_view.table.rowCount() == 1
    dialog.select_chapter("chapter-1")
    dialog.check_chapter_requested.emit("chapter-1")
    assert coordinator.checked == ["chapter-1"]


def test_embedding_probe_refuses_an_incomplete_setup(qt_app):
    """Testing a connection that cannot be built must explain, not throw."""
    from gemini_translator.qa.settings import QaSettings

    controller = _controller(_Coordinator())
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.test_embedding(QaSettings(embedding_provider="openai_compatible"))

    assert statuses and "ключ" in statuses[-1].lower()


def test_embedding_probe_reports_a_provider_that_cannot_be_built(qt_app):
    """A provider with nothing configured must be named as a setup problem."""
    from gemini_translator.qa.settings import QaSettings
    from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller import (
        _probe_embedding,
    )

    message = _probe_embedding(QaSettings(embedding_provider="gemini"))

    assert "не настроен" in message


def test_embedding_probe_reports_a_missing_local_model(qt_app):
    """Choosing the local model without installing it must say exactly that."""
    from gemini_translator.qa.settings import QaSettings
    from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller import (
        _probe_embedding,
    )

    message = _probe_embedding(QaSettings(embedding_provider="local_onnx"))

    assert "не удалось" in message.lower() or "не настроен" in message.lower()


def test_export_writes_the_bundle_and_reports_where(qt_app, tmp_path):
    """An export the user cannot find is not an export."""
    controller = _controller(_Coordinator())
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.export_report(str(tmp_path))

    assert (tmp_path / "chapters.csv").is_file()
    assert (tmp_path / "glossary.csv").is_file()
    assert str(tmp_path) in statuses[-1]


def test_export_reports_a_broken_journal_instead_of_writing_nothing(qt_app, tmp_path):
    """A silent no-op would look exactly like a successful export."""

    def broken():
        raise RuntimeError("journal is corrupted")

    controller = _controller(_Coordinator(), journal_loader=broken)
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.export_report(str(tmp_path))

    assert "corrupted" in statuses[-1]
    assert not list(tmp_path.glob("*.csv"))


def test_the_progress_bar_names_the_chapter_and_estimates_the_rest(qt_app):
    """Полоса, которая молчит до конца прохода, ничего не сообщает."""
    coordinator = _Coordinator()
    controller = _controller(coordinator, events=("chapter-1", "chapter-2", "chapter-3"))
    updates = []
    controller.progress_changed.connect(lambda *args: updates.append(args))

    controller.check_all()

    assert updates[0] == (0, 3, "")
    assert [item[0] for item in updates[1:4]] == [1, 2, 3]
    assert updates[1][2] == "chapter-1"
    # The estimate appears only once the pass has a pace to estimate from.
    assert "осталось" not in updates[1][2]
    assert "осталось" in updates[2][2]


def test_the_estimate_survives_a_coarse_monotonic_clock(qt_app, monkeypatch):
    """Та же грубость часов молча отменяла оценку остатка на Windows."""
    import time

    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    coordinator = _Coordinator()
    controller = _controller(coordinator, events=("chapter-1", "chapter-2", "chapter-3"))
    updates = []
    controller.progress_changed.connect(lambda *args: updates.append(args))

    controller.check_all()

    assert "осталось" in updates[2][2]


def test_a_duration_is_spelled_the_way_a_waiting_person_reads_it():
    from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller import (
        _humanize_seconds,
    )

    assert _humanize_seconds(0) == "0 с"
    assert _humanize_seconds(45) == "45 с"
    assert _humanize_seconds(90) == "2 мин"
    assert _humanize_seconds(100) == "2 мин"
    assert _humanize_seconds(3700) == "1 ч 01 мин"
    assert _humanize_seconds(-5) == "0 с"


def test_embedding_probe_forwards_app_proxy_settings(qt_app, monkeypatch):
    """Проба «Проверить подключение» должна ходить через тот же прокси
    приложения, что и боевой QA-прогон: с trust_env=False у сессии другого
    источника прокси больше нет, и проба без proxy_settings уходила напрямую."""
    from gemini_translator.qa import assembly
    from gemini_translator.qa.settings import QaSettings
    from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller import (
        _probe_embedding,
    )

    seen = []

    def fake_factory(proxy_settings=None):
        seen.append(proxy_settings)
        raise RuntimeError("stop here")

    monkeypatch.setattr(assembly, "aiohttp_session_factory", fake_factory)
    proxy = {"enabled": True, "type": "SOCKS5", "host": "127.0.0.1", "port": "1080"}

    message = _probe_embedding(QaSettings(embedding_provider="gemini"), proxy_settings=proxy)

    assert seen == [proxy]
    assert "не настроен" in message


def test_current_proxy_settings_come_from_the_app_settings_manager():
    from gemini_translator.ui.dialogs.validation_dialogs.translation_quality_controller import (
        _current_proxy_settings,
    )

    proxy = {"enabled": True, "type": "HTTP", "host": "proxy.local", "port": "3128"}

    class _Manager:
        def load_proxy_settings(self):
            return dict(proxy)

    class _App:
        def get_settings_manager(self):
            return _Manager()

    class _BrokenApp:
        def get_settings_manager(self):
            raise RuntimeError("settings unavailable")

    assert _current_proxy_settings(_App()) == proxy
    assert _current_proxy_settings(object()) is None
    assert _current_proxy_settings(_BrokenApp()) is None


def test_the_probe_answer_also_goes_to_the_settings_card(qt_app):
    from gemini_translator.qa.settings import QaSettings

    controller = _controller(_Coordinator())
    answers: list[str] = []
    controller.embedding_checked.connect(answers.append)

    controller.test_embedding(QaSettings(embedding_provider="openai_compatible"))

    assert answers and "ключ" in answers[-1].lower()


class _PendingCoordinator(_Coordinator):
    """Starts a pass and keeps it running until the test finishes it."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.pending = None

    def run_background(self, factory, on_done=None):
        self.pending = (factory, on_done)

    def finish(self):
        factory, on_done = self.pending
        self.pending = None
        try:
            result, error = asyncio.run(factory()), None
        except BaseException as failure:  # noqa: BLE001 - mirrors the real callback
            result, error = None, failure
        if on_done is not None:
            on_done(result, error)


def test_stopping_keeps_the_window_busy_until_the_pass_really_stops(qt_app):
    """«Остановить» снимал занятость сразу — поверх недоостановленного прохода запускался второй."""
    coordinator = _PendingCoordinator()
    controller = _controller(coordinator, events=("chapter-1", "chapter-2"))
    statuses, busy = [], []
    controller.status_changed.connect(statuses.append)
    controller.busy_changed.connect(busy.append)

    controller.check_all()
    controller.cancel()

    assert coordinator.cancelled is True
    assert busy == [True]
    assert statuses[-1] == "Останавливаю проверку…"

    coordinator.finish()

    assert busy == [True, False]
    assert statuses[-1] == "Проверка остановлена: проверено 2 из 2."


def test_a_stop_that_interrupts_a_chapter_is_not_reported_as_a_failure(qt_app):
    import concurrent.futures

    class _Interrupted(_PendingCoordinator):
        async def check_all_now(self, events, options=None, on_progress=None, on_chapter=None):
            if callable(on_progress):
                on_progress(1, len(events), events[0].chapter_id)
            raise concurrent.futures.CancelledError()

    coordinator = _Interrupted()
    controller = _controller(coordinator, events=("chapter-1", "chapter-2", "chapter-3"))
    statuses = []
    controller.status_changed.connect(statuses.append)

    controller.check_all()
    controller.cancel()
    coordinator.finish()

    assert statuses[-1] == "Проверка остановлена: проверено 1 из 3."


def test_checking_one_chapter_clears_an_earlier_stop(qt_app):
    """После остановленного прохода проверка одной главы отменялась, не начавшись."""
    coordinator = _Coordinator()
    controller = _controller(coordinator)

    controller.check_chapter("chapter-1")

    assert coordinator.reset_calls == 1


def test_the_estimate_comes_first_and_the_chapter_is_named_by_its_file(qt_app):
    """Полоса показывала «з 484 — OEBPS/chapter13.xhtml · ост»: число и оценка обрезались."""
    coordinator = _Coordinator()
    events = ("OEBPS/chapter1.xhtml", "OEBPS/chapter2.xhtml", "OEBPS/chapter3.xhtml")
    controller = _controller(coordinator, events=events)
    updates = []
    controller.progress_changed.connect(lambda *args: updates.append(args))

    controller.check_all()

    assert updates[1][2] == "chapter1"
    assert updates[2][2].startswith("осталось ~")
    assert updates[2][2].endswith(" · chapter2")


def test_the_pass_header_counts_chapters_the_russian_way(qt_app):
    controller = _controller(_Coordinator(), events=("chapter-1", "chapter-2"))
    logged = []
    controller.chapter_logged.connect(logged.append)

    controller.check_all()

    assert "Проверка книги: 2 главы." in logged[0]


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
    statuses, busy, reports, deciding = [], [], [], []
    controller.status_changed.connect(statuses.append)
    controller.busy_changed.connect(busy.append)
    controller.report_ready.connect(reports.append)
    controller.deciding_changed.connect(deciding.append)

    controller.apply_suggestion("sg-1")

    assert coordinator.applied == ["sg-1"]
    # A decision locks its own card, not the whole window.
    assert busy == []
    assert deciding == [frozenset({"sg-1"}), frozenset()]
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
        "Правку применить нельзя: глава изменилась после проверки. Файл главы не тронут."
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


def test_a_crash_while_applying_is_reported_and_releases_the_card(qt_app):
    class _Crashing(_Coordinator):
        async def apply_suggestion(self, suggestion_id):
            raise RuntimeError("disk full")

    controller = _controller(_Crashing())
    statuses, busy, deciding = [], [], []
    controller.status_changed.connect(statuses.append)
    controller.busy_changed.connect(busy.append)
    controller.deciding_changed.connect(deciding.append)

    controller.apply_suggestion("sg-1")

    assert busy == []
    assert deciding[-1] == frozenset()
    assert "disk full" in statuses[-1]


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


def test_a_fix_can_be_decided_while_a_pass_runs(qt_app):
    """Правки ждали конца многочасового прохода, хотя проход их не касался."""
    from gemini_translator.qa.service import SuggestionOutcome

    coordinator = _SuggestionCoordinator(SuggestionOutcome("applied", "sg-1", "chapter-1"))
    controller = _controller(coordinator)
    busy: list[bool] = []
    controller.busy_changed.connect(busy.append)
    controller._set_busy(True)  # a pass is running

    controller.apply_suggestion("sg-1")
    controller.dismiss_suggestion("sg-2")

    assert coordinator.applied == ["sg-1"]
    assert coordinator.dismissed == ["sg-2"]
    assert busy == [True]


def test_a_chapter_being_checked_says_to_apply_after_it(qt_app):
    from gemini_translator.qa.service import SuggestionOutcome

    coordinator = _SuggestionCoordinator(
        SuggestionOutcome("busy", "sg-1", "OEBPS/chapter12.xhtml", "глава сейчас проверяется")
    )
    controller = _controller(coordinator)
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)

    controller.apply_suggestion("sg-1")

    assert statuses[-1] == "Глава «chapter12» сейчас проверяется — примените правку после неё."


def test_the_window_hears_which_chapters_are_being_checked(qt_app):
    from gemini_translator.qa.service import SuggestionOutcome
    from gemini_translator.ui.dialogs.validation_dialogs import TranslationQualityDialog

    class _Listening(_SuggestionCoordinator):
        listener = None

        def set_checking_listener(self, listener):
            self.listener = listener

    coordinator = _Listening(SuggestionOutcome("dismissed", "sg-1", "chapter-1"))
    controller = _controller(coordinator)
    heard: list[frozenset] = []
    controller.checking_changed.connect(heard.append)

    controller.attach(TranslationQualityDialog())
    coordinator.listener(frozenset({"chapter-2"}))

    assert heard[-1] == frozenset({"chapter-2"})
