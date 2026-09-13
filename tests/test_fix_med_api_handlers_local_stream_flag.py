# tests/test_fix_med_api_handlers_local_stream_flag.py
"""
Закрепляющий тест для находки perf:network/3-local-handler-ignores-stream-f.

Было: LocalApiHandler.call_api (gemini_translator/api/handlers/local.py)
принимал параметр use_stream, но тело метода жёстко отправляло
payload["stream"] = False независимо от его значения — параметр use_stream
нигде дальше не использовался, а ответ всегда дожидался синхронным
response.json() одним блоком. При обрыве длинной локальной генерации
(Timeout/ConnectionError) весь накопленный сервером текст терялся без
partial_text.

Стало: payload["stream"] реально совпадает с переданным use_stream;
при use_stream=True requests.Session.post вызывается с stream=True и ответ
разбирается потоково через response.iter_lines() (см.
LocalApiHandler._collect_local_stream), с сохранением partial_text в
PartialGenerationError при обрыве потока (закреплено отдельно в
tests/test_fix_med_api_handlers_local_stream_partial_text.py).

xfail снят: этот тест был закладкой при статусе blocked, теперь дефект
исправлен.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from gemini_translator.api.handlers.local import LocalApiHandler


class _DummyResponse:
    status_code = 200
    text = ""

    def __init__(self, finish_reason="stop", content="ok"):
        self._finish_reason = finish_reason
        self._content = content
        self._payload = {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": content},
                }
            ]
        }

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        if self._content:
            yield "data: " + json.dumps({"choices": [{"delta": {"content": self._content}}]})
        yield "data: " + json.dumps(
            {"choices": [{"delta": {}, "finish_reason": self._finish_reason}]}
        )
        yield "data: [DONE]"


class _WorkerStub:
    def __init__(self):
        self.provider_config = {
            "base_url": "http://127.0.0.1:11434/v1/chat/completions",
            "is_async": False,
        }
        self.model_config = {
            "id": "local-model",
            "base_url": "http://127.0.0.1:11434/v1/chat/completions",
        }
        self.prompt_builder = SimpleNamespace(system_instruction=None)
        self.temperature = 0.2
        self.temperature_override_enabled = True
        self.api_key = ""
        self.model_id = ""
        self.events = []

    def _post_event(self, event, payload):
        self.events.append((event, payload))


def _make_handler():
    worker = _WorkerStub()
    handler = LocalApiHandler(worker)
    handler.setup_client(SimpleNamespace(api_key="local-key"))
    return handler, worker


def test_payload_stream_flag_matches_use_stream_argument():
    handler, _worker = _make_handler()
    captured_payloads = []
    captured_stream_kwargs = []

    def fake_post(url, headers=None, json=None, proxies=None, timeout=None, stream=None):
        captured_payloads.append(json)
        captured_stream_kwargs.append(stream)
        return _DummyResponse()

    with patch(
        "gemini_translator.api.handlers.local.requests.Session.post",
        side_effect=fake_post,
    ):
        result = handler.call_api("prompt", "log", use_stream=True)

    # payload["stream"] теперь реально совпадает с переданным use_stream,
    # и запрос к requests тоже сделан в потоковом режиме.
    assert captured_payloads[0]["stream"] is True
    assert captured_stream_kwargs[0] is True
    assert result == "ok"


def test_payload_stream_flag_false_keeps_synchronous_json_path():
    handler, _worker = _make_handler()
    captured_payloads = []
    captured_stream_kwargs = []

    def fake_post(url, headers=None, json=None, proxies=None, timeout=None, stream=None):
        captured_payloads.append(json)
        captured_stream_kwargs.append(stream)
        return _DummyResponse()

    with patch(
        "gemini_translator.api.handlers.local.requests.Session.post",
        side_effect=fake_post,
    ):
        result = handler.call_api("prompt", "log", use_stream=False)

    # Поведение use_stream=False (эталонный синхронный путь) не изменилось.
    assert captured_payloads[0]["stream"] is False
    assert captured_stream_kwargs[0] is False
    assert result == "ok"
