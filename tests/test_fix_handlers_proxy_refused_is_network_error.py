"""
Прокси из настроек не отвечает (например, SSH-туннель ещё не поднялся или упал):
aiohttp_socks бросает свои ProxyConnectionError / ProxyError / ProxyTimeoutError —
прямых наследников Exception, не OSError. Шесть хендлеров на aiohttp ловили
транспортные сбои как (aiohttp.ClientError, OSError), поэтому отказ прокси уходил
в их `except Exception`: трейсбек в консоль и голый Exception, который
ErrorAnalyzer считает API_ERROR. После двух таких попыток глава проваливалась
окончательно (или уходила на принудительную нарезку), хотя это сетевая пауза.

Классификация в base._process_exception_and_counters
(tests/test_libs_libs_aiohttp_proxy_errors.py) сюда не доходила: хендлер
заворачивал ошибку в Exception раньше.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import contextlib
import io
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiohttp_socks

from gemini_translator.api.errors import ErrorType, NetworkError
from gemini_translator.api.handlers.deepseek import DeepseekApiHandler
from gemini_translator.api.handlers.gemini import GeminiApiHandler
from gemini_translator.api.handlers.huggingface import HuggingFaceApiHandler
from gemini_translator.api.handlers.nvidia import NvidiaApiHandler
from gemini_translator.api.handlers.openmodel import OpenModelApiHandler
from gemini_translator.api.handlers.openrouter import OpenRouterApiHandler
from gemini_translator.core.worker_helpers.error_analyzer import ErrorAnalyzer


class _RefusingProxySession:
    """Сессия, чей коннектор не достучался до прокси: ошибка на входе в post()."""

    def __init__(self, error):
        self.error = error

    def post(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        raise self.error

    async def __aexit__(self, *args):
        return False


def _worker(model_id, provider_config=None):
    return SimpleNamespace(
        provider_config={"is_async": True, "base_timeout": 600, **(provider_config or {})},
        model_config={"id": model_id},
        prompt_builder=SimpleNamespace(system_instruction="sys"),
        temperature=0.7,
        temperature_override_enabled=False,
        thinking_enabled=False,
        thinking_level=None,
        api_key="secret-key-ABCD",
        model_id=model_id,
        is_cancelled=False,
        settings_manager=MagicMock(),
        _post_event=lambda *a, **k: None,
    )


def _make_gemini():
    handler = GeminiApiHandler(_worker("gemini-test"))
    handler.default_url = "https://example.invalid/v1beta/models/gemini-test:generateContent?key=k"
    return handler


def _make_deepseek():
    handler = DeepseekApiHandler(_worker("deepseek-chat"))
    handler.base_url = "https://example.invalid/v1/chat/completions"
    return handler


def _make_huggingface():
    handler = HuggingFaceApiHandler(_worker("google/gemma-3-27b-it:scaleway"))
    handler.base_url = "https://example.invalid/v1/chat/completions"
    return handler


def _make_nvidia():
    handler = NvidiaApiHandler(_worker("meta/llama-4-scout"))
    handler.base_url = "https://example.invalid/v1/chat/completions"
    handler._reset_model_id_to_primary = lambda: None
    return handler


def _make_openmodel():
    handler = OpenModelApiHandler(_worker("deepseek-v4-flash", {"base_url": "https://example.invalid"}))
    handler.setup_client(SimpleNamespace(api_key="secret-key-ABCD"))
    return handler


def _make_openrouter():
    handler = OpenRouterApiHandler(_worker("deepseek/deepseek-chat-v3-0324:free"))
    handler.base_url = "https://example.invalid/v1/chat/completions"
    handler.is_dynamic_local = False
    return handler


HANDLER_FACTORIES = {
    "gemini": _make_gemini,
    "deepseek": _make_deepseek,
    "huggingface": _make_huggingface,
    "nvidia": _make_nvidia,
    "openmodel": _make_openmodel,
    "openrouter": _make_openrouter,
}

PROXY_ERROR_FACTORIES = {
    "ProxyConnectionError": lambda: aiohttp_socks.ProxyConnectionError(
        "[Errno 61] Couldn't connect to proxy 127.0.0.1:8080 [Connect call failed ('127.0.0.1', 8080)]"
    ),
    "ProxyError": lambda: aiohttp_socks.ProxyError("Unexpected SOCKS version number"),
    "ProxyTimeoutError": lambda: aiohttp_socks.ProxyTimeoutError("Proxy connection timed out: 60"),
}


class HandlersTreatProxyFailureAsNetworkErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_aiohttp_handler_turns_proxy_failure_into_network_error(self):
        for handler_name, make_handler in HANDLER_FACTORIES.items():
            for error_name, make_error in PROXY_ERROR_FACTORIES.items():
                with self.subTest(handler=handler_name, error=error_name):
                    handler = make_handler()
                    error = make_error()

                    async def refusing_session(*args, error=error, **kwargs):
                        return _RefusingProxySession(error)

                    handler._get_or_create_session_internal = refusing_session
                    stderr = io.StringIO()

                    with contextlib.redirect_stderr(stderr), self.assertRaises(NetworkError) as raised:
                        await handler.call_api("Привет", "[test]")

                    self.assertIs(raised.exception.__cause__, error)
                    self.assertNotIn("Traceback", stderr.getvalue())


def _closed_local_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ProxyFromSettingsNotListeningTests(unittest.IsolatedAsyncioTestCase):
    """Настоящий ProxyConnector на порт, где никто не слушает, — как у
    выключенного SSH-туннеля на 127.0.0.1:8080."""

    async def test_refused_proxy_is_a_network_pause_not_an_api_error(self):
        handler = GeminiApiHandler(_worker("gemini-test"))
        handler.setup_client(
            client_override=SimpleNamespace(api_key="secret-key-ABCD"),
            proxy_settings={
                "enabled": True,
                "type": "SOCKS5",
                "host": "127.0.0.1",
                "port": _closed_local_port(),
            },
        )
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr), self.assertRaises(NetworkError) as raised:
                await handler.execute_api_call("Привет", "[test]")
        finally:
            await handler._close_thread_session_internal()

        self.assertEqual(ErrorAnalyzer._classify_exception(None, raised.exception), ErrorType.NETWORK)
        self.assertIsInstance(raised.exception.__cause__, aiohttp_socks.ProxyConnectionError)
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
