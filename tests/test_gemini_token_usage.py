"""The token counter shows what Gemini billed, not a guess from string lengths.

Gemini reports usageMetadata in every response and in stream chunks; the
handler used to ignore it and post an estimate for every request.
"""

import asyncio
import json
from types import SimpleNamespace

from gemini_translator.api.handlers.gemini import GeminiApiHandler


class _StreamContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class _Response:
    def __init__(self, *, body=b"", chunks=()):
        self.status = 200
        self._body = body
        self.content = _StreamContent(list(chunks))

    async def read(self):
        return self._body

    async def text(self):
        return self._body.decode("utf-8")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _Session:
    def __init__(self, response):
        self._response = response

    def post(self, url, headers=None, json=None):
        return self._response


def _handler_answering(response):
    events = []
    worker = SimpleNamespace(
        provider_config={"is_async": True},
        model_config={"id": "gemini-test", "provider": "gemini", "min_thinking_budget": False},
        api_key="test-key",
        model_id="gemini-test",
        is_cancelled=False,
        settings_manager=SimpleNamespace(increment_request_count=lambda *args, **kwargs: None),
        prompt_builder=SimpleNamespace(system_instruction=None),
        temperature_override_enabled=False,
        temperature=None,
        _post_event=lambda name, payload: events.append((name, payload)),
    )
    handler = GeminiApiHandler(worker)
    handler.setup_client(SimpleNamespace(api_key="test-key"))

    async def session():
        return _Session(response)

    handler._get_or_create_session_internal = session
    return handler, events


def _posted_usage(handler, events, prompt, *, use_stream):
    asyncio.run(handler.execute_api_call(prompt, "[TEST]", use_stream=use_stream))
    return [payload for name, payload in events if name == "token_usage_updated"][-1]


def test_full_response_reports_billed_tokens_with_thinking_counted_as_output():
    body = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "перевод"}]}, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": 1200,
            "candidatesTokenCount": 340,
            "thoughtsTokenCount": 60,
            "totalTokenCount": 1600,
            "cachedContentTokenCount": 1024,
        },
    }).encode("utf-8")
    handler, events = _handler_answering(_Response(body=body))

    usage = _posted_usage(handler, events, "SOURCE", use_stream=False)

    assert usage["input_tokens"] == 1200
    assert usage["output_tokens"] == 400
    assert usage["total_tokens"] == 1600
    assert usage["cached_tokens"] == 1024
    assert usage["estimated"] is False


def test_stream_reports_the_usage_of_its_last_chunk():
    first = {"candidates": [{"content": {"parts": [{"text": "пере"}]}}],
             "usageMetadata": {"promptTokenCount": 1200, "totalTokenCount": 1200}}
    last = {"candidates": [{"content": {"parts": [{"text": "вод"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 340, "totalTokenCount": 1540}}
    chunks = ["[" + json.dumps(first), "," + json.dumps(last) + "]"]
    handler, events = _handler_answering(_Response(chunks=[chunk.encode("utf-8") for chunk in chunks]))

    usage = _posted_usage(handler, events, "SOURCE", use_stream=True)

    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (1200, 340, 1540)
    assert usage["estimated"] is False


def test_response_without_usage_falls_back_to_the_estimate_instead_of_an_older_request():
    with_usage = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "перевод"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 340, "totalTokenCount": 1540},
    }).encode("utf-8")
    without_usage = json.dumps({
        "candidates": [{"content": {"parts": [{"text": "перевод"}]}, "finishReason": "STOP"}],
    }).encode("utf-8")
    handler, events = _handler_answering(_Response(body=with_usage))
    _posted_usage(handler, events, "SOURCE", use_stream=False)

    handler._get_or_create_session_internal = lambda: _async_value(_Session(_Response(body=without_usage)))
    usage = _posted_usage(handler, events, "SOURCE", use_stream=False)

    assert usage["estimated"] is True


async def _async_value(value):
    return value
