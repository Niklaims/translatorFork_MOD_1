"""Every call counts its own tokens, even when calls share one handler.

A worker runs up to max_concurrent_requests calls through one API handler at
once. When the usage of a call lived in a handler field, a neighbouring call
overwrote it or wiped it, and a failed attempt published nothing although the
provider had billed it.
"""

import asyncio
import contextvars
import threading
from types import SimpleNamespace

import aiohttp
import pytest

from gemini_translator.api import token_usage
from gemini_translator.api.base import BaseApiHandler
from gemini_translator.api.errors import ContentFilterError


def test_remember_outside_an_attempt_keeps_nothing():
    token_usage.remember(10, 2)

    assert token_usage.reported() is None


def test_the_latest_report_of_an_attempt_wins():
    token = token_usage.begin_attempt()
    try:
        token_usage.remember(1200, 0)
        token_usage.remember(1200, 340, cached_tokens=1024, thinking_tokens=60, total_tokens=1600)
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported == {
        "input_tokens": 1200,
        "output_tokens": 340,
        "total_tokens": 1600,
        "cached_tokens": 1024,
        "thinking_tokens": 60,
    }
    assert token_usage.reported() is None


def test_optional_counts_are_left_out_and_the_total_is_summed():
    token = token_usage.begin_attempt()
    try:
        token_usage.remember(100, 20)
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def test_a_new_attempt_starts_empty_and_the_outer_one_comes_back():
    outer = token_usage.begin_attempt()
    try:
        token_usage.remember(1, 1)
        inner = token_usage.begin_attempt()
        try:
            assert token_usage.reported() is None
            token_usage.remember(2, 2)
        finally:
            token_usage.end_attempt(inner)
        assert token_usage.reported()["input_tokens"] == 1
    finally:
        token_usage.end_attempt(outer)


def test_reported_hands_out_a_copy():
    token = token_usage.begin_attempt()
    try:
        token_usage.remember(5, 5)
        token_usage.reported()["input_tokens"] = 999
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported["input_tokens"] == 5


def test_a_task_started_inside_the_attempt_reports_into_it():
    async def scenario():
        token = token_usage.begin_attempt()
        try:
            async def provider_call():
                token_usage.remember(30, 3)

            await asyncio.create_task(provider_call())
            return token_usage.reported()
        finally:
            token_usage.end_attempt(token)

    assert asyncio.run(scenario())["input_tokens"] == 30


def test_a_thread_running_in_a_copy_of_the_context_reports_into_the_attempt():
    token = token_usage.begin_attempt()
    try:
        context = contextvars.copy_context()
        thread = threading.Thread(target=context.run, args=(token_usage.remember, 40, 4))
        thread.start()
        thread.join()
        reported = token_usage.reported()
    finally:
        token_usage.end_attempt(token)

    assert reported["input_tokens"] == 40


def test_publish_hands_the_usage_to_a_poster_and_tolerates_none():
    events = []

    token_usage.publish_token_usage({"input_tokens": 1}, lambda name, payload: events.append((name, payload)))
    token_usage.publish_token_usage({"input_tokens": 2})
    token_usage.publish_token_usage({"input_tokens": 3}, poster="not callable")

    assert events == [("token_usage_updated", {"input_tokens": 1})]


def _worker(*, is_async=True, model_config=None, provider_config=None):
    events = []
    worker = SimpleNamespace(
        provider_config={
            "is_async": is_async,
            "transient_disconnect_retry_delay_seconds": 0,
            **(provider_config or {}),
        },
        model_config={"id": "test-model", "provider": "test-provider"} if model_config is None else model_config,
        api_key="test-key",
        model_id="test-model",
        is_cancelled=False,
        settings_manager=SimpleNamespace(
            increment_request_count=lambda *args, **kwargs: None,
            decrement_request_count=lambda *args, **kwargs: None,
        ),
        _post_event=lambda name, payload: events.append((name, payload)),
    )
    return worker, events


def _published(events):
    return [payload for name, payload in events if name == "token_usage_updated"]


def _counts(usage):
    return usage["input_tokens"], usage["output_tokens"], usage["estimated"]


class _ScriptedAsyncHandler(BaseApiHandler):
    """call_api plays the coroutine the test wrote for its prompt."""

    def __init__(self, worker, script):
        super().__init__(worker)
        self._script = script

    async def call_api(self, prompt, log_prefix, allow_incomplete=False, use_stream=True, debug=False, max_output_tokens=None):
        return await self._script[prompt](self)


class _ScriptedSyncHandler(BaseApiHandler):
    """A synchronous handler: execute_api_call runs call_api in a worker thread."""

    def __init__(self, worker, script):
        super().__init__(worker)
        self._script = script

    def call_api(self, prompt, log_prefix, allow_incomplete=False, use_stream=True, debug=False, max_output_tokens=None):
        return self._script[prompt](self)


def test_parallel_calls_through_one_handler_publish_their_own_usage():
    worker, events = _worker()

    async def scenario():
        first_reported = asyncio.Event()
        second_reported = asyncio.Event()

        async def first(handler):
            handler._remember_token_usage(100, 10)
            first_reported.set()
            await second_reported.wait()
            return "first answer"

        async def second(handler):
            await first_reported.wait()
            handler._remember_token_usage(2000, 200)
            second_reported.set()
            return "second answer"

        handler = _ScriptedAsyncHandler(worker, {"first": first, "second": second})
        await asyncio.gather(
            handler.execute_api_call("first", "[TEST]"),
            handler.execute_api_call("second", "[TEST]"),
        )

    asyncio.run(scenario())

    assert sorted(_counts(usage) for usage in _published(events)) == [(100, 10, False), (2000, 200, False)]


def test_a_call_starting_next_to_another_does_not_wipe_its_usage():
    worker, events = _worker()

    async def scenario():
        first_reported = asyncio.Event()
        second_answered = asyncio.Event()

        async def first(handler):
            handler._remember_token_usage(100, 10)
            first_reported.set()
            await second_answered.wait()
            return "first answer"

        async def second(handler):
            # This provider reports no usage at all.
            second_answered.set()
            return "second answer"

        handler = _ScriptedAsyncHandler(worker, {"first": first, "second": second})
        first_call = asyncio.create_task(handler.execute_api_call("first", "[TEST]"))
        await first_reported.wait()
        await handler.execute_api_call("second", "[TEST]")
        await first_call

    asyncio.run(scenario())

    usages = _published(events)
    assert len(usages) == 2
    assert [_counts(usage) for usage in usages if not usage["estimated"]] == [(100, 10, False)]


def test_sync_handler_threads_fill_the_tally_of_their_own_call():
    worker, events = _worker(is_async=False)
    both_reported = threading.Barrier(2, timeout=5)

    def first(handler):
        handler._remember_token_usage(300, 30)
        both_reported.wait()
        return "first answer"

    def second(handler):
        handler._remember_token_usage(4000, 400)
        both_reported.wait()
        return "second answer"

    handler = _ScriptedSyncHandler(worker, {"first": first, "second": second})

    async def scenario():
        await asyncio.gather(
            handler.execute_api_call("first", "[TEST]"),
            handler.execute_api_call("second", "[TEST]"),
        )

    asyncio.run(scenario())

    assert sorted(_counts(usage) for usage in _published(events)) == [(300, 30, False), (4000, 400, False)]


def test_a_failed_attempt_publishes_what_the_provider_billed():
    worker, events = _worker()

    async def blocked(handler):
        handler._remember_token_usage(500, 0)
        raise ContentFilterError("Блокировка на уровне промпта: SAFETY")

    handler = _ScriptedAsyncHandler(worker, {"blocked": blocked})

    with pytest.raises(ContentFilterError):
        asyncio.run(handler.execute_api_call("blocked", "[TEST]"))

    [usage] = _published(events)
    assert _counts(usage) == (500, 0, False)
    assert (usage["provider"], usage["model_id"]) == ("test-provider", "test-model")


def test_a_failed_attempt_without_a_report_publishes_nothing():
    worker, events = _worker()

    async def blocked(handler):
        raise ContentFilterError("Блокировка на уровне промпта: SAFETY")

    handler = _ScriptedAsyncHandler(worker, {"blocked": blocked})

    with pytest.raises(ContentFilterError):
        asyncio.run(handler.execute_api_call("blocked", "[TEST]"))

    assert _published(events) == []


def test_a_retried_attempt_publishes_its_own_usage_after_the_failed_one():
    worker, events = _worker()
    attempts = []

    async def flaky(handler):
        attempts.append("attempt")
        if len(attempts) == 1:
            handler._remember_token_usage(600, 60)
            raise aiohttp.ServerDisconnectedError()
        return "answer"

    handler = _ScriptedAsyncHandler(worker, {"flaky": flaky})

    assert asyncio.run(handler.execute_api_call("flaky", "[TEST]")) == "answer"

    usages = _published(events)
    assert len(attempts) == 2
    assert len(usages) == 2
    assert _counts(usages[0]) == (600, 60, False)
    assert usages[1]["estimated"] is True


def test_usage_goes_out_through_the_module_function_the_bridge_replaces(monkeypatch):
    worker, events = _worker()
    published = []
    monkeypatch.setattr(
        token_usage, "publish_token_usage", lambda usage, poster=None: published.append((usage, poster))
    )

    async def answer(handler):
        handler._remember_token_usage(700, 70)
        return "answer"

    handler = _ScriptedAsyncHandler(worker, {"answer": answer})
    asyncio.run(handler.execute_api_call("answer", "[TEST]"))

    [(usage, poster)] = published
    assert _counts(usage) == (700, 70, False)
    assert poster is worker._post_event
    assert events == []


def test_provider_comes_from_the_provider_config_when_the_model_config_has_none():
    worker, events = _worker(
        model_config={"id": "DeepSeek-V4-Flash-0731"},
        provider_config={"provider": "seekai"},
    )

    async def answer(handler):
        return "answer"

    handler = _ScriptedAsyncHandler(worker, {"answer": answer})
    asyncio.run(handler.execute_api_call("answer", "[TEST]"))

    [usage] = _published(events)
    assert usage["provider"] == "seekai"


def test_translation_usage_carries_no_operation_mark():
    """Only QA marks its usage; the reader counts everything else by the command it ran."""
    worker, events = _worker()

    async def answer(handler):
        handler._remember_token_usage(100, 10)
        return "answer"

    handler = _ScriptedAsyncHandler(worker, {"answer": answer})
    asyncio.run(handler.execute_api_call("answer", "[TEST]"))

    [usage] = _published(events)
    assert "operation" not in usage


def test_a_failing_poster_does_not_fail_the_call():
    worker, _events = _worker()

    def broken_poster(name, payload):
        raise RuntimeError("status bar is gone")

    worker._post_event = broken_poster

    async def answer(handler):
        handler._remember_token_usage(800, 80)
        return "answer"

    handler = _ScriptedAsyncHandler(worker, {"answer": answer})

    assert asyncio.run(handler.execute_api_call("answer", "[TEST]")) == "answer"
