# tests/test_fix_med_api_handlers_local_stream_partial_text.py
"""
Закрепляющий тест для находки perf:network/3-local-handler-ignores-stream-f.

До фикса LocalApiHandler.call_api игнорировал use_stream и всегда слал
payload["stream"] = False, ожидая единый синхронный JSON-ответ. При обрыве
соединения (Timeout/ConnectionError) во время долгой локальной генерации
(таймаут по умолчанию 3300с) весь текст, уже сгенерированный сервером,
терялся -- наружу уходил голый NetworkError без partial_text.

Этот тест эмулирует реальный потоковый ответ локального OpenAI-совместимого
сервера (Ollama/LM Studio): несколько SSE-чанков с накопленным текстом, а
затем обрыв соединения (requests.exceptions.ChunkedEncodingError) до
завершения генерации. Ожидание: как и у остальных хендлеров (huggingface.py,
deepseek.py, nvidia.py, openrouter.py), обрыв потока с уже накопленным
текстом должен подниматься как PartialGenerationError с partial_text,
а не просто теряться в NetworkError.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from gemini_translator.api.errors import PartialGenerationError
from gemini_translator.api.handlers.local import LocalApiHandler


class _DummyStreamResponse:
    """Эмулирует response requests с stream=True: отдаёт SSE-строки через
    iter_lines(), затем обрывается посреди генерации."""

    status_code = 200
    text = ""

    def __init__(self, sse_lines, error_after):
        self._sse_lines = sse_lines
        self._error_after = error_after

    def iter_lines(self, decode_unicode=True):
        for line in self._sse_lines:
            yield line
        raise self._error_after

    def json(self):
        # Если код всё ещё дожидается единого JSON-ответа вместо потока --
        # это и есть дефект (use_stream=True проигнорирован).
        raise AssertionError(
            "response.json() не должен вызываться при use_stream=True -- "
            "хендлер обязан читать response.iter_lines()"
        )


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


def test_stream_interruption_preserves_partial_text():
    handler, _worker = _make_handler()

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Глава "}}]}',
        'data: {"choices": [{"delta": {"content": "первая. "}}]}',
        'data: {"choices": [{"delta": {"content": "Начало текста"}}]}',
    ]
    stream_error = requests.exceptions.ChunkedEncodingError("connection broken")
    captured_kwargs = []

    def fake_post(url, headers=None, json=None, proxies=None, timeout=None, stream=None):
        captured_kwargs.append({"json": json, "stream": stream})
        return _DummyStreamResponse(sse_lines, stream_error)

    with patch(
        "gemini_translator.api.handlers.local.requests.Session.post",
        side_effect=fake_post,
    ):
        with pytest.raises(PartialGenerationError) as caught:
            handler.call_api("prompt", "log", use_stream=True)

    # Реальный стриминг действительно запрошен у сервера.
    assert captured_kwargs[0]["json"]["stream"] is True
    assert captured_kwargs[0]["stream"] is True

    # Накопленный до обрыва текст не потерян.
    assert caught.value.partial_text == "Глава первая. Начало текста"
