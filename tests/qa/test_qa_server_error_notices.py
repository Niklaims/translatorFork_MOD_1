"""A check that keeps failing on the server says so in the log, and not every twenty seconds."""

from __future__ import annotations

import asyncio

import pytest

from gemini_translator.api.errors import NetworkError, TemporaryRateLimitError
from gemini_translator.qa.handler_factory import (
    SERVER_ERROR_REPEAT_SECONDS,
    QaHandlerError,
    RotatingQaHandler,
    ServerErrorNotices,
    build_qa_handler_factory,
)
from gemini_translator.qa.key_pool import QaKeyPool
from gemini_translator.qa.llm.completion import QaModelSelection

OVERLOADED = "Сервер Gemini перегружен (503)."


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Handler:
    """Answers with what the test queued: an error to raise or a text to return."""

    def __init__(self, answers: list) -> None:
        self._answers = answers

    async def execute_api_call(self, *args, **kwargs):
        answer = self._answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _handler(answers, clock, lines, notices, model="gemini-3.8-flash"):
    return RotatingQaHandler(
        QaKeyPool(["fake-key"], clock=clock),
        lambda key: _Handler(answers),
        log=lines.append,
        sleep=clock.sleep,
        notices=notices,
        model_name=model,
    )


def _ask(handler):
    return asyncio.run(handler.execute_api_call("prompt", "[QA]"))


def _overloaded():
    return NetworkError(OVERLOADED, delay_seconds=20)


def test_a_failing_server_is_named_with_the_model_and_where_to_change_it():
    clock, lines = Clock(), []
    notices = ServerErrorNotices(clock=clock)
    error = _overloaded()

    with pytest.raises(NetworkError) as raised:
        _ask(_handler([error], clock, lines, notices))

    # The retry loop above still decides what to do with the very same error.
    assert raised.value is error
    assert len(lines) == 1
    assert "Сервер отвечает ошибкой" in lines[0]
    assert OVERLOADED in lines[0]
    assert "gemini-3.8-flash" in lines[0]
    assert "«Модель проверки»" in lines[0]


def test_the_same_failure_is_repeated_only_after_five_minutes():
    """503 приходит каждые 20 с часами: строка на каждый вытеснила бы главы из журнала."""
    clock, lines = Clock(), []
    notices = ServerErrorNotices(clock=clock)

    for _ in range(3):
        with pytest.raises(NetworkError):
            _ask(_handler([_overloaded()], clock, lines, notices))
        clock.now += 20
    assert len(lines) == 1

    clock.now = 1000.0 + SERVER_ERROR_REPEAT_SECONDS
    with pytest.raises(NetworkError):
        _ask(_handler([_overloaded()], clock, lines, notices))

    assert len(lines) == 2
    assert "всё ещё" in lines[1]
    assert "Неудачных попыток подряд: 4" in lines[1]


def test_a_different_failure_is_named_at_once():
    clock, lines = Clock(), []
    notices = ServerErrorNotices(clock=clock)

    with pytest.raises(NetworkError):
        _ask(_handler([_overloaded()], clock, lines, notices))
    with pytest.raises(NetworkError):
        _ask(
            _handler(
                [NetworkError("Ошибка сервера (500): internal", delay_seconds=25)],
                clock,
                lines,
                notices,
            )
        )

    assert len(lines) == 2
    assert "Ошибка сервера (500)" in lines[1]


def test_the_first_answer_after_failures_says_the_server_is_back():
    clock, lines = Clock(), []
    notices = ServerErrorNotices(clock=clock)

    with pytest.raises(NetworkError):
        _ask(_handler([_overloaded()], clock, lines, notices))
    assert _ask(_handler(["ok"], clock, lines, notices, model="gemini-3.5-flash")) == "ok"
    assert _ask(_handler(["ok"], clock, lines, notices, model="gemini-3.5-flash")) == "ok"

    assert len(lines) == 2
    assert "Сервер снова отвечает" in lines[1]
    assert "gemini-3.5-flash" in lines[1]


def test_keys_resting_longer_than_one_request_waits_are_named_too():
    """Так 14.09 два окна полчаса стояли на первой главе без единой строки."""
    clock, lines = Clock(), []
    notices = ServerErrorNotices(clock=clock)
    rested = TemporaryRateLimitError("Временный лимит запросов (429).", delay_seconds=3600)
    handler = RotatingQaHandler(
        QaKeyPool(["fake-key"], clock=clock),
        lambda key: _Handler([rested]),
        log=lines.append,
        sleep=clock.sleep,
        max_wait_seconds=120,
        notices=notices,
        model_name="gemini-3.8-flash",
    )

    with pytest.raises(QaHandlerError):
        _ask(handler)

    notice = [line for line in lines if "на паузе" in line]
    assert len(notice) == 1
    assert "gemini-3.8-flash" in notice[0]
    assert "«Модель проверки»" in notice[0]


def test_a_failure_that_is_not_the_servers_trouble_adds_nothing():
    clock, lines = Clock(), []
    notices = ServerErrorNotices(clock=clock)

    with pytest.raises(ValueError):
        _ask(_handler([ValueError("bad prompt")], clock, lines, notices))

    assert lines == []


def test_the_requests_of_one_check_share_what_was_already_said(monkeypatch):
    """Каждый запрос строит свой обработчик; повтор той же ошибки всё равно не пишется."""
    import gemini_translator.api.config as api_config
    import gemini_translator.api.factory as api_factory

    class _Overloaded:
        def __init__(self, worker) -> None:
            self.worker = worker

        def setup_client(self, holder, proxy_settings=None):
            return True

        async def execute_api_call(self, *args, **kwargs):
            raise _overloaded()

    monkeypatch.setattr(
        api_config,
        "api_providers_view",
        lambda: {
            "gemini": {
                "handler_class": "Overloaded",
                "models": {"Gemini 3.8 Flash": {"id": "gemini-3.8-flash"}},
            }
        },
    )
    monkeypatch.setattr(api_factory, "get_api_handler_class", lambda name: _Overloaded)
    lines: list[str] = []
    factory = build_qa_handler_factory(
        settings_manager=None, key_pool=QaKeyPool(["fake-key"]), log=lines.append
    )
    model = QaModelSelection("gemini", "gemini-3.8-flash")

    for _ in range(2):
        with pytest.raises(NetworkError):
            asyncio.run(factory(model).execute_api_call("prompt", "[QA]"))

    assert len([line for line in lines if "Сервер отвечает ошибкой" in line]) == 1
