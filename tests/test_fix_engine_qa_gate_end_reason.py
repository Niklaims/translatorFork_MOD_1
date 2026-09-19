"""Завершение перевода сообщает о замечаниях QA без заявления о блокировке."""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from gemini_translator.core.translation_engine import TranslationEngine


_MISSING = object()


def _engine(events, *, gate_open: bool):
    engine = TranslationEngine.__new__(TranslationEngine)
    engine.is_session_finishing = False
    engine.is_soft_stopping = False
    engine.task_manager = MagicMock()
    engine.task_manager.is_finished.return_value = True
    engine.task_manager.has_blocking_qa_gate.return_value = gate_open
    engine.api_key_manager = MagicMock()
    engine.keys_map = {}
    engine.active_workers_map = {}
    engine.pending_launches = 0
    engine._post_event = lambda name, data=None: events.append((name, data or {}))
    engine._start_final_qa_pass = lambda: False
    engine.show_summary_data = lambda: None
    engine._end_session = lambda reason: events.append(("end", {"reason": reason}))
    return engine


def _end_reason(events):
    reasons = [data["reason"] for name, data in events if name == "end"]
    assert len(reasons) == 1, events
    return reasons[0]


def test_open_high_gate_is_reported_as_qa_risk_after_translation():
    events = []
    _engine(events, gate_open=True)._check_if_session_finished()
    reason = _end_reason(events)
    assert "успешно" not in reason.lower()
    assert "qa" in reason.lower() or "проверк" in reason.lower()
    messages = [data.get("message", "") for name, data in events if name == "log_message"]
    assert "заблокирован" not in reason.lower()
    assert all("заблокирован" not in message.lower() for message in messages)


def test_without_gate_the_success_message_is_unchanged():
    events = []
    _engine(events, gate_open=False)._check_if_session_finished()
    assert _end_reason(events) == "Сессия успешно завершена"


@pytest.fixture()
def session_coordinator():
    """Put a session's QA coordinator on the application, and take it off after."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    previous = getattr(app, "qa_coordinator", _MISSING)

    def install(unchecked):
        app.qa_coordinator = SimpleNamespace(unchecked_chapter_count=lambda: unchecked)

    yield install
    if previous is _MISSING:
        if hasattr(app, "qa_coordinator"):
            delattr(app, "qa_coordinator")
    else:
        app.qa_coordinator = previous


def _qa_lines(events):
    return [
        data.get("message", "")
        for name, data in events
        if name == "log_message" and data.get("message", "").startswith("[QA]")
    ]


def test_translation_that_outran_the_check_says_what_is_left(session_coordinator):
    """The session ends on its own and names what the check did not reach."""
    session_coordinator(3)
    events = []

    _engine(events, gate_open=False)._check_if_session_finished()

    lines = _qa_lines(events)
    assert len(lines) == 1
    assert "3" in lines[0]
    assert "Продолжить проверку" in lines[0]
    assert _end_reason(events) == "Сессия успешно завершена"


def test_a_check_that_kept_up_adds_nothing(session_coordinator):
    session_coordinator(0)
    events = []

    _engine(events, gate_open=False)._check_if_session_finished()

    assert _qa_lines(events) == []
    assert _end_reason(events) == "Сессия успешно завершена"
