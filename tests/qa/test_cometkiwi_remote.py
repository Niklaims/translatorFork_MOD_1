"""Scoring on another machine: the address, the transport, and the refusals."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import aiohttp
import pytest

from gemini_translator.qa.capabilities import QaCapabilityKey
from gemini_translator.qa.estimators.base import (
    QualityEstimate,
    QualityEstimateRequest,
    SourceTranslationWindow,
    unavailable,
)
from gemini_translator.qa.estimators.cometkiwi_client import (
    REMOTE_CONNECT_TIMEOUT_SECONDS,
    SCHEMA_VERSION,
    CometKiwiEstimator,
    CometKiwiRunnerConfig,
    RunnerProcessError,
    remote_transport,
)
from gemini_translator.qa.models import ChapterMetrics, RiskLevel
from gemini_translator.qa.service import ChapterQaResult, _quality_score_status
from gemini_translator.qa.settings import QaCapabilitySettings, QaSettings
from tests.qa.test_translation_quality_service import _service


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


# --- settings and readiness: an address stands in for a local install -----


def _settings(**overrides) -> QaSettings:
    values = {
        "capabilities": QaCapabilitySettings(cometkiwi_enabled=True),
        "cometkiwi_model": "wmt22-cometkiwi-da",
        "cometkiwi_license_accepted": True,
        "cometkiwi_endpoint": "http://192.168.1.50:8765",
    }
    values.update(overrides)
    return QaSettings(**values)


def test_an_address_stands_in_for_the_local_runner_and_weights():
    """Иначе возможность выключится молча: раннера и весов на этой машине нет."""
    settings = _settings()

    assert settings.cometkiwi_is_remote is True
    assert QaCapabilityKey.COMETKIWI.value not in settings.unsatisfied_requirements()
    assert settings.effective_capabilities().cometkiwi_enabled is True


def test_without_an_address_the_local_runner_is_still_required():
    settings = _settings(cometkiwi_endpoint="")

    assert QaCapabilityKey.COMETKIWI.value in settings.unsatisfied_requirements()
    assert settings.effective_capabilities().cometkiwi_enabled is False


def test_the_licence_is_owed_in_both_modes():
    settings = _settings(cometkiwi_license_accepted=False)

    assert QaCapabilityKey.COMETKIWI.value in settings.unsatisfied_requirements()


def test_the_address_survives_a_save_and_a_load():
    settings = _settings()

    assert QaSettings.from_dict(settings.to_dict()).cometkiwi_endpoint == (
        "http://192.168.1.50:8765"
    )


def test_the_setup_description_asks_for_the_address_not_for_local_weights():
    from gemini_translator.qa.estimators.cometkiwi_model_manager import (
        describe_cometkiwi_setup,
    )

    assert describe_cometkiwi_setup(_settings(), None, None) == ""
    described = describe_cometkiwi_setup(_settings(cometkiwi_model=""), None, None)
    assert "модель" in described
    assert "путь к runner" not in described
    assert "установленные веса" not in described


# --- the reason travels into quality_score_status, bounded ----------------


def test_an_unavailable_reason_is_carried_in_the_status_string():
    estimate = unavailable("cometkiwi", "wmt22-cometkiwi-da", "endpoint_unreachable")

    assert _quality_score_status(estimate) == "unavailable:endpoint_unreachable"


def test_a_completed_estimate_keeps_the_bare_status():
    """A completed estimate is also what clears an earlier reason once the PC wakes."""
    estimate = QualityEstimate(
        estimator="cometkiwi",
        model="wmt22-cometkiwi-da",
        window_scores=(0.5,),
        status="completed",
    )

    assert _quality_score_status(estimate) == "completed"


def test_an_unavailable_estimate_with_no_reason_keeps_the_bare_status():
    estimate = QualityEstimate(
        estimator="cometkiwi", model="wmt22-cometkiwi-da", status="unavailable"
    )

    assert _quality_score_status(estimate) == "unavailable"


@pytest.mark.parametrize(
    "hostile_reason",
    [
        "=cmd|'/C calc'!A1",  # spreadsheet formula injection
        "bad,reason",  # breaks a CSV column
        "bad\nreason",  # breaks a CSV or log line
        "неизвестная ошибка сервера",  # outside the bounded ascii vocabulary
        "a" * 65,  # one character over the persisted bound
    ],
)
def test_hostile_reasons_are_never_persisted_verbatim(hostile_reason):
    """No authentication guards this server; free text must not reach the journal."""
    estimate = unavailable("cometkiwi", "wmt22-cometkiwi-da", hostile_reason)

    assert _quality_score_status(estimate) == "unavailable:invalid_reason"


def test_a_compound_runner_reason_is_persisted_as_two_segments():
    """A runner's own failure - out_of_memory above all - must reach the journal."""
    estimate = unavailable(
        "cometkiwi", "wmt22-cometkiwi-da", "runner_error:out_of_memory"
    )

    assert _quality_score_status(estimate) == "unavailable:runner_error:out_of_memory"


def test_the_real_safe_reason_output_survives_the_composition():
    """Regression guard: neither function may silently collapse this again."""
    from gemini_translator.qa.estimators.cometkiwi_client import _safe_reason

    estimate = unavailable(
        "cometkiwi", "wmt22-cometkiwi-da", _safe_reason("Out of memory")
    )

    assert _quality_score_status(estimate) == "unavailable:runner_error:out_of_memory"


def test_a_non_ascii_digit_in_the_suffix_is_still_rejected():
    """str.isdigit() is true for non-ASCII digits; the persistence bound is not."""
    estimate = unavailable("cometkiwi", "wmt22-cometkiwi-da", "runner_error:gpu²")

    assert _quality_score_status(estimate) == "unavailable:invalid_reason"


def test_a_reason_with_two_colons_is_rejected():
    estimate = unavailable("cometkiwi", "wmt22-cometkiwi-da", "a:b:c")

    assert _quality_score_status(estimate) == "unavailable:invalid_reason"


def test_attach_quality_estimate_persists_the_reason_and_round_trips(tmp_path):
    """The journal, not just the in-memory result, must carry the reason."""
    service, journal, journal_path = _service(tmp_path)
    result = ChapterQaResult(
        chapter_id="chapter-1",
        risk_level=RiskLevel.LOW,
        may_continue_translation=True,
        coverage_mode="unavailable",
        metrics=ChapterMetrics(
            chapter_id="chapter-1", source_language="zh", target_language="ru"
        ),
    )
    estimate = unavailable("cometkiwi", "wmt22-cometkiwi-da", "endpoint_unreachable")

    updated = service.attach_quality_estimate(result, estimate)

    assert updated.metrics.quality_score_status == "unavailable:endpoint_unreachable"
    payload = journal.metrics["chapter-1"].to_dict()
    assert payload["quality_score_status"] == "unavailable:endpoint_unreachable"
    assert ChapterMetrics.from_dict(payload).quality_score_status == (
        "unavailable:endpoint_unreachable"
    )


# --- a sleeping PC must not be mistaken for a slow one ---------------------


def test_the_session_timeout_bounds_the_connect_phase_separately(monkeypatch):
    """total stays the caller's budget; sock_connect is this transport's own bound."""
    captured = {}
    real_client_timeout = aiohttp.ClientTimeout

    def _spy_timeout(*args, **kwargs):
        captured["kwargs"] = kwargs
        return real_client_timeout(*args, **kwargs)

    monkeypatch.setattr(aiohttp, "ClientTimeout", _spy_timeout)
    transport = remote_transport(_remote(endpoint="http://127.0.0.1:9"))

    with pytest.raises(RunnerProcessError):
        asyncio.run(transport((), "{}", timeout=42.0))

    assert captured["kwargs"]["total"] == 42.0
    assert captured["kwargs"]["sock_connect"] == REMOTE_CONNECT_TIMEOUT_SECONDS


def test_a_connection_timeout_is_endpoint_unreachable_not_timeout(monkeypatch):
    """A connection that never came up is a sleeping machine, not a slow one."""

    def _raise_connection_timeout(self, *args, **kwargs):
        raise aiohttp.ConnectionTimeoutError()

    monkeypatch.setattr(aiohttp.ClientSession, "post", _raise_connection_timeout)
    estimator = CometKiwiEstimator(
        _remote(endpoint="http://192.168.1.50:8765"), license_accepted=True
    )

    estimate = asyncio.run(estimator.estimate(_request()))

    assert estimate.status == "unavailable"
    assert estimate.metadata["reason"] == "endpoint_unreachable"


def test_a_plain_request_timeout_still_reads_as_timeout(monkeypatch):
    """Only a failed connection is "endpoint_unreachable"; a slow answer is not."""

    def _raise_timeout(self, *args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(aiohttp.ClientSession, "post", _raise_timeout)
    estimator = CometKiwiEstimator(
        _remote(endpoint="http://192.168.1.50:8765"), license_accepted=True
    )

    estimate = asyncio.run(estimator.estimate(_request()))

    assert estimate.status == "unavailable"
    assert estimate.metadata["reason"] == "timeout"
