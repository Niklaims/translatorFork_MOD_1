"""Scoring on another machine: the address, the transport, and the refusals."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gemini_translator.qa.estimators.base import (
    QualityEstimateRequest,
    SourceTranslationWindow,
)
from gemini_translator.qa.estimators.cometkiwi_client import (
    SCHEMA_VERSION,
    CometKiwiEstimator,
    CometKiwiRunnerConfig,
    RunnerProcessError,
    remote_transport,
)


def _remote(**overrides) -> CometKiwiRunnerConfig:
    values = {
        "runner_path": "",
        "model_dir": "",
        "model": "wmt22-cometkiwi-da",
        "device": "cuda",
        "endpoint": "http://192.168.1.50:8765",
    }
    values.update(overrides)
    return CometKiwiRunnerConfig(**values)


def test_a_remote_config_does_not_want_a_local_runner_or_local_weights():
    """Раннер и веса живут на ПК; требовать их на Mac — выключить возможность."""
    assert _remote().is_remote is True
    assert _remote().setup_problem() == ""


def test_an_empty_endpoint_keeps_the_local_rules():
    config = CometKiwiRunnerConfig(
        runner_path="", model_dir="", model="wmt22-cometkiwi-da"
    )
    assert config.is_remote is False
    assert config.setup_problem() == "runner_missing"


@pytest.mark.parametrize(
    "endpoint",
    [
        "192.168.1.50:8765",        # без схемы
        "ftp://192.168.1.50:8765",  # чужая схема
        "http://",                  # без хоста
        "http://192.168.1.50:0",    # порт вне диапазона
        "http://192.168.1.50:abc",  # порт не число
    ],
)
def test_an_unusable_address_is_named_and_not_dialled(endpoint):
    assert _remote(endpoint=endpoint).setup_problem() == "endpoint_invalid"


def test_the_model_name_is_still_required_remotely():
    """Оценка без имени модели бесполезна при сравнении прогонов."""
    assert _remote(model="").setup_problem() == "model_missing"


def test_a_trailing_slash_does_not_make_a_second_address():
    assert _remote(endpoint="http://192.168.1.50:8765/").score_url() == (
        "http://192.168.1.50:8765/score"
    )
    assert _remote().score_url() == "http://192.168.1.50:8765/score"


class _Server:
    """A real HTTP server on a free port: the transport is worth testing for real."""

    def __init__(self, handler_body) -> None:
        received = self.received = []

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
                length = int(self.headers.get("Content-Length", "0"))
                received.append(json.loads(self.rfile.read(length)))
                status, body = handler_body(received[-1])
                encoded = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.endpoint = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def _answer(request):
    return 200, json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": request["request_id"],
            "model": request["model"],
            "device": "cuda",
            "scores": [0.81, 0.63],
        }
    )


def _request() -> QualityEstimateRequest:
    return QualityEstimateRequest(
        chapter_id="chapter-1",
        source_language="zh",
        target_language="ru",
        windows=(
            SourceTranslationWindow(
                window_id="w1",
                source="源文本一",
                translation="Перевод один",
                visible_chars=len("Перевод один"),
            ),
            SourceTranslationWindow(
                window_id="w2",
                source="源文本二",
                translation="Перевод два",
                visible_chars=len("Перевод два"),
            ),
        ),
    )


def test_a_remote_estimate_sends_the_same_payload_and_reads_the_answer():
    with _Server(_answer) as server:
        estimator = CometKiwiEstimator(
            _remote(endpoint=server.endpoint),
            license_accepted=True,
        )
        estimate = asyncio.run(estimator.estimate(_request()))

    assert estimate.status == "completed"
    sent = server.received[0]
    assert sent["schema_version"] == SCHEMA_VERSION
    assert [segment["translation"] for segment in sent["segments"]] == [
        "Перевод один",
        "Перевод два",
    ]


def test_a_sleeping_pc_skips_the_estimate_and_never_stops_the_run():
    """Выключенный ПК — не ошибка прогона, а отсутствие оценки с честной причиной."""
    # Порт, который никто не слушает: соединение отвергается сразу.
    estimator = CometKiwiEstimator(
        _remote(endpoint="http://127.0.0.1:9"), license_accepted=True
    )
    estimate = asyncio.run(estimator.estimate(_request()))

    assert estimate.status == "unavailable"
    assert estimate.metadata["reason"] == "endpoint_unreachable"


def test_a_server_error_is_a_named_reason_not_an_exception():
    with _Server(lambda request: (500, "boom")) as server:
        estimator = CometKiwiEstimator(
            _remote(endpoint=server.endpoint), license_accepted=True
        )
        estimate = asyncio.run(estimator.estimate(_request()))

    assert estimate.status == "unavailable"
    assert estimate.metadata["reason"] == "endpoint_status_500"


def test_an_oversized_answer_is_refused_rather_than_read():
    body = json.dumps({"padding": "x" * 1_200_000})
    with _Server(lambda request: (200, body)) as server:
        transport = remote_transport(_remote(endpoint=server.endpoint))
        with pytest.raises(RunnerProcessError) as caught:
            asyncio.run(transport((), "{}", timeout=30))

    assert caught.value.reason == "response_too_large"


def test_an_explicit_transport_still_wins_over_the_address():
    """Тесты и будущие транспорты подменяют отправку, как и раньше."""

    async def fake(command, payload, *, timeout, cancellation=None):
        return json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "request_id": json.loads(payload)["request_id"],
                "model": "wmt22-cometkiwi-da",
                "device": "cuda",
                "scores": [0.5, 0.5],
            }
        )

    estimator = CometKiwiEstimator(
        _remote(), license_accepted=True, run_process=fake
    )
    estimate = asyncio.run(estimator.estimate(_request()))

    assert estimate.status == "completed"
