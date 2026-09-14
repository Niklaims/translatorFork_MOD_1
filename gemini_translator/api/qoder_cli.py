"""Deliver the Qoder CLI to builds that lack it, and only the CLI their SDK expects.

qoder-agent-sdk talks to Qoder by starting ``qodercli``, a platform binary of
about a hundred megabytes that pip places next to the SDK. A frozen build keeps
the SDK's Python code but not that binary, so the first Qoder request of such a
build takes the binary out of the SDK's own wheel on PyPI.

The build, not the network, decides what may run: the frozen app carries the
SDK's RECORD (PyInstaller ``copy_metadata``), and a binary is installed only if
it hashes to exactly what the build machine installed. The wheel is also held
to PyPI's own digest, which separates a download damaged in transit (worth
retrying) from a wrong binary (never installed).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import importlib.metadata
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from ..utils.interprocess_lock import interprocess_lock


QODER_SDK_DISTRIBUTION = "qoder-agent-sdk"
PYPI_INDEX_URL = "https://pypi.org"
# Waiting for another window that is already downloading the wheel is cheaper
# than downloading it twice, even on a slow line.
DEFAULT_LOCK_TIMEOUT_SECONDS = 30 * 60

_BINARY_NAMES = ("qodercli", "qodercli.exe")
_VERIFIED_MARKER = ".verified"
_STAGING_PREFIX = ".staging-"
_LOCK_NAME = ".install.lock"
_VERSION_DIRECTORY = re.compile(r"\d+(?:\.\d+)+(?:[.+-][0-9A-Za-z.]+)?")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_CHUNK_BYTES = 1 << 20
_HTTP_TIMEOUT = (15, 60)
_MISMATCH = "Qoder CLI с PyPI не совпадает с тем, что записано в сборке"


class QoderCliError(RuntimeError):
    """The CLI could not be delivered; ``retryable`` says whether waiting can help."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = bool(retryable)


class QoderCliCancelled(QoderCliError):
    """The request that needed the CLI was cancelled while it was being installed."""

    def __init__(self, message: str = "установка Qoder CLI отменена") -> None:
        super().__init__(message, retryable=True)


@dataclass(frozen=True, slots=True)
class QoderCliPin:
    """The one binary a build accepts: the wheel it comes in, its path there, its hash."""

    distribution: str
    version: str
    wheel_filename: str
    member: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class _Release:
    url: str
    size: int
    sha256: str


def read_pin(distribution=None, *, name: str = QODER_SDK_DISTRIBUTION) -> QoderCliPin:
    """Read the CLI this build's SDK was installed with from the SDK's RECORD."""
    if distribution is None:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise QoderCliError(
                "в сборке нет метаданных qoder-agent-sdk, скачанный Qoder CLI нечем проверить",
                retryable=False,
            ) from error

    project = str(distribution.metadata["Name"] or name)
    version = str(distribution.version or "")
    tags = [
        line.split(":", 1)[1].strip()
        for line in (distribution.read_text("WHEEL") or "").splitlines()
        if line.lower().startswith("tag:")
    ]
    entries = [
        entry
        for entry in (distribution.files or ())
        if entry.parts[:-1] == ("qoder_agent_sdk", "_bundled") and entry.name in _BINARY_NAMES
    ]
    if not version or len(tags) != 1 or len(entries) != 1:
        raise QoderCliError(
            "метаданные qoder-agent-sdk не описывают один Qoder CLI для этой платформы",
            retryable=False,
        )
    entry = entries[0]
    if entry.hash is None or entry.hash.mode != "sha256" or not entry.size:
        raise QoderCliError("в RECORD qoder-agent-sdk нет хеша Qoder CLI", retryable=False)

    encoded = entry.hash.value
    try:
        raw_digest = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except ValueError as error:
        raise QoderCliError("хеш Qoder CLI в RECORD qoder-agent-sdk повреждён", retryable=False) from error
    if len(raw_digest) != hashlib.sha256().digest_size:
        raise QoderCliError("хеш Qoder CLI в RECORD qoder-agent-sdk повреждён", retryable=False)
    wheel_project = re.sub(r"[-_.]+", "_", project).lower()
    return QoderCliPin(
        distribution=project,
        version=version,
        wheel_filename=f"{wheel_project}-{version}-{tags[0]}.whl",
        member=entry.as_posix(),
        sha256=raw_digest.hex(),
        size=int(entry.size),
    )


def default_root() -> Path:
    """The per-user data directory the app already uses, next to its updater."""
    from ..utils.update_installer import staging_root

    return staging_root().parent / "qoder-cli"


class QoderCliInstaller:
    """Own one directory of downloaded CLIs: a CLI there is verified or absent."""

    def __init__(
        self,
        pin: QoderCliPin,
        root,
        *,
        fetch_json,
        download,
        index_url: str = PYPI_INDEX_URL,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.pin = pin
        self.root = Path(root)
        self._fetch_json = fetch_json
        self._download = download
        self._index_url = str(index_url).rstrip("/")
        self._lock_timeout = lock_timeout

    @property
    def cli_path(self) -> Path:
        return self.root / self.pin.version / Path(self.pin.member).name

    def installed(self) -> bool:
        """Tell whether the pinned CLI is in place, without hashing 100 MB again."""
        path = self.cli_path
        try:
            if path.stat().st_size != self.pin.size:
                return False
            marker = (path.parent / _VERIFIED_MARKER).read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return False
        return marker == self.pin.sha256

    def ensure(self, cancel=None) -> Path:
        """Return the pinned CLI, installing it first if no window has done so yet."""
        if self.installed():
            return self.cli_path
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise QoderCliError(f"не удалось создать {self.root}: {error}", retryable=False) from error

        # Without the lock (timeout, or a file system without locks) the install
        # is still safe: staging is private and the final rename is atomic.
        with interprocess_lock(self.root / _LOCK_NAME, timeout=self._lock_timeout) as locked:
            if self.installed():
                return self.cli_path
            if locked:
                self._remove_abandoned_staging()
            self._install(cancel)
            if locked:
                self._remove_other_versions()
        return self.cli_path

    def _install(self, cancel) -> None:
        _raise_if_cancelled(cancel)
        release = self._release()
        staging = None
        try:
            staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=str(self.root)))
            wheel = staging / self.pin.wheel_filename
            _raise_if_cancelled(cancel)
            try:
                self._download(release.url, wheel, release.size, cancel)
            except QoderCliError:
                raise
            except Exception as error:  # noqa: BLE001 - any transport failure is retryable
                raise QoderCliError(
                    f"не удалось скачать {self.pin.wheel_filename}: {error}", retryable=True
                ) from error
            _raise_if_cancelled(cancel)
            if _file_sha256(wheel, limit=release.size) != release.sha256:
                raise QoderCliError(
                    f"{self.pin.wheel_filename} повреждён при скачивании", retryable=True
                )

            binary = staging / Path(self.pin.member).name
            self._extract_verified(wheel, binary)
            if os.name != "nt":
                binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            target_dir = self.cli_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            marker = target_dir / _VERIFIED_MARKER
            marker.unlink(missing_ok=True)
            os.replace(binary, self.cli_path)
            marker.write_text(self.pin.sha256, encoding="ascii")
        except OSError as error:
            raise QoderCliError(f"не удалось установить Qoder CLI: {error}", retryable=True) from error
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    def _release(self) -> _Release:
        url = f"{self._index_url}/pypi/{self.pin.distribution}/{self.pin.version}/json"
        try:
            document = self._fetch_json(url)
        except QoderCliError:
            raise
        except Exception as error:  # noqa: BLE001 - network, TLS, proxy or JSON failure
            raise QoderCliError(
                f"PyPI не ответил о {self.pin.distribution} {self.pin.version}: {error}",
                retryable=True,
            ) from error

        files = document.get("urls") if isinstance(document, dict) else None
        for item in files or ():
            if not isinstance(item, dict) or item.get("filename") != self.pin.wheel_filename:
                continue
            digests = item.get("digests") if isinstance(item.get("digests"), dict) else {}
            sha256 = str(digests.get("sha256") or "").lower()
            size = item.get("size")
            download_url = item.get("url")
            if (
                isinstance(download_url, str)
                and download_url
                and isinstance(size, int)
                and not isinstance(size, bool)
                and size > 0
                and _SHA256_HEX.fullmatch(sha256)
            ):
                return _Release(download_url, size, sha256)
            raise QoderCliError(f"PyPI описал {self.pin.wheel_filename} неполно", retryable=True)
        raise QoderCliError(
            f"на PyPI нет {self.pin.wheel_filename} для этой платформы", retryable=False
        )

    def _extract_verified(self, wheel: Path, binary: Path) -> None:
        digest = hashlib.sha256()
        try:
            with zipfile.ZipFile(wheel) as archive:
                try:
                    info = archive.getinfo(self.pin.member)
                except KeyError:
                    raise QoderCliError(
                        f"в {self.pin.wheel_filename} нет {self.pin.member}", retryable=False
                    ) from None
                if info.file_size != self.pin.size:
                    raise QoderCliError(_MISMATCH, retryable=False)
                written = 0
                with archive.open(info) as source, open(binary, "wb") as target:
                    while chunk := source.read(_CHUNK_BYTES):
                        written += len(chunk)
                        if written > self.pin.size:
                            raise QoderCliError(_MISMATCH, retryable=False)
                        digest.update(chunk)
                        target.write(chunk)
        except zipfile.BadZipFile as error:
            raise QoderCliError(f"{self.pin.wheel_filename} повреждён", retryable=True) from error
        if digest.hexdigest() != self.pin.sha256:
            raise QoderCliError(_MISMATCH, retryable=False)

    def _children(self) -> list[Path]:
        """Entries for best-effort cleanup; a root that cannot be listed skips it."""
        try:
            return list(self.root.iterdir())
        except OSError:
            return []

    def _remove_abandoned_staging(self) -> None:
        for child in self._children():
            if child.is_dir() and child.name.startswith(_STAGING_PREFIX):
                shutil.rmtree(child, ignore_errors=True)

    def _remove_other_versions(self) -> None:
        for child in self._children():
            if (
                child.is_dir()
                and child.name != self.pin.version
                and _VERSION_DIRECTORY.fullmatch(child.name)
            ):
                shutil.rmtree(child, ignore_errors=True)


class _RequestsTransport:
    """The two HTTP calls an install makes, through the app's proxy and CA bundle."""

    def __init__(self, proxy_url=None) -> None:
        self._proxies = None
        if proxy_url:
            url = str(proxy_url)
            if url.startswith("socks5://"):
                # Resolve PyPI through the proxy too, as the rest of the app does.
                url = "socks5h://" + url[len("socks5://"):]
            self._proxies = {"http": url, "https": url}

    def _session(self):
        import requests

        from .base import _get_ssl_context_signature

        session = requests.Session()
        # A system proxy must not silently take over, as in the updater.
        session.trust_env = False
        _kind, first, second = _get_ssl_context_signature()
        session.verify = first or second
        if self._proxies:
            session.proxies = dict(self._proxies)
        return session

    def fetch_json(self, url):
        with self._session() as session, session.get(url, timeout=_HTTP_TIMEOUT) as response:
            if response.status_code == 404:
                raise QoderCliError(f"PyPI не знает {url}", retryable=False)
            if response.status_code != 200:
                raise QoderCliError(f"PyPI ответил HTTP {response.status_code}", retryable=True)
            return response.json()

    def download(self, url, destination, expected_size, cancel):
        with self._session() as session, session.get(
            url, stream=True, timeout=_HTTP_TIMEOUT
        ) as response:
            if response.status_code != 200:
                raise QoderCliError(
                    f"PyPI ответил HTTP {response.status_code} на скачивание", retryable=True
                )
            written = 0
            with open(destination, "wb") as target:
                for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                    _raise_if_cancelled(cancel)
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > expected_size:
                        raise QoderCliError("PyPI отдал больше данных, чем объявил", retryable=True)
                    target.write(chunk)


def build_installer(
    pin: QoderCliPin | None = None,
    root=None,
    *,
    proxy_url=None,
    index_url: str = PYPI_INDEX_URL,
) -> QoderCliInstaller:
    """An installer for this build's SDK, talking to PyPI through the app's proxy."""
    transport = _RequestsTransport(proxy_url)
    return QoderCliInstaller(
        pin if pin is not None else read_pin(),
        Path(root) if root is not None else default_root(),
        fetch_json=transport.fetch_json,
        download=transport.download,
        index_url=index_url,
    )


def _raise_if_cancelled(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise QoderCliCancelled()


def _file_sha256(path: Path, *, limit: int) -> str | None:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as source:
        while chunk := source.read(_CHUNK_BYTES):
            total += len(chunk)
            if total > limit:
                return None
            digest.update(chunk)
    return digest.hexdigest()
