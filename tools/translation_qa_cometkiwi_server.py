#!/usr/bin/env python3
"""Answer COMETKiwi scoring requests over the local network, from one process.

This script is deliberately not part of the application package: like the
console runner beside it, it is meant to run under an interpreter where PyTorch
and ``unbabel-comet`` are installed, on the machine that owns the GPU.

It speaks the same protocol as ``translation_qa_cometkiwi_runner.py``, schema
version 1, over HTTP:

    POST /score    one request object in, one answer object out
    GET  /health   the model, the device, and whether the weights are loaded

Two rules make it safe enough to listen on a home network.  The weights
directory and the device come from this command line and the ``model_dir`` and
``device`` of an incoming request are ignored: otherwise anyone who can reach
the port could make this process load an arbitrary checkpoint file.  And the
text of a chapter never reaches a log or an answer: failures are named by short
identifiers, exactly as the console runner names them.

There is no authentication.  Run it only on a network you trust, and do not
forward its port through a router.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time


def _runner():
    """Load the console runner beside this file and reuse its validation."""
    path = Path(__file__).resolve().parent / "translation_qa_cometkiwi_runner.py"
    spec = importlib.util.spec_from_file_location("cometkiwi_runner", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cometkiwi_runner"] = module
    spec.loader.exec_module(module)
    return module


_RUNNER = _runner()
SCHEMA_VERSION = _RUNNER.SCHEMA_VERSION
MAX_SEGMENTS = _RUNNER.MAX_SEGMENTS
MAX_REQUEST_BYTES = _RUNNER.MAX_REQUEST_BYTES
RequestError = _RUNNER.RequestError
DEFAULT_PORT = 8765
# A refusal is answered under the request's own id when that id is a string no
# longer than this, even before the rest of the request has been validated.
MAX_ECHOED_REQUEST_ID_CHARS = 128
# The method and the path of a request line are the client's own text, and
# none of it reaches the terminal: a known method and a route this server
# serves are named in the log, anything else is written as "?".
_LOGGED_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"}
)
_LOGGED_ROUTES = frozenset({"/score", "/health"})


def validate_payload(payload: object) -> dict:
    """Apply every rule the console runner applies, except the local path one.

    ``read_request`` ends by requiring the request's own ``model_dir`` to exist
    on disk.  Over a network that field is not ours to trust and not ours to
    honour, so it is neither checked nor used.
    """
    if not isinstance(payload, dict):
        raise RequestError("invalid_request")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RequestError("unsupported_schema_version")
    for field in ("request_id", "model"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RequestError("invalid_request")
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise RequestError("invalid_request")
    if len(segments) > MAX_SEGMENTS:
        raise RequestError("too_many_segments")
    for segment in segments:
        if not isinstance(segment, dict):
            raise RequestError("invalid_request")
        if set(segment) - {"source", "translation"}:
            raise RequestError("unexpected_segment_field")
        for field in ("source", "translation"):
            if not isinstance(segment.get(field), str) or not segment[field].strip():
                raise RequestError("invalid_request")
    return payload


class ScoringService:
    """Hold one loaded model and answer one request at a time."""

    def __init__(self, model_dir: str, device: str, model: str, loader=None) -> None:
        self._model_dir = str(model_dir)
        self._device = str(device or "cpu")
        self._model_name = str(model)
        self._loader = loader or _RUNNER.load_model
        self._model = None
        # One GPU cannot usefully run two batches at once, and serialising here
        # is what keeps the memory it needs predictable.
        self._lock = threading.Lock()

    def health(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "model": self._model_name,
            "device": self._device,
            "loaded": self._model is not None,
        }

    def handle(self, payload: object) -> dict:
        # Taken before validation, so that a refusal is still answered under
        # the request's own id: the client compares ids before it reads an
        # error, and an empty id turned a Mac and a PC on different schema
        # versions into request_id_mismatch instead of the reason itself.
        request_id = _echoable_request_id(payload)
        try:
            request = validate_payload(payload)
            request_id = request["request_id"]
            started = time.monotonic()
            with self._lock:
                if self._model is None:
                    self._model = self._loader(self._model_dir)
                scores = _RUNNER.score_with(
                    self._model, {**request, "device": self._device}
                )
            if len(scores) != len(request["segments"]):
                raise RequestError("score_count_mismatch")
            answer = {
                "schema_version": SCHEMA_VERSION,
                "request_id": request_id,
                "model": self._model_name,
                "device": self._device,
                "scores": scores,
                "runtime_seconds": round(time.monotonic() - started, 3),
            }
            asked = request.get("model")
            if isinstance(asked, str) and asked != self._model_name:
                answer["model_mismatch"] = asked
            return answer
        except RequestError as error:
            return _failure(request_id, str(error))
        except MemoryError:
            return _failure(request_id, "out_of_memory")
        except ImportError:
            return _failure(request_id, "runner_environment_incomplete")
        except Exception as error:  # noqa: BLE001 - the caller sees only a reason
            if type(error).__name__ == "OutOfMemoryError":
                # torch.OutOfMemoryError, a CUDA allocation that failed,
                # subclasses RuntimeError rather than MemoryError. It is matched
                # by name so that this process never imports torch to know it.
                return _failure(request_id, "out_of_memory")
            return _failure(request_id, type(error).__name__.lower())


def _failure(request_id: str, reason: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "error": reason,
    }


def _echoable_request_id(payload: object) -> str:
    """The request's own id if it is a short string, read before any validation."""
    if not isinstance(payload, dict):
        return ""
    value = payload.get("request_id")
    if isinstance(value, str) and 1 <= len(value) <= MAX_ECHOED_REQUEST_ID_CHARS:
        return value
    return ""


def build_handler(service: ScoringService):
    """Return a handler bound to one service, with no logging of request bodies."""

    class _Handler(BaseHTTPRequestHandler):
        server_version = "CometKiwiQA/1"
        # Set on each connection's socket by StreamRequestHandler.setup().
        # Without it a client that vanishes halfway through its body leaves
        # this thread blocked in rfile.read() for good. It bounds one read or
        # one write, not a request: scoring touches no socket while it runs,
        # so a long batch on the GPU is not cut short by it.
        timeout = 60
        _responded = False

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
            self._responded = False
            try:
                if self.path.rstrip("/") != "/health":
                    self._send(404, {"error": "not_found"})
                    return
                self._send(200, service.health())
            except Exception:  # noqa: BLE001 - the transport-layer backstop below
                self._fail_safely()

        def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's spelling
            self._responded = False
            try:
                if self.path.rstrip("/") != "/score":
                    self._send(404, {"error": "not_found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send(400, {"error": "invalid_request"})
                    return
                if length < 0:
                    # int("-1") parses fine, and rfile.read(-1) reads until EOF -
                    # a negative length is malformed, not merely "too large",
                    # so it gets the same answer as any other unparsable value.
                    self._send(400, {"error": "invalid_request"})
                    return
                if length > MAX_REQUEST_BYTES:
                    self._send(413, {"error": "request_too_large"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length) or b"")
                except ValueError:
                    self._send(400, {"error": "invalid_request"})
                    return
                self._send(200, service.handle(payload))
            except Exception:  # noqa: BLE001 - the transport-layer backstop below
                self._fail_safely()

        def _fail_safely(self) -> None:
            """Catch whatever ``ScoringService.handle`` did not.

            That method already turns every exception it sees into a short
            reason with no request content in it, but that is one function's
            discipline, not a structural guarantee against everything
            between the socket and it. Left uncaught, an exception here
            would reach ``socketserver.BaseServer.handle_error``, which
            prints a full traceback and never goes through ``log_message``
            at all. This is the transport-layer backstop: one fixed log
            line and, if nothing has been sent yet, one fixed body -
            regardless of what broke or what the request contained.
            """
            if not self._responded:
                try:
                    encoded = json.dumps({"error": "server_error"}).encode("utf-8")
                    self.send_response_only(500)
                    self.send_header("Server", self.version_string())
                    self.send_header("Date", self.date_time_string())
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                except Exception:  # noqa: BLE001 - the connection may already be gone
                    pass
            # After the answer, like every line this handler writes: see _send.
            self.log_message("unhandled exception")

        def _send(self, status: int, body: dict) -> None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            # Headers are irreversibly on the wire past this point: a later
            # failure (e.g. the client vanishing mid-write) must not trigger
            # a second send_response() call.
            self._responded = True
            self.wfile.write(encoded)
            # Only now, with the answer on the wire. A Windows console holding
            # a text selection (QuickEdit) blocks every write to it; while this
            # line was written from send_response(), before the headers, that
            # selection held the answer too, and the Mac waited out its whole
            # timeout for a chapter the PC had already scored.
            self._log(str(status))

        def log_request(self, code="-", size="-"):
            # send_response() calls this before anything is sent. The one line
            # per answer is written by _send, after the body instead.
            return

        def log_message(self, fmt, *args):
            # Everything else the stdlib logs arrives here, send_error()'s
            # report on a malformed request line among it: that report comes
            # before any command or path is set, and its args carry the raw
            # request line. So the fixed format string alone, never fmt % args.
            self._log(str(fmt))

        def _log(self, outcome: str) -> None:
            """Write one line: method, route, outcome, and nothing a client wrote.

            The default logs the request line. Nothing of a chapter, and no
            text a client chose, belongs in a terminal left open all day.
            """
            command = getattr(self, "command", None)
            path = getattr(self, "path", None)
            route = path.rstrip("/") if isinstance(path, str) else ""
            method = command if command in _LOGGED_METHODS else "?"
            shown_route = route if route in _LOGGED_ROUTES else "?"
            try:
                sys.stderr.write(f"{method} {shown_route} -> {outcome}\n")
            except Exception:  # noqa: BLE001 - a log line is never worth an answer
                pass

    return _Handler


class ScoringHTTPServer(ThreadingHTTPServer):
    """The server ``main`` runs: a thread per request, and one instance per port."""

    def __init__(self, server_address, handler_class, bind_and_activate=True):
        # HTTPServer turns SO_REUSEADDR on. Elsewhere that only lets a restarted
        # server rebind a port still in TIME_WAIT; on Windows it lets a second
        # process bind a port that is already listening, so an autostarted
        # server and a manual launch would both come up and both load the
        # model into the same card's memory. Decided per instance, and before
        # super().__init__() binds the socket.
        self.allow_reuse_address = sys.platform != "win32"
        super().__init__(server_address, handler_class, bind_and_activate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, help="каталог с весами")
    parser.add_argument("--model", required=True, help="имя модели для журнала")
    parser.add_argument("--device", default="cuda", choices=("cpu", "cuda"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    if not Path(args.model_dir).is_dir():
        sys.stderr.write(f"Каталог весов не найден: {args.model_dir}\n")
        return 2
    try:
        # The lookup load_model() makes on the first request, made up front:
        # a directory it finds no checkpoint in would otherwise start a server
        # that passes the connection check and then fails every chapter.
        _RUNNER._checkpoint_path(Path(args.model_dir))
    except RequestError:
        sys.stderr.write(
            f"В каталоге весов нет файла .ckpt: {args.model_dir}\n"
            "Укажите каталог, в котором лежит сам .ckpt — у модели, скачанной "
            "с Hugging Face, это подкаталог checkpoints. Остальные файлы модели "
            "не перемещайте.\n"
        )
        return 2

    service = ScoringService(args.model_dir, args.device, args.model)
    server = ScoringHTTPServer((args.host, args.port), build_handler(service))
    sys.stderr.write(
        f"COMETKiwi слушает http://{args.host}:{args.port} "
        f"({args.model}, {args.device}). Ctrl+C — остановить.\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
