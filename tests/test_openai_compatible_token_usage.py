"""The token counter shows what OpenAI-compatible providers billed, not a guess.

Their responses carry a usage object, and a stream carries it in a final chunk
with empty choices when the provider sends one. The handlers ignored it and
posted an estimate from string lengths, which never sees reasoning tokens.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gemini_translator.api.errors import PartialGenerationError
from gemini_translator.api.handlers._sse_stream import parse_openai_compatible_sse_stream
from gemini_translator.api.handlers.deepseek import DeepseekApiHandler
from gemini_translator.api.handlers.huggingface import HuggingFaceApiHandler
from gemini_translator.api.handlers.local import LocalApiHandler
from gemini_translator.api.handlers.nvidia import NvidiaApiHandler
from gemini_translator.api.handlers.openrouter import OpenRouterApiHandler


USAGE = {
    "prompt_tokens": 1200,
    "completion_tokens": 400,
    "total_tokens": 1600,
    "prompt_tokens_details": {"cached_tokens": 1024},
    "completion_tokens_details": {"reasoning_tokens": 150},
}

HANDLERS = {
    "deepseek": DeepseekApiHandler,
    "huggingface": HuggingFaceApiHandler,
    "nvidia": NvidiaApiHandler,
    "openrouter": OpenRouterApiHandler,
}


def _full_body(usage):
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1757836800,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "перевод"},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _stream_lines(usage):
    lines = [
        'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":'
        '[{"index":0,"delta":{"role":"assistant","content":"пере"},"finish_reason":null}]}',
        'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":'
        '[{"index":0,"delta":{"content":"вод"},"finish_reason":"stop"}]}',
    ]
    if usage is not None:
        chunk = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": [], "usage": usage}
        lines.append("data: " + json.dumps(chunk))
    lines.append("data: [DONE]")
    return lines


class _Response:
    """aiohttp response of a cloud OpenAI-compatible API."""

    def __init__(self, *, json_body=None, stream_lines=()):
        self.status = 200
        self.headers = {}
        self._json = json_body
        self._lines = list(stream_lines)

    async def json(self, content_type=None):
        return self._json

    async def text(self):
        return json.dumps(self._json)

    @property
    def content(self):
        async def lines():
            for line in self._lines:
                yield line.encode("utf-8")

        return lines()


class _Ctx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)

    def post(self, *args, **kwargs):
        return _Ctx(self._responses.pop(0))


def _handler(name, responses):
    events = []
    model_id = f"{name}-model"
    worker = SimpleNamespace(
        provider_config={"is_async": True, "base_timeout": 600},
        model_config={"id": model_id, "provider": name},
        prompt_builder=SimpleNamespace(system_instruction="sys"),
        temperature=0.7,
        temperature_override_enabled=False,
        thinking_enabled=False,
        thinking_level=None,
        api_key="secret",
        model_id=model_id,
        is_cancelled=False,
        _post_event=lambda event, payload: events.append((event, payload)),
        settings_manager=SimpleNamespace(
            increment_request_count=lambda *args, **kwargs: None,
            decrement_request_count=lambda *args, **kwargs: None,
        ),
    )
    handler = HANDLERS[name](worker)
    handler.base_url = "https://example.invalid/v1/chat/completions"
    handler.is_dynamic_local = False
    handler._reset_model_id_to_primary = lambda: None
    handler._force_session_reset = lambda *args, **kwargs: None
    session = _Session(responses)

    async def get_session():
        return session

    handler._get_or_create_session_internal = get_session
    return handler, events


def _posted_usage(name, responses, *, use_stream):
    handler, events = _handler(name, responses)
    for _ in responses:
        asyncio.run(handler.execute_api_call("SOURCE", "[TEST]", use_stream=use_stream))
    return [payload for event, payload in events if event == "token_usage_updated"]


class _LocalResponse:
    """requests response of a local OpenAI-compatible server."""

    status_code = 200
    text = ""

    def __init__(self, *, body=None, lines=()):
        self._body = body
        self._lines = list(lines)

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=True):
        yield from self._lines

    def close(self):
        pass


def _local_published_usages(response, *, use_stream, allow_incomplete=False, raises=None):
    events = []
    base_url = "http://127.0.0.1:11434/v1/chat/completions"
    worker = SimpleNamespace(
        provider_config={"base_url": base_url, "is_async": False},
        model_config={"id": "local-model", "base_url": base_url},
        prompt_builder=SimpleNamespace(system_instruction=None),
        temperature=0.2,
        temperature_override_enabled=True,
        api_key="",
        model_id="",
        is_cancelled=False,
        settings_manager=SimpleNamespace(
            increment_request_count=lambda *args, **kwargs: None,
            decrement_request_count=lambda *args, **kwargs: None,
        ),
        _post_event=lambda event, payload: events.append((event, payload)),
    )
    handler = LocalApiHandler(worker)
    handler.setup_client(SimpleNamespace(api_key="local-key"))
    # The local handler is synchronous: execute_api_call runs it in a worker
    # thread, and the usage it reads there must reach this call's event.
    with patch("gemini_translator.api.handlers.local.requests.Session.post", return_value=response):
        call = handler.execute_api_call(
            "SOURCE", "[TEST]", allow_incomplete=allow_incomplete, use_stream=use_stream
        )
        if raises is None:
            asyncio.run(call)
        else:
            with pytest.raises(raises):
                asyncio.run(call)
    return [payload for event, payload in events if event == "token_usage_updated"]


def _local_posted_usage(response, *, use_stream):
    return _local_published_usages(response, use_stream=use_stream)[-1]


def test_sse_stream_passes_the_usage_of_its_final_chunk_to_on_usage():
    seen = []

    text, finish_reason, _ = asyncio.run(
        parse_openai_compatible_sse_stream(
            _Response(stream_lines=_stream_lines(USAGE)), on_usage=seen.append
        )
    )

    assert (text, finish_reason) == ("перевод", "stop")
    assert seen == [USAGE]


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_full_response_reports_the_billed_tokens(name):
    usage = _posted_usage(name, [_Response(json_body=_full_body(USAGE))], use_stream=False)[-1]

    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (1200, 400, 1600)
    assert usage["cached_tokens"] == 1024
    assert usage["thinking_tokens"] == 150
    assert usage["estimated"] is False


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_stream_reports_the_billed_tokens_of_its_final_chunk(name):
    usage = _posted_usage(name, [_Response(stream_lines=_stream_lines(USAGE))], use_stream=True)[-1]

    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (1200, 400, 1600)
    assert usage["thinking_tokens"] == 150
    assert usage["estimated"] is False


def test_deepseek_prompt_cache_hits_count_as_cached_tokens():
    deepseek_usage = {
        "prompt_tokens": 1200,
        "completion_tokens": 400,
        "total_tokens": 1600,
        "prompt_cache_hit_tokens": 1024,
        "prompt_cache_miss_tokens": 176,
    }

    usage = _posted_usage(
        "deepseek", [_Response(json_body=_full_body(deepseek_usage))], use_stream=False
    )[-1]

    assert usage["cached_tokens"] == 1024
    # No completion_tokens_details: the provider did not say how much of the output was reasoning.
    assert "thinking_tokens" not in usage


def test_request_without_usage_is_estimated_instead_of_repeating_the_previous_one():
    usages = _posted_usage(
        "openrouter",
        [_Response(json_body=_full_body(USAGE)), _Response(json_body=_full_body(None))],
        use_stream=False,
    )

    assert [usage["estimated"] for usage in usages] == [False, True]


def test_local_server_full_response_reports_the_billed_tokens():
    usage = _local_posted_usage(_LocalResponse(body=_full_body(USAGE)), use_stream=False)

    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (1200, 400, 1600)
    assert usage["thinking_tokens"] == 150
    assert usage["estimated"] is False


def test_local_server_stream_reports_the_billed_tokens_of_its_final_chunk():
    usage = _local_posted_usage(_LocalResponse(lines=_stream_lines(USAGE)), use_stream=True)

    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (1200, 400, 1600)
    assert usage["estimated"] is False


def test_local_server_ignoring_the_stream_flag_still_reports_the_billed_tokens():
    usage = _local_posted_usage(
        _LocalResponse(lines=[json.dumps(_full_body(USAGE))]), use_stream=True
    )

    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (1200, 400, 1600)
    assert usage["estimated"] is False


@pytest.mark.parametrize("name", ["deepseek", "huggingface"])
def test_full_response_cut_by_the_length_limit_still_publishes_the_billed_tokens(name):
    body = _full_body(USAGE)
    body["choices"][0]["finish_reason"] = "length"
    handler, events = _handler(name, [_Response(json_body=body)])

    with pytest.raises(PartialGenerationError):
        asyncio.run(handler.execute_api_call("SOURCE", "[TEST]", use_stream=False))

    [usage] = [payload for event, payload in events if event == "token_usage_updated"]
    assert (usage["input_tokens"], usage["output_tokens"], usage["estimated"]) == (1200, 400, False)


def test_local_server_answer_cut_by_the_length_limit_still_publishes_the_billed_tokens():
    body = _full_body(USAGE)
    body["choices"][0]["finish_reason"] = "length"

    usages = _local_published_usages(
        _LocalResponse(body=body), use_stream=False, allow_incomplete=True, raises=PartialGenerationError
    )

    assert [(usage["input_tokens"], usage["output_tokens"], usage["estimated"]) for usage in usages] == [
        (1200, 400, False)
    ]
