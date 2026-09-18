"""Регрессионные тесты для двух дефектов cli.py:

1. CliSessionObserver.on_timeout эмитил manual_stop_requested напрямую в
   event_posted.emit, в обход event_bus.emit_event — из-за этого при
   срабатывании --timeout не вызывался inflight.cancel_all() для зависших
   MCP AI-запросов (mcp-bench-cli/bugs/5-cli-timeout-raw-emit-skips-inf).

2. command_generate/command_glossary_generate/command_untranslated_fix
   вызывали runtime.shutdown() обычной инструкцией, а не в finally — при
   исключении между bootstrap() и concluding shutdown() движок/прокси/
   настройки не освобождались (mcp-bench-cli/bugs/4-cli-shutdown-not-in-finally).
"""

import types
from argparse import Namespace

import pytest

from gemini_translator.cli import (
    CliError,
    CliSessionObserver,
    command_generate,
    command_glossary_generate,
    command_untranslated_fix,
)


# --- Находка 5: on_timeout должен идти через emit_event ---------------------


class _FakeEventPosted:
    def __init__(self):
        self.raw_emits = []

    def emit(self, event):
        self.raw_emits.append(event)


class _FakeEventBus:
    """Минимальная модель EventBus.emit_event: для STOP_EVENTS снимает inflight MCP-запросы."""

    STOP_EVENTS = frozenset({"manual_stop_requested", "stop_session_requested"})

    def __init__(self):
        self.event_posted = _FakeEventPosted()
        self.cancel_calls = 0
        self.emit_event_calls = []

    def emit_event(self, event):
        self.emit_event_calls.append(event)
        if isinstance(event, dict) and event.get("event") in self.STOP_EVENTS:
            self.cancel_calls += 1
        self.event_posted.emit(event)


class _FakeApp:
    def __init__(self):
        self.event_bus = _FakeEventBus()
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


class _FakeQTimer:
    def __init__(self):
        self.scheduled = []

    def singleShot(self, msec, callback):
        self.scheduled.append((msec, callback))


class _FakeQtCore:
    def __init__(self):
        self.QTimer = _FakeQTimer()


def test_on_timeout_uses_emit_event_so_stop_cancels_inflight_mcp_requests():
    """--timeout должен снимать зависшие MCP-запросы так же, как обычный стоп из GUI."""
    fake_self = types.SimpleNamespace(
        app=_FakeApp(),
        QtCore=_FakeQtCore(),
        finished=False,
        timed_out=False,
        reason=None,
        timeout_sec=42,
    )

    CliSessionObserver.on_timeout(fake_self)

    assert fake_self.timed_out is True
    assert fake_self.reason == "timeout after 42s"
    assert fake_self.app.event_bus.cancel_calls == 1, (
        "on_timeout обязан слать manual_stop_requested через emit_event, "
        "иначе inflight.cancel_all() не вызывается и зависшие MCP-запросы не отменяются"
    )
    assert len(fake_self.app.event_bus.emit_event_calls) == 1, (
        "on_timeout должен слать событие через emit_event ровно один раз"
    )
    assert fake_self.app.event_bus.emit_event_calls[0]["event"] == "manual_stop_requested"
    # Приложение всё равно должно завершиться через 5 секунд, как раньше.
    assert fake_self.QtCore.QTimer.scheduled[-1][0] == 5000
    assert fake_self.QtCore.QTimer.scheduled[-1][1] == fake_self.app.quit


# --- Находка 4: runtime.shutdown() должен быть в finally --------------------


class _ShutdownTrackingRuntime:
    """Подставной HeadlessRuntime, фиксирующий, был ли вызван shutdown()."""

    instances = []

    def __init__(self):
        self.shutdown_called = False
        _ShutdownTrackingRuntime.instances.append(self)

    def bootstrap(self, *, include_engine):
        return Namespace(settings_manager=object())

    def shutdown(self):
        self.shutdown_called = True


@pytest.fixture(autouse=True)
def _reset_runtime_instances():
    _ShutdownTrackingRuntime.instances = []
    yield
    _ShutdownTrackingRuntime.instances = []


def test_command_generate_shuts_down_engine_when_body_raises(monkeypatch):
    from gemini_translator import cli

    monkeypatch.setattr(cli, "HeadlessRuntime", _ShutdownTrackingRuntime)

    def _raise(*args, **kwargs):
        raise CliError("boom")

    monkeypatch.setattr(cli, "_settings_with_single_task_mode", _raise)

    args = Namespace(
        prompt="p",
        prompt_file=None,
        text="t",
        input=None,
        label=None,
        verbose=False,
        timeout=None,
    )

    with pytest.raises(CliError):
        command_generate(args)

    assert _ShutdownTrackingRuntime.instances[0].shutdown_called is True, (
        "command_generate должен освобождать движок/прокси/настройки даже при исключении "
        "в теле команды (shutdown() должен быть в finally)"
    )


def test_command_glossary_generate_shuts_down_engine_when_body_raises(monkeypatch, tmp_path):
    from gemini_translator import cli

    monkeypatch.setattr(cli, "HeadlessRuntime", _ShutdownTrackingRuntime)
    monkeypatch.setattr(cli, "_project_manager", lambda project_folder: object())

    def _raise(*args, **kwargs):
        raise CliError("boom")

    monkeypatch.setattr(cli, "_settings_with_single_task_mode", _raise)

    args = Namespace(
        project=str(tmp_path / "project"),
        epub=str(tmp_path / "book.epub"),
        chapters="pending",
        chapter=[],
        offset=0,
        limit=None,
    )

    with pytest.raises(CliError):
        command_glossary_generate(args)

    assert _ShutdownTrackingRuntime.instances[0].shutdown_called is True, (
        "command_glossary_generate должен освобождать движок/прокси/настройки даже при "
        "исключении в теле команды (shutdown() должен быть в finally)"
    )


def test_command_untranslated_fix_shuts_down_engine_when_body_raises(monkeypatch, tmp_path):
    from gemini_translator import cli

    monkeypatch.setattr(cli, "HeadlessRuntime", _ShutdownTrackingRuntime)
    monkeypatch.setattr(cli, "_project_manager", lambda project_folder: object())

    def _raise(*args, **kwargs):
        raise CliError("boom")

    monkeypatch.setattr(cli, "_settings_with_single_task_mode", _raise)

    args = Namespace(
        project=str(tmp_path / "project"),
        epub=str(tmp_path / "book.epub"),
        chapters="pending",
        chapter=[],
        offset=0,
        limit=None,
    )

    with pytest.raises(CliError):
        command_untranslated_fix(args)

    assert _ShutdownTrackingRuntime.instances[0].shutdown_called is True, (
        "command_untranslated_fix должен освобождать движок/прокси/настройки даже при "
        "исключении в теле команды (shutdown() должен быть в finally)"
    )
