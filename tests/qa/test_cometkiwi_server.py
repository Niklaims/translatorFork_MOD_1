"""The PC side: one loaded model, its own weights, and nothing the network says."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


def _load(name: str):
    path = Path(__file__).resolve().parents[2] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server_module():
    return _load("translation_qa_cometkiwi_server")


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, data, **kwargs):
        self.calls += 1
        return {"scores": [0.7 for _ in data]}


def _service(server_module, model_dir="C:/kiwi/weights", **overrides):
    model = _Model()
    loads = []

    def loader(path):
        loads.append(str(path))
        return model

    values = {"model_dir": model_dir, "device": "cuda", "model": "wmt22-cometkiwi-da"}
    values.update(overrides)
    service = server_module.ScoringService(loader=loader, **values)
    return service, model, loads


def _payload(**overrides):
    values = {
        "schema_version": 1,
        "request_id": "r-1",
        "model": "wmt22-cometkiwi-da",
        "model_dir": "/anything/the/network/says",
        "device": "cpu",
        "source_language": "zh",
        "target_language": "ru",
        "segments": [{"source": "源", "translation": "Перевод"}],
    }
    values.update(overrides)
    return values


def test_the_weights_come_from_the_command_line_never_from_the_request(server_module):
    """Иначе любой узел сети заставит процесс загрузить произвольный чекпоинт."""
    service, _, loads = _service(server_module)

    answer = service.handle(_payload(model_dir="/etc/passwd", device="cpu"))

    assert loads == ["C:/kiwi/weights"]
    assert answer["device"] == "cuda"
    assert answer["scores"] == [0.7]


def test_the_model_is_loaded_once_for_many_requests(server_module):
    service, model, loads = _service(server_module)

    service.handle(_payload(request_id="r-1"))
    service.handle(_payload(request_id="r-2"))

    assert loads == ["C:/kiwi/weights"]
    assert model.calls == 2


def test_a_request_for_another_model_is_answered_with_a_warning_not_a_refusal(
    server_module,
):
    service, _, _ = _service(server_module)

    answer = service.handle(_payload(model="some-other-model"))

    assert answer["scores"] == [0.7]
    assert answer["model"] == "wmt22-cometkiwi-da"
    assert answer["model_mismatch"] == "some-other-model"


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({"schema_version": 2}, "unsupported_schema_version"),
        ({"segments": []}, "invalid_request"),
        ({"segments": [{"source": "源", "translation": "П", "reference": "R"}]},
         "unexpected_segment_field"),
        ({"request_id": ""}, "invalid_request"),
    ],
)
def test_a_bad_request_is_refused_before_the_model_is_touched(
    server_module, payload, reason
):
    service, _, loads = _service(server_module)

    answer = service.handle(_payload(**payload))

    assert answer["error"] == reason
    assert loads == []


def test_health_answers_without_loading_anything(server_module):
    service, _, loads = _service(server_module)

    health = service.health()

    assert health == {
        "schema_version": 1,
        "model": "wmt22-cometkiwi-da",
        "device": "cuda",
        "loaded": False,
    }
    assert loads == []


def test_health_says_when_the_weights_are_in_memory(server_module):
    service, _, _ = _service(server_module)
    service.handle(_payload())

    assert service.health()["loaded"] is True


def test_a_failing_model_answers_a_reason_and_never_the_chapter_text(server_module):
    class _Broken:
        def predict(self, data, **kwargs):
            raise RuntimeError("Перевод один утёк бы сюда")

    service = server_module.ScoringService(
        model_dir="C:/kiwi/weights",
        device="cuda",
        model="wmt22-cometkiwi-da",
        loader=lambda path: _Broken(),
    )

    answer = service.handle(_payload())

    assert answer["error"] == "runtimeerror"
    assert "Перевод" not in json.dumps(answer, ensure_ascii=False)
