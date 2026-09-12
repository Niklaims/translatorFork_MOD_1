"""Each failure of a quality estimate reaches the journal under its own name.

``quality_score_status`` keeps a reason only when it is a short ASCII token.
Four real failures used to lose their names on the way there: a runner killed
by a signal (``runner_exit_-9`` fails that bound), scores no model should
return (``aggregate`` raised free text), a CUDA out-of-memory (the server named
it after its class), and a request the PC refused for its schema version (the
refusal carried no request id, so the Mac read it as ``request_id_mismatch``).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from gemini_translator.qa.estimators.base import (
    QualityEstimateError,
    QualityEstimateRequest,
    SourceTranslationWindow,
    unavailable,
)
from gemini_translator.qa.estimators.cometkiwi_client import (
    CometKiwiEstimator,
    CometKiwiRunnerConfig,
    _exit_reason,
    _read_answer,
)
from gemini_translator.qa.service import _quality_score_status


MODEL = "wmt22-cometkiwi-da"
SEGMENT = {"source": "源文本", "translation": "Перевод"}


def _load_server():
    name = "translation_qa_cometkiwi_server"
    path = Path(__file__).resolve().parents[2] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server_module():
    return _load_server()


def _request() -> QualityEstimateRequest:
    return QualityEstimateRequest(
        chapter_id="chapter-1",
        source_language="zh",
        target_language="ru",
        windows=(
            SourceTranslationWindow(
                window_id="w1",
                source=SEGMENT["source"],
                translation=SEGMENT["translation"],
                visible_chars=len(SEGMENT["translation"]),
            ),
        ),
    )


def _remote_config() -> CometKiwiRunnerConfig:
    return CometKiwiRunnerConfig(
        runner_path="",
        model_dir="",
        model=MODEL,
        device="cuda",
        endpoint="http://192.168.1.50:8765",
    )


def _scoring_service(server_module, model):
    return server_module.ScoringService(
        model_dir="C:/kiwi/weights", device="cuda", model=MODEL, loader=lambda path: model
    )


def _through(service):
    """A transport that hands each request to the PC server's own handler."""

    async def send(command, payload, *, timeout, cancellation=None):
        return json.dumps(service.handle(json.loads(payload)), ensure_ascii=False)

    return send


def _estimate_through(transport):
    estimator = CometKiwiEstimator(
        _remote_config(), license_accepted=True, run_process=transport
    )
    return asyncio.run(estimator.estimate(_request()))


# --- a local runner killed by a signal -------------------------------------


@pytest.mark.parametrize(
    "returncode, stderr, reason",
    [
        (-9, b"", "runner_signal_9"),
        (-15, b"", "runner_signal_15"),
        (1, b"", "runner_exit_1"),
        (137, b"", "runner_exit_137"),
        (-9, b"CUDA out of memory", "out_of_memory"),
        (None, b"", "runner_crashed"),
    ],
)
def test_a_signal_is_named_and_every_other_exit_reason_is_unchanged(
    returncode, stderr, reason
):
    assert _exit_reason(returncode, stderr) == reason


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals only")
def test_a_runner_killed_by_a_signal_is_journalled_under_that_signal(tmp_path):
    """asyncio reports a signal as a negative return code; the bound refuses a minus sign."""
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import os\nimport signal\n\nos.kill(os.getpid(), signal.SIGKILL)\n",
        encoding="utf-8",
    )
    weights = tmp_path / "weights"
    weights.mkdir()
    estimator = CometKiwiEstimator(
        CometKiwiRunnerConfig(
            runner_path=str(runner),
            model_dir=str(weights),
            model=MODEL,
            python_executable=sys.executable,
            timeout_seconds=60,
        ),
        license_accepted=True,
    )

    estimate = asyncio.run(estimator.estimate(_request()))

    assert estimate.metadata["reason"] == "runner_signal_9"
    assert _quality_score_status(estimate) == "unavailable:runner_signal_9"


# --- scores no model should return ------------------------------------------


@pytest.mark.parametrize("score", [1.02, -0.01])
def test_a_score_outside_the_unit_interval_is_journalled_as_invalid_scores(
    server_module, score
):
    """Scored by the PC server's own handler, read back by the real estimator."""

    class _Model:
        def predict(self, data, **kwargs):
            return {"scores": [score for _ in data]}

    estimate = _estimate_through(_through(_scoring_service(server_module, _Model())))

    assert estimate.status == "unavailable"
    assert estimate.metadata["reason"] == "invalid_scores"
    assert _quality_score_status(estimate) == "unavailable:invalid_scores"


def test_a_score_that_is_not_a_number_is_journalled_as_invalid_scores():
    async def send(command, payload, *, timeout, cancellation=None):
        request = json.loads(payload)
        return json.dumps(
            {
                "schema_version": 1,
                "request_id": request["request_id"],
                "model": MODEL,
                "device": "cuda",
                "scores": ["0.5"],
            }
        )

    estimate = _estimate_through(send)

    assert _quality_score_status(estimate) == "unavailable:invalid_scores"


# --- a CUDA out-of-memory on the PC -----------------------------------------


class OutOfMemoryError(RuntimeError):
    """Shaped like torch.OutOfMemoryError: a RuntimeError, not a MemoryError."""


def test_a_cuda_out_of_memory_reaches_the_journal_as_out_of_memory(server_module):
    class _Gpu:
        def predict(self, data, **kwargs):
            raise OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")

    service = _scoring_service(server_module, _Gpu())

    answer = service.handle(
        {"schema_version": 1, "request_id": "r-1", "model": MODEL, "segments": [SEGMENT]}
    )

    assert answer["error"] == "out_of_memory"
    with pytest.raises(QualityEstimateError) as caught:
        _read_answer(json.dumps(answer), "r-1", 1)
    assert str(caught.value) == "runner_error:out_of_memory"
    assert _quality_score_status(unavailable("cometkiwi", MODEL, str(caught.value))) == (
        "unavailable:runner_error:out_of_memory"
    )
    assert _quality_score_status(_estimate_through(_through(service))) == (
        "unavailable:runner_error:out_of_memory"
    )


# --- a Mac and a PC on different schema versions ------------------------------


@pytest.mark.parametrize("request_id", ["r-9", "x" * 128])
def test_a_request_refused_for_its_schema_version_is_answered_under_its_own_id(
    server_module, request_id
):
    """The client compares ids before it reads an error; an empty id hid the real one."""
    service = _scoring_service(server_module, object())

    answer = service.handle(
        {
            "schema_version": 2,
            "request_id": request_id,
            "model": MODEL,
            "segments": [SEGMENT],
        }
    )

    assert answer == {
        "schema_version": 1,
        "request_id": request_id,
        "error": "unsupported_schema_version",
    }
    with pytest.raises(QualityEstimateError) as caught:
        _read_answer(json.dumps(answer), request_id, 1)
    assert str(caught.value) == "runner_error:unsupported_schema_version"


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "request_id": ""},
        {"schema_version": 2, "request_id": 7},
        {"schema_version": 2, "request_id": None},
        {"schema_version": 2, "request_id": "x" * 129},
        {"schema_version": 2},
        ["r-9"],
    ],
    ids=["empty", "number", "null", "too-long", "absent", "not-an-object"],
)
def test_a_request_id_that_is_not_a_short_string_is_not_echoed(server_module, payload):
    service = _scoring_service(server_module, object())

    answer = service.handle(payload)

    assert answer["request_id"] == ""
    assert "error" in answer
