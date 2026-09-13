# tests/test_fix_med_api_handlers_local_stream_response_close.py
"""
Закрепляющие тесты для ревью-замечания (major, local.py:143) к находке
perf:network/3-local-handler-ignores-stream-f.

До этой правки потоковый response ни разу не закрывался -- ни при успешном
разборе, ни при обрыве -- а requests.Session при stream=True не возвращает
соединение в пул, пока тело не дочитано или response не закрыт явно. Хуже
того, при обрыве соединения внутри iter_lines персистентная сессия с
недочитанным телом продолжала жить и переиспользоваться следующим вызовом,
хотя раньше (до появления настоящего стриминга) обрыв соединения обязательно
проходил через _drop_http_session() (см. except requests.exceptions.Timeout /
ConnectionError в call_api).

Ожидание:
1. response.close() вызывается на потоковом пути как при успехе, так и при
   обрыве (через finally).
2. При обрыве потока (PartialGenerationError из _collect_local_stream)
   персистентная HTTP-сессия сбрасывается тем же способом, что и при
   обрыве вне стрима -- self._drop_http_session().
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from gemini_translator.api.errors import PartialGenerationError
from gemini_translator.api.handlers.local import LocalApiHandler


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


class _ClosableStreamResponse:
    """Отслеживает, сколько раз был вызван close(), как настоящий
    requests.Response при stream=True."""

    status_code = 200
    text = ""

    def __init__(self, lines, error_after=None):
        self._lines = lines
        self._error_after = error_after
        self.close_calls = 0

    def iter_lines(self, decode_unicode=True):
        yield from self._lines
        if self._error_after is not None:
            raise self._error_after

    def close(self):
        self.close_calls += 1

    def json(self):
        raise AssertionError("response.json() не должен вызываться при use_stream=True")


def test_stream_response_is_closed_after_successful_read():
    handler, _worker = _make_handler()
    response = _ClosableStreamResponse(
        [
            'data: {"choices": [{"delta": {"content": "Готовый перевод"}}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ]
    )

    def fake_post(url, headers=None, json=None, proxies=None, timeout=None, stream=None):
        return response

    with patch(
        "gemini_translator.api.handlers.local.requests.Session.post",
        side_effect=fake_post,
    ):
        result = handler.call_api("prompt", "log", use_stream=True)

    assert result == "Готовый перевод"
    assert response.close_calls == 1


def test_stream_response_closed_and_session_dropped_on_interruption():
    handler, _worker = _make_handler()
    stream_error = requests.exceptions.ChunkedEncodingError("connection broken")
    response = _ClosableStreamResponse(
        ['data: {"choices": [{"delta": {"content": "Часть текста"}}]}'],
        error_after=stream_error,
    )

    def fake_post(url, headers=None, json=None, proxies=None, timeout=None, stream=None):
        return response

    with patch(
        "gemini_translator.api.handlers.local.requests.Session.post",
        side_effect=fake_post,
    ):
        # Прогреваем персистентную сессию -- она должна существовать ДО обрыва.
        session_before = handler._get_http_session()
        assert handler._http_session is session_before

        with pytest.raises(PartialGenerationError):
            handler.call_api("prompt", "log", use_stream=True)

    # Response обязательно закрыт даже при обрыве потока.
    assert response.close_calls == 1
    # Персистентная сессия сброшена -- как и при обрыве вне стрима
    # (requests.exceptions.Timeout/ConnectionError в call_api).
    assert handler._http_session is None
