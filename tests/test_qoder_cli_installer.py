"""How a frozen build gets the Qoder CLI its SDK expects, and only that CLI.

The SDK runs a ~100 MB binary that the release spec never shipped. The build
keeps the SDK's RECORD instead, so the binary downloaded later from PyPI can be
held to the exact hash the build machine installed.
"""

import hashlib
import http.server
import io
import json
import os
import stat
import threading
import time
import zipfile
from importlib.metadata import PathDistribution
from pathlib import Path

import pytest

from gemini_translator.api import qoder_cli
from gemini_translator.api.qoder_cli import (
    QoderCliCancelled,
    QoderCliError,
    QoderCliInstaller,
    QoderCliPin,
    read_pin,
)


CLI_BYTES = b"fake qodercli binary v1\n"
CLI_SHA256 = "2c45b63ea4798820a5fa7278f2fe9a0c825b355889e84361d105d01ab80c5114"
CLI_RECORD_HASH = "LEW2PqR5iCCl-nJ48v6aDIJbNViJ6ENh0QXQGrgMURQ"
SAME_SIZE_TAMPERED_BYTES = b"fake qodercli binary v2\n"
WHEEL_NAME = "qoder_agent_sdk-1.0.14-py3-none-macosx_11_0_arm64.whl"
MEMBER = "qoder_agent_sdk/_bundled/qodercli"
JSON_PATH = "/pypi/qoder-agent-sdk/1.0.14/json"


def _pin(**changes):
    values = dict(
        distribution="qoder-agent-sdk",
        version="1.0.14",
        wheel_filename=WHEEL_NAME,
        member=MEMBER,
        sha256=CLI_SHA256,
        size=24,
    )
    values.update(changes)
    return QoderCliPin(**values)


def _dist_info(
    tmp_path, *, member=MEMBER, tag="py3-none-macosx_11_0_arm64", record_hash=CLI_RECORD_HASH
):
    info = tmp_path / "site" / "qoder_agent_sdk-1.0.14.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: qoder-agent-sdk\nVersion: 1.0.14\n",
        encoding="utf-8",
    )
    (info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nGenerator: hatchling 1.32.0\n"
        f"Root-Is-Purelib: true\nTag: {tag}\n",
        encoding="utf-8",
    )
    (info / "RECORD").write_text(
        "qoder_agent_sdk/__init__.py,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0\n"
        f"{member},sha256={record_hash},24\n"
        "qoder_agent_sdk-1.0.14.dist-info/RECORD,,\n",
        encoding="utf-8",
    )
    return PathDistribution(info)


def _wheel_bytes(cli_bytes, member=MEMBER):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("qoder_agent_sdk/__init__.py", "")
        archive.writestr(member, cli_bytes)
    return buffer.getvalue()


def _leftovers(root):
    """Everything an install left on disk, apart from the lock and the result."""
    if not root.exists():
        return []
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(".lock")
    )


class FakeIndex:
    """PyPI as the installer sees it: one release document and one wheel."""

    def __init__(self, cli_bytes=CLI_BYTES, *, digest=None, filename=WHEEL_NAME):
        self.wheel = _wheel_bytes(cli_bytes)
        self.document = {
            "urls": [
                {
                    "filename": filename,
                    "packagetype": "bdist_wheel",
                    "url": f"https://files.example/{filename}",
                    "size": len(self.wheel),
                    "digests": {"sha256": digest or hashlib.sha256(self.wheel).hexdigest()},
                }
            ]
        }
        self.json_requests = []
        self.downloads = []

    def fetch_json(self, url):
        self.json_requests.append(url)
        return self.document

    def download(self, url, destination, expected_size, cancel):
        self.downloads.append(url)
        Path(destination).write_bytes(self.wheel)

    def installer(self, root, **kwargs):
        return QoderCliInstaller(
            _pin(),
            root,
            fetch_json=self.fetch_json,
            download=kwargs.pop("download", self.download),
            **kwargs,
        )


def test_pin_is_the_binary_recorded_by_the_installed_sdk(tmp_path):
    assert read_pin(_dist_info(tmp_path)) == _pin()


def test_windows_pin_names_the_executable_and_its_wheel(tmp_path):
    pin = read_pin(
        _dist_info(
            tmp_path,
            member="qoder_agent_sdk/_bundled/qodercli.exe",
            tag="py3-none-win_amd64",
        )
    )

    assert pin.member == "qoder_agent_sdk/_bundled/qodercli.exe"
    assert pin.wheel_filename == "qoder_agent_sdk-1.0.14-py3-none-win_amd64.whl"


def test_build_without_sdk_metadata_cannot_pin_a_cli():
    with pytest.raises(QoderCliError) as raised:
        read_pin(name="qoder-agent-sdk-that-is-not-installed")

    assert raised.value.retryable is False


def test_record_with_a_malformed_hash_cannot_pin_a_cli(tmp_path):
    with pytest.raises(QoderCliError) as raised:
        read_pin(_dist_info(tmp_path, record_hash="AAAAAAA"))

    assert raised.value.retryable is False


def test_installs_the_recorded_binary_where_the_handler_will_run_it(tmp_path):
    index = FakeIndex()

    path = index.installer(tmp_path / "cli").ensure()

    assert path == tmp_path / "cli" / "1.0.14" / "qodercli"
    assert path.read_bytes() == CLI_BYTES
    assert index.json_requests == ["https://pypi.org/pypi/qoder-agent-sdk/1.0.14/json"]
    assert index.downloads == [f"https://files.example/{WHEEL_NAME}"]
    if os.name != "nt":
        assert path.stat().st_mode & stat.S_IXUSR


def test_installed_cli_is_not_downloaded_again(tmp_path):
    index = FakeIndex()
    index.installer(tmp_path / "cli").ensure()

    another_process = index.installer(tmp_path / "cli")

    assert another_process.installed() is True
    assert another_process.ensure() == tmp_path / "cli" / "1.0.14" / "qodercli"
    assert len(index.downloads) == 1


def test_unverified_file_left_in_place_is_replaced_by_the_verified_cli(tmp_path):
    root = tmp_path / "cli"
    leftover = root / "1.0.14" / "qodercli"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(SAME_SIZE_TAMPERED_BYTES)
    index = FakeIndex()
    installer = index.installer(root)

    assert installer.installed() is False
    assert installer.ensure().read_bytes() == CLI_BYTES
    assert len(index.downloads) == 1


def test_binary_other_than_the_recorded_one_is_never_installed(tmp_path):
    installer = FakeIndex(SAME_SIZE_TAMPERED_BYTES).installer(tmp_path / "cli")

    with pytest.raises(QoderCliError) as raised:
        installer.ensure()

    assert raised.value.retryable is False
    assert installer.installed() is False
    assert _leftovers(tmp_path / "cli") == []


def test_wheel_corrupted_in_transit_is_retried_later(tmp_path):
    installer = FakeIndex(digest="0" * 64).installer(tmp_path / "cli")

    with pytest.raises(QoderCliError) as raised:
        installer.ensure()

    assert raised.value.retryable is True
    assert _leftovers(tmp_path / "cli") == []


def test_platform_without_a_published_wheel_is_reported_without_downloading(tmp_path):
    index = FakeIndex(filename="qoder_agent_sdk-1.0.14-py3-none-win_amd64.whl")

    with pytest.raises(QoderCliError) as raised:
        index.installer(tmp_path / "cli").ensure()

    assert raised.value.retryable is False
    assert index.downloads == []


def test_network_failure_is_retryable_and_leaves_nothing_behind(tmp_path):
    def broken_download(url, destination, expected_size, cancel):
        Path(destination).write_bytes(b"partial")
        raise OSError("connection reset by peer")

    installer = FakeIndex().installer(tmp_path / "cli", download=broken_download)

    with pytest.raises(QoderCliError) as raised:
        installer.ensure()

    assert raised.value.retryable is True
    assert _leftovers(tmp_path / "cli") == []


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="directory permissions are checked on POSIX only",
)
def test_unwritable_cli_directory_is_reported_instead_of_crashing(tmp_path):
    root = tmp_path / "cli"
    root.mkdir()
    root.chmod(0o500)
    try:
        with pytest.raises(QoderCliError):
            FakeIndex().installer(root, lock_timeout=0.1).ensure()
    finally:
        root.chmod(0o700)


def test_cancelled_install_leaves_nothing_behind(tmp_path):
    cancel = threading.Event()
    cancel.set()
    installer = FakeIndex().installer(tmp_path / "cli")

    with pytest.raises(QoderCliCancelled):
        installer.ensure(cancel)

    assert installer.installed() is False
    assert _leftovers(tmp_path / "cli") == []


def test_previous_cli_versions_are_removed_after_install(tmp_path):
    root = tmp_path / "cli"
    (root / "1.0.13").mkdir(parents=True)
    (root / "1.0.13" / "qodercli").write_bytes(b"old cli")
    (root / "notes.txt").write_text("keep me", encoding="utf-8")

    FakeIndex().installer(root).ensure()

    assert not (root / "1.0.13").exists()
    assert (root / "notes.txt").read_text(encoding="utf-8") == "keep me"


def test_parallel_workers_share_one_download(tmp_path):
    index = FakeIndex()
    root = tmp_path / "cli"

    def slow_download(url, destination, expected_size, cancel):
        time.sleep(0.2)
        index.download(url, destination, expected_size, cancel)

    results, errors = [], []

    def worker():
        try:
            results.append(index.installer(root, download=slow_download).ensure())
        except Exception as error:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert results == [root / "1.0.14" / "qodercli"] * 3
    assert len(index.downloads) == 1


class _IndexHandler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802 - http.server naming
        body = self.routes.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client stopped reading on purpose, which is what a test checks

    def log_message(self, *args):
        pass


@pytest.fixture
def package_index():
    routes = {}
    handler = type("Handler", (_IndexHandler,), {"routes": routes})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", routes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _publish(routes, base_url, wheel, *, served=None):
    routes[f"/files/{WHEEL_NAME}"] = served if served is not None else wheel
    routes[JSON_PATH] = json.dumps(
        {
            "urls": [
                {
                    "filename": WHEEL_NAME,
                    "packagetype": "bdist_wheel",
                    "url": f"{base_url}/files/{WHEEL_NAME}",
                    "size": len(wheel),
                    "digests": {"sha256": hashlib.sha256(wheel).hexdigest()},
                }
            ]
        }
    ).encode("utf-8")


def test_installs_from_a_package_index_over_http(tmp_path, package_index):
    base_url, routes = package_index
    _publish(routes, base_url, _wheel_bytes(CLI_BYTES))

    installer = qoder_cli.build_installer(_pin(), tmp_path / "cli", index_url=base_url)

    assert installer.ensure().read_bytes() == CLI_BYTES


def test_download_longer_than_the_index_announced_is_abandoned(tmp_path, package_index):
    base_url, routes = package_index
    wheel = _wheel_bytes(CLI_BYTES)
    _publish(routes, base_url, wheel, served=wheel + b"\0" * 65536)

    installer = qoder_cli.build_installer(_pin(), tmp_path / "cli", index_url=base_url)

    with pytest.raises(QoderCliError) as raised:
        installer.ensure()

    assert raised.value.retryable is True
    assert _leftovers(tmp_path / "cli") == []


def test_http_download_stops_writing_once_it_passes_the_announced_size(tmp_path, package_index):
    base_url, routes = package_index
    routes["/files/big.whl"] = b"\0" * (3 * 1024 * 1024)
    destination = tmp_path / "big.whl"

    with pytest.raises(QoderCliError) as raised:
        qoder_cli._RequestsTransport().download(f"{base_url}/files/big.whl", destination, 1024, None)

    assert raised.value.retryable is True
    assert destination.stat().st_size <= 1024


def test_http_download_stops_when_the_request_is_cancelled(tmp_path, package_index):
    base_url, routes = package_index
    routes["/files/cli.whl"] = b"\0" * 4096
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(QoderCliCancelled):
        qoder_cli._RequestsTransport().download(
            f"{base_url}/files/cli.whl", tmp_path / "cli.whl", 4096, cancel
        )

