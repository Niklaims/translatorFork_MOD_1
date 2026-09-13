# tests/test_fix_med_api_handlers_local_stream_flag.py
"""
Закрепляющий тест для находки perf:network/3-local-handler-ignores-stream-f.

LocalApiHandler.call_api (gemini_translator/api/handlers/local.py) принимает
параметр use_stream, но тело метода жёстко отправляет payload["stream"] = False
независимо от его значения — параметр use_stream нигде дальше не используется.

Настоящий фикс (потоковое чтение SSE-чанков от локального сервера с накоплением
partial_text для PartialGenerationError при обрыве) требует, чтобы
requests.Session.post вызывался с stream=True и разбирал response.iter_lines().
Все шесть моков fake_post в tests/test_local_api_handler.py объявлены как
(url, headers=None, json=None, proxies=None, timeout=None) и возвращают
_DummyResponse без iter_lines()/content — они не эмулируют потоковый ответ.
Правка этого файла запрещена в рамках данной находки (группа api_handlers_local
может менять только local.py и новые tests/test_fix_med_api_handlers_local_*.py),
поэтому находка помечена blocked, а не закрыта.

Тест документирует именно этот дефект и помечен xfail(strict=False): он не
валит сборку сейчас, но автоматически станет зелёным (и тогда xfail будет
нужно снять), когда payload["stream"] начнёт реально совпадать с переданным
use_stream.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gemini_translator.api.handlers.local import LocalApiHandler


class _DummyResponse:
    status_code = 200
    text = ""

    def __init__(self, finish_reason="stop", content="ok"):
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


@pytest.mark.xfail(
    reason=(
        "blocked: реальный фикс требует потокового response.iter_lines() и "
        "совместной правки tests/test_local_api_handler.py (её fake_post не "
        "эмулирует stream=True) — правка этого файла вне разрешённой области "
        "находки perf:network/3-local-handler-ignores-stream-f"
    ),
    strict=False,
)
def test_payload_stream_flag_matches_use_stream_argument():
    handler, _worker = _make_handler()
    captured_payloads = []

    def fake_post(url, headers=None, json=None, proxies=None, timeout=None):
        captured_payloads.append(json)
        return _DummyResponse()

    with patch(
        "gemini_translator.api.handlers.local.requests.Session.post",
        side_effect=fake_post,
    ):
        handler.call_api("prompt", "log", use_stream=True)

    # Сейчас payload["stream"] всегда False независимо от use_stream —
    # это и есть дефект perf:network/3-local-handler-ignores-stream-f.
    assert captured_payloads[0]["stream"] is True
