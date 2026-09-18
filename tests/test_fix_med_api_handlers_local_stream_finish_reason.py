# tests/test_fix_med_api_handlers_local_stream_finish_reason.py
"""
Закрепляющие тесты для ревью-замечаний к находке
perf:network/3-local-handler-ignores-stream-f (файл local.py).

Рецензент (major, local.py:262): потоковая ветка LocalApiHandler.call_api
после первого фикса требовала finish_reason == "stop", иначе выбрасывала
ValidationFailedError и теряла весь уже собранный текст -- даже если сервер
успешно отдал полный перевод, но не прислал (или прислал не "stop")
финальный finish_reason. Ни один другой хендлер (см. deepseek.py) такого
требования в стриме не предъявляет: там непустой collected_text просто
возвращается, особый случай только finish_reason == "length".

Второй сценарий того же замечания: локальный сервер может проигнорировать
"stream": true в запросе и ответить одним обычным JSON-телом (не SSE).
Раньше это тоже приводило к потере текста (ни одна строка не начиналась с
"data: ", collected_text оставался пустым). Ожидание: хендлер обязан
распознать такой ответ и разобрать его как обычный синхронный JSON вместо
того, чтобы терять текст.

Минорное замечание (local.py:227): has_content выставлялся в потоке
безусловно, поэтому ветка "пустой потоковый ответ" была недостижима.
Проверяем, что она стала достижимой и дает осмысленное сообщение, когда
поток действительно пуст (ни одного choices-чанка, saw_sse=False).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gemini_translator.api.errors import PartialGenerationError, ValidationFailedError
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


class _LinesResponse:
    """Отдаёт заранее заданные строки через iter_lines(), без обрыва."""

    status_code = 200
    text = ""

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self, decode_unicode=True):
        yield from self._lines

    def json(self):
        raise AssertionError("response.json() не должен вызываться при use_stream=True")


def _post_with(handler, response_lines_factory):
    def fake_post(url, headers=None, json=None, proxies=None, timeout=None, stream=None):
        return _LinesResponse(response_lines_factory())

    return patch(
        "gemini_translator.api.handlers.local.requests.Session.post",
        side_effect=fake_post,
    )


def test_stream_without_stop_finish_reason_still_returns_full_text():
    """Сервер отдал полный текст, но финальный чанк вообще не пришёл --
    ни один локальный сервер не обязан слать явный finish_reason:'stop',
    и требовать этого от потока не должен ни один хендлер (см. deepseek.py,
    где особый случай в стриме -- только 'length')."""
    handler, _worker = _make_handler()
    lines = [
        'data: {"choices": [{"delta": {"content": "Полный перевод главы"}}]}',
        "data: [DONE]",
    ]

    with _post_with(handler, lambda: lines):
        result = handler.call_api("prompt", "log", use_stream=True)

    assert result == "Полный перевод главы"


def test_stream_with_non_stop_non_length_finish_reason_returns_text():
    """finish_reason, отличный от 'stop' и 'length' (например 'tool_calls'
    или любой другой, не являющийся в OpenAI-совместимом API признаком
    обрезки) не должен приводить к потере текста в потоке."""
    handler, _worker = _make_handler()
    lines = [
        'data: {"choices": [{"delta": {"content": "Текст главы"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "content_filter"}]}',
        "data: [DONE]",
    ]

    with _post_with(handler, lambda: lines):
        result = handler.call_api("prompt", "log", use_stream=True)

    assert result == "Текст главы"


def test_stream_length_without_allow_incomplete_behavior_unchanged_shape():
    """length + allow_incomplete (как и раньше) -- единственный особый
    случай в потоке, приводящий к PartialGenerationError с сохранённым
    partial_text."""
    handler, worker = _make_handler()
    lines = [
        'data: {"choices": [{"delta": {"content": "Обрезанный текст"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "length"}]}',
        "data: [DONE]",
    ]

    with _post_with(handler, lambda: lines):
        with pytest.raises(PartialGenerationError) as caught:
            handler.call_api("prompt", "log", use_stream=True, allow_incomplete=True)

    assert caught.value.partial_text == "Обрезанный текст"
    assert any(
        "client max_tokens was not set" in payload.get("message", "")
        for event, payload in worker.events
        if event == "log_message"
    )


def test_stream_falls_back_to_plain_json_body_when_server_ignores_stream_flag():
    """Локальный сервер проигнорировал payload['stream']=True в запросе и
    ответил одним обычным JSON-телом (не SSE) -- ни одна строка не
    начинается с 'data: '. Хендлер обязан распознать это и разобрать тело
    как обычный синхронный ответ вместо того, чтобы терять текст."""
    handler, _worker = _make_handler()
    plain_json_body = (
        '{"choices": [{"finish_reason": "stop", '
        '"message": {"content": "Ответ без стриминга"}}]}'
    )

    with _post_with(handler, lambda: [plain_json_body]):
        result = handler.call_api("prompt", "log", use_stream=True)

    assert result == "Ответ без стриминга"


def test_stream_truly_empty_raises_informative_exception_not_validation_error():
    """Если поток реально пуст (ни одной валидной SSE-строки, ни намёка на
    JSON-тело), должно подниматься понятное сообщение о пустом потоковом
    ответе, а не ValidationFailedError с finish_reason=None."""
    handler, _worker = _make_handler()

    with _post_with(handler, lambda: []):
        with pytest.raises(Exception) as caught:
            handler.call_api("prompt", "log", use_stream=True)

    assert not isinstance(caught.value, ValidationFailedError)
    assert "пуст" in str(caught.value).lower()
