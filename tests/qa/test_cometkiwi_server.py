"""The PC side: one loaded model, its own weights, and nothing the network says."""

from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

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


# --- the same behaviour, proven over a real HTTP server -------------------
#
# Everything above drives ScoringService in-process. A manual check is not
# coverage, so the same claims are repeated here against an actual socket:
# a ThreadingHTTPServer built from the module's own build_handler(service),
# bound to an OS-assigned port, served from a daemon thread. The idiom is the
# one tests/qa/test_cometkiwi_remote.py already established for the client
# side of this same wire protocol.


class _RealServer:
    """A real HTTP server on a free port, built from the module's own handler."""

    def __init__(self, server_module, service) -> None:
        self._httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), server_module.build_handler(service)
        )
        self.host = "127.0.0.1"
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://{self.host}:{self.port}"

    def __enter__(self):
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()


def _post_bytes(base_url: str, path: str, data: bytes):
    request = urllib.request.Request(f"{base_url}{path}", data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _post(base_url: str, path: str, payload: dict):
    return _post_bytes(base_url, path, json.dumps(payload).encode("utf-8"))


def _get(base_url: str, path: str):
    try:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_a_hostile_request_over_real_http_is_still_pinned_to_the_servers_own_weights(
    server_module,
):
    """The task's central security property, proven over the wire, not only in-process."""
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service) as server:
        status, answer = _post(
            server.base_url,
            "/score",
            _payload(model_dir="/etc/passwd", device="cpu"),
        )

    assert status == 200
    assert loads == ["C:/kiwi/weights"]
    assert answer["device"] == "cuda"
    assert answer["scores"] == [0.7]


def test_health_over_real_http_answers_without_touching_the_loader(server_module):
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service) as server:
        status, body = _get(server.base_url, "/health")

    assert status == 200
    assert body == {
        "schema_version": 1,
        "model": "wmt22-cometkiwi-da",
        "device": "cuda",
        "loaded": False,
    }
    assert loads == []


def test_an_unknown_path_is_refused_on_both_methods_without_touching_the_loader(
    server_module,
):
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service) as server:
        get_status, get_body = _get(server.base_url, "/nope")
        post_status, post_body = _post(server.base_url, "/nope", _payload())

    assert get_status == 404
    assert get_body == {"error": "not_found"}
    assert post_status == 404
    assert post_body == {"error": "not_found"}
    assert loads == []


def test_an_oversized_content_length_is_refused_before_the_body_is_read(
    server_module,
):
    """The guard must trip on the header alone; it must never wait to read megabytes."""
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service) as server:
        connection = http.client.HTTPConnection(server.host, server.port, timeout=5)
        try:
            connection.putrequest("POST", "/score")
            connection.putheader(
                "Content-Length", str(server_module.MAX_REQUEST_BYTES + 1)
            )
            connection.endheaders()
            response = connection.getresponse()
            status = response.status
            body = json.loads(response.read())
        finally:
            connection.close()

    assert status == 413
    assert body == {"error": "request_too_large"}
    assert loads == []


def test_a_body_that_is_not_json_is_answered_400(server_module):
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service) as server:
        status, body = _post_bytes(server.base_url, "/score", b"not json")

    assert status == 400
    assert body == {"error": "invalid_request"}
    assert loads == []


def test_the_log_never_carries_a_word_of_the_chapter(server_module, capsys):
    """``log_message`` exists precisely so a request body never reaches the terminal."""
    service, _, _ = _service(server_module)
    phrase = "УникальнаяФразаТолькоВЭтойГлаве9f3a"
    with _RealServer(server_module, service) as server:
        _post(
            server.base_url,
            "/score",
            _payload(segments=[{"source": "源", "translation": phrase}]),
        )

    captured = capsys.readouterr()
    assert phrase not in captured.err
    assert phrase not in captured.out
