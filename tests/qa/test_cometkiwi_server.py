"""The PC side: one loaded model, its own weights, and nothing the network says."""

from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import types
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


@pytest.fixture(autouse=True)
def _offline_switch_left_as_found(monkeypatch):
    # main() turns the Hub libraries offline for its own process; restored
    # after each test so that none hands the setting on to the next.
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)


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


class _JoinedServer(ThreadingHTTPServer):
    """A ThreadingHTTPServer whose server_close() waits for its request threads.

    ThreadingHTTPServer serves each request on a daemon thread, and
    socketserver's server_close() joins only non-daemon ones. The handler now
    writes its log line after the answer, so a client can return before that
    line exists; with daemon threads, captured stderr read after the ``with``
    block would still race the request thread.
    """

    daemon_threads = False


class _RealServer:
    """A real HTTP server on a free port, built from the module's own handler."""

    def __init__(self, server_module, service, *, handler_timeout=None) -> None:
        handler = server_module.build_handler(service)
        if handler_timeout is not None:
            handler.timeout = handler_timeout
        self._httpd = _JoinedServer(("127.0.0.1", 0), handler)
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


# --- the transport-layer backstop, and the guard next to it ---------------
#
# Review found two gaps in the same handler: an exception that escapes
# do_GET/do_POST used to reach socketserver's own handle_error, which prints
# a full traceback and never goes through log_message; and a negative
# Content-Length parsed fine but sent rfile.read() to read until EOF, hanging
# the request thread. Both are fixed in build_handler; these tests pin both.


def test_an_exception_that_escapes_the_service_leaks_neither_itself_nor_the_chapter(
    server_module, capsys
):
    """Safe even if ScoringService's own catch-all is bypassed entirely.

    ``socketserver.BaseServer.handle_error`` prints a full traceback for any
    exception ``do_POST`` does not catch itself, and it never goes through
    ``log_message``. A fake service whose ``handle`` raises directly (rather
    than a real ``ScoringService``, whose own ``handle`` already turns
    exceptions into a short reason) proves the handler's own backstop catches
    it independently of that inner discipline.
    """
    exception_text = "traceback-leak-canary-4f2c8e19"
    chapter_phrase = "ГлаваКоторуюНельзяУвидетьВЛоге-a1b2c3"

    class _RaisingService:
        def health(self) -> dict:
            return {
                "schema_version": 1,
                "model": "m",
                "device": "cpu",
                "loaded": False,
            }

        def handle(self, payload):
            raise RuntimeError(exception_text)

    with _RealServer(server_module, _RaisingService()) as server:
        status, body = _post(
            server.base_url,
            "/score",
            _payload(segments=[{"source": "源", "translation": chapter_phrase}]),
        )

    captured = capsys.readouterr()
    assert status == 500
    assert body == {"error": "server_error"}
    assert exception_text not in captured.err
    assert exception_text not in captured.out
    assert chapter_phrase not in captured.err
    assert chapter_phrase not in captured.out
    # One fixed line for the whole failure, written after the 500 went out.
    assert captured.err == "POST /score -> unhandled exception\n"


def test_a_negative_content_length_is_refused_promptly_not_read_until_eof(
    server_module,
):
    """``int("-1")`` parses fine; ``rfile.read(-1)`` reads until EOF and hangs."""
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service) as server:
        connection = http.client.HTTPConnection(server.host, server.port, timeout=5)
        try:
            connection.putrequest("POST", "/score")
            connection.putheader("Content-Length", "-1")
            connection.endheaders()
            response = connection.getresponse()
            status = response.status
            body = json.loads(response.read())
        finally:
            connection.close()

    assert status == 400
    assert body == {"error": "invalid_request"}
    assert loads == []


# --- the request log: never a traceback, never the request, always after ----
#
# log_message used to read self.command and self.path, which the stdlib has
# not set yet when it reports a malformed request line: the AttributeError
# went to socketserver's handle_error, which printed a traceback and sent the
# client nothing. The same line said "done" whatever the outcome, and it was
# written from send_response(), before the answer, so a Windows console
# holding a text selection held the answer as well. The line now follows the
# answer, which is why every assertion that a line IS present reads captured
# stderr only after _RealServer has closed the server and joined its threads.


def _exchange(host: str, port: int, raw: bytes) -> bytes:
    """Send raw bytes on a fresh connection and read until the server closes it."""
    with socket.create_connection((host, port), timeout=5) as connection:
        connection.sendall(raw)
        received = bytearray()
        while chunk := connection.recv(65536):
            received.extend(chunk)
    return bytes(received)


@pytest.mark.parametrize(
    "raw, status_line",
    [
        # Four words ending in a valid version: the stdlib records that
        # version before it rejects the syntax, so its 400 has a status line.
        (b"GET /a /b-canary-5e1d HTTP/1.1\r\n", b"HTTP/1.0 400 "),
        # One byte over the stdlib's 65536-byte limit and nothing after it:
        # the server reads every byte it was sent, so it closes cleanly
        # instead of resetting a connection with unread data in it.
        (b"GET /" + b"a" * 65532, b"HTTP/1.0 414 "),
    ],
    ids=["malformed-request-line", "request-line-over-65536-bytes"],
)
def test_a_malformed_request_line_is_answered_4xx_not_dropped(
    server_module, capsys, raw, status_line
):
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service) as server:
        response = _exchange(server.host, server.port, raw)

    captured = capsys.readouterr()
    assert response.startswith(status_line)
    assert "Traceback" not in captured.err
    assert "canary" not in captured.err
    assert loads == []


def test_a_request_line_with_an_unparsable_version_gets_an_answer_not_a_traceback(
    server_module, capsys
):
    """The review's own probe line.

    The stdlib rejects the last word as a version before it has recorded any
    version at all, so it answers the way HTTP/0.9 is answered: an error page
    with no status line. What matters here is that the page is sent at all.
    """
    service, _, _ = _service(server_module)
    with _RealServer(server_module, service) as server:
        response = _exchange(
            server.host, server.port, b"GET / HTTP/1.1 canary-77d0\r\n"
        )

    captured = capsys.readouterr()
    assert b"400" in response
    assert "Traceback" not in captured.err
    assert "canary" not in captured.err


def test_log_message_writes_its_fixed_format_and_never_its_arguments(
    server_module, capsys
):
    """For a malformed request line the stdlib passes that raw line as an argument."""
    service, _, _ = _service(server_module)
    handler_class = server_module.build_handler(service)
    # No request was ever parsed on this instance: command and path are unset.
    handler = handler_class.__new__(handler_class)

    handler.log_message("code %d, message %s", 400, "Bad request syntax ('canary')")

    assert capsys.readouterr().err == "? ? -> code %d, message %s\n"


def test_each_answer_is_logged_with_its_own_status(server_module, capsys):
    service, _, _ = _service(server_module)
    with _RealServer(server_module, service) as server:
        score_status, _ = _post(server.base_url, "/score", _payload())
        health_status, _ = _get(server.base_url, "/health")
        missing_status, _ = _get(server.base_url, "/nope")

    captured = capsys.readouterr()
    assert (score_status, health_status, missing_status) == (200, 200, 404)
    # Each line follows its own answer, so two requests in a row may log in
    # either order.
    assert sorted(captured.err.splitlines()) == sorted(
        ["POST /score -> 200", "GET /health -> 200", "GET ? -> 404"]
    )


def test_a_path_this_server_does_not_serve_never_reaches_the_log(
    server_module, capsys
):
    """A path is the client's own text: only a route this server serves is named."""
    service, _, _ = _service(server_module)
    with _RealServer(server_module, service) as server:
        response = _exchange(
            server.host, server.port, b"GET /\x1b[2Jcanary-3c9a HTTP/1.0\r\n\r\n"
        )

    captured = capsys.readouterr()
    assert response.startswith(b"HTTP/1.0 404 ")
    assert captured.err == "GET ? -> 404\n"


# --- a client that stops sending ---------------------------------------------


def test_the_handler_gives_up_on_a_silent_connection_after_a_minute(server_module):
    service, _, _ = _service(server_module)

    assert server_module.build_handler(service).timeout == 60


def test_a_client_that_stalls_mid_body_is_disconnected(server_module):
    """Without a socket timeout this request thread would wait in rfile.read() for good."""
    service, _, loads = _service(server_module)
    with _RealServer(server_module, service, handler_timeout=0.5) as server:
        with socket.create_connection(
            (server.host, server.port), timeout=5
        ) as connection:
            connection.sendall(
                b"POST /score HTTP/1.0\r\nContent-Length: 100\r\n\r\n" + b'{"schema'
            )
            started = time.monotonic()
            try:
                while connection.recv(65536):
                    pass
            except TimeoutError:
                pytest.fail("the server kept a stalled connection open")
            elapsed = time.monotonic() - started

    assert 0.3 <= elapsed < 3
    assert loads == []


# --- one server per port on Windows ------------------------------------------


@pytest.mark.parametrize(
    "platform, reuses_address", [("win32", False), ("darwin", True)]
)
def test_the_server_refuses_to_share_its_port_only_on_windows(
    server_module, monkeypatch, platform, reuses_address
):
    """On Windows SO_REUSEADDR lets a second process bind a port already listening."""
    service, _, _ = _service(server_module)
    monkeypatch.setattr(sys, "platform", platform)
    server = server_module.ScoringHTTPServer(
        ("127.0.0.1", 0), server_module.build_handler(service)
    )
    try:
        option = server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)
    finally:
        server.server_close()

    assert server.allow_reuse_address is reuses_address
    # Decided before bind(): the option is actually on the socket, or not.
    assert bool(option) is reuses_address


# --- a weights directory the loader would find nothing in --------------------


def _refuse_to_serve(*args, **kwargs):
    raise AssertionError("main() must not construct a server")


def test_main_refuses_a_weights_directory_with_no_checkpoint_in_it(
    server_module, monkeypatch, capsys, tmp_path
):
    """Hugging Face keeps the .ckpt in checkpoints/, one level below the model root.

    Started on that root, the server used to pass the connection check and then
    answer checkpoint_missing for every chapter.
    """
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "model.ckpt").write_bytes(b"")
    (tmp_path / "hparams.yaml").write_text("", encoding="utf-8")
    monkeypatch.setattr(server_module, "ScoringHTTPServer", _refuse_to_serve)

    code = server_module.main(
        ["--model-dir", str(tmp_path), "--model", "wmt22-cometkiwi-da"]
    )

    assert code == 2
    assert capsys.readouterr().err == (
        f"В каталоге весов нет файла .ckpt: {tmp_path}\n"
        "Укажите каталог, в котором лежит сам .ckpt — у модели, скачанной с "
        "Hugging Face, это подкаталог checkpoints. Остальные файлы модели не "
        "перемещайте.\n"
    )


def test_main_starts_on_the_directory_that_holds_the_checkpoint(
    server_module, monkeypatch, capsys, tmp_path
):
    (tmp_path / "model.ckpt").write_bytes(b"")
    constructed = []

    class _IdleServer:
        def __init__(self, address, handler_class):
            constructed.append(address)

        def serve_forever(self):
            return

        def server_close(self):
            return

    monkeypatch.setattr(server_module, "ScoringHTTPServer", _IdleServer)

    code = server_module.main(
        ["--model-dir", str(tmp_path), "--model", "wmt22-cometkiwi-da", "--port", "8765"]
    )

    assert code == 0
    assert constructed == [("0.0.0.0", 8765)]
    assert ".ckpt" not in capsys.readouterr().err


def test_main_still_refuses_a_weights_directory_that_does_not_exist(
    server_module, monkeypatch, capsys, tmp_path
):
    missing = tmp_path / "absent"
    monkeypatch.setattr(server_module, "ScoringHTTPServer", _refuse_to_serve)

    code = server_module.main(
        ["--model-dir", str(missing), "--model", "wmt22-cometkiwi-da"]
    )

    assert code == 2
    assert capsys.readouterr().err == f"Каталог весов не найден: {missing}\n"


# --- a model load that needs nothing from the internet ------------------------

# hparams.yaml exactly as Unbabel/wmt22-cometkiwi-da ships it.
_KIWI_HPARAMS = """\
activations: Tanh
batch_size: 4
class_identifier: unified_metric
dropout: 0.1
encoder_learning_rate: 1.0e-06
encoder_model: XLM-RoBERTa
final_activation: null
hidden_sizes:
- 3072
- 1024
input_segments:
- mt
- src
keep_embeddings_frozen: true
layer: mix
layer_norm: false
layer_transformation: sparsemax_patch
layerwise_decay: 0.95
learning_rate: 1.5e-05
loss: mse
loss_lambda: 0.65
nr_frozen_epochs: 0.3
optimizer: AdamW
pool: avg
pretrained_model: microsoft/infoxlm-large
sent_layer: mix
train_data:
- data/1720-da.mlqe-src.csv
validation_data:
- data/wmt-ende-newstest2021.csv
- data/wmt-enru-newstest2021.csv
- data/wmt-zhen-newstest2021.csv
word_layer: 24
word_level_training: false
word_weights:
- 0.15
- 0.85
"""


def _downloaded_model(root: Path) -> Path:
    """Lay a model out as Hugging Face downloads it; return the checkpoint's directory."""
    (root / "hparams.yaml").write_text(_KIWI_HPARAMS, encoding="utf-8")
    checkpoints = root / "checkpoints"
    checkpoints.mkdir()
    (checkpoints / "model.ckpt").write_bytes(b"")
    return checkpoints


def _hub_cache(monkeypatch, *on_disk: tuple[str, str]) -> None:
    """Stand in for huggingface_hub, which this environment lacks: its cache lookup only.

    Answers as the real try_to_load_from_cache does, a path for a cached file and
    None for one it knows nothing of, and only for the (repo, file) pairs given.
    """
    hub = types.ModuleType("huggingface_hub")

    def try_to_load_from_cache(repo_id, filename, cache_dir=None, revision=None, repo_type=None):
        if (repo_id, filename) in on_disk:
            return f"/hub/models--{repo_id.replace('/', '--')}/snapshots/0/{filename}"
        return None

    hub.try_to_load_from_cache = try_to_load_from_cache
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)


def _server_recording_the_offline_switch(seen: list):
    class _Server:
        def __init__(self, address, handler_class):
            return

        def serve_forever(self):
            # What the process holds while serving is what the first request's
            # import of COMET, and with it of the Hub libraries, reads.
            seen.append(os.environ.get("HF_HUB_OFFLINE"))

        def server_close(self):
            return

    return _Server


def test_main_serves_with_the_hub_libraries_offline(server_module, monkeypatch, tmp_path):
    """Every file was on disk, and an antivirus inspecting HTTPS still failed the load.

    huggingface_hub re-raises an SSL or proxy failure instead of answering from
    its cache, and transformers' Mistral-regex check asks the Hub for model info
    whatever local_files_only says. Only HF_HUB_OFFLINE, which both libraries
    read once at import, keeps a fully cached load off the network.
    """
    checkpoints = _downloaded_model(tmp_path)
    _hub_cache(monkeypatch, ("microsoft/infoxlm-large", "config.json"))
    seen = []
    monkeypatch.setattr(
        server_module, "ScoringHTTPServer", _server_recording_the_offline_switch(seen)
    )

    code = server_module.main(
        ["--model-dir", str(checkpoints), "--model", "wmt22-cometkiwi-da"]
    )

    assert code == 0
    assert seen == ["1"]


def test_main_leaves_a_switch_the_user_set_alone(server_module, monkeypatch, tmp_path):
    """Asked to stay online, the first load fetches the encoder itself: nothing to check."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    checkpoints = _downloaded_model(tmp_path)
    _hub_cache(monkeypatch)
    seen = []
    monkeypatch.setattr(
        server_module, "ScoringHTTPServer", _server_recording_the_offline_switch(seen)
    )

    code = server_module.main(
        ["--model-dir", str(checkpoints), "--model", "wmt22-cometkiwi-da"]
    )

    assert code == 0
    assert seen == ["0"]


def test_main_refuses_to_start_offline_without_the_encoder_in_the_cache(
    server_module, monkeypatch, capsys, tmp_path
):
    """COMET builds the encoder from the tokenizer and config hparams.yaml names.

    Offline and never fetched, they failed every chapter with attributeerror
    while the connection check stayed green. Refused up front instead, naming
    the command that fetches them with this very interpreter.
    """
    checkpoints = _downloaded_model(tmp_path)
    _hub_cache(monkeypatch)
    monkeypatch.setattr(server_module, "ScoringHTTPServer", _refuse_to_serve)

    code = server_module.main(
        ["--model-dir", str(checkpoints), "--model", "wmt22-cometkiwi-da"]
    )

    message = capsys.readouterr().err
    assert code == 2
    assert "microsoft/infoxlm-large" in message
    assert sys.executable in message
    assert str(checkpoints / "model.ckpt") in message


# --- the batch file that starts it on the PC ---------------------------------


def test_the_batch_file_reads_as_utf8_and_names_the_checkpoints_directory():
    path = Path(__file__).resolve().parents[2] / "tools" / "start_cometkiwi_server.bat"
    raw = path.read_bytes()

    # cmd reads a .bat in the OEM codepage, so chcp 65001 comes first; a BOM
    # would break the @echo off in front of it; and the file stays CRLF.
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    lines = raw.decode("utf-8").split("\r\n")
    assert lines[:2] == ["@echo off", "chcp 65001 >nul"]
    weights = next(
        index for index, line in enumerate(lines) if line.startswith("set KIWI_WEIGHTS=")
    )
    assert lines[weights - 1] == (
        "rem Каталог, в котором лежит сам файл .ckpt "
        "(у модели с Hugging Face — подкаталог checkpoints)."
    )
    assert lines[weights] == r"set KIWI_WEIGHTS=C:\kiwi\weights\wmt22-cometkiwi-da\checkpoints"
