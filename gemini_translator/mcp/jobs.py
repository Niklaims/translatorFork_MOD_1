from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import threading

from ..utils.io_utils import atomic_write_text
from ._json_io import load_task_json
from .paths import ensure_state_dirs, job_dir

TEXT_FIELD_HINTS = ("text", "prompt", "chapter", "response", "content")
SECRET_FIELD_HINTS = ("api_key", "api-key", "token", "secret", "password")
SECRET_ARG_OPTIONS = {"--api-key", "--token", "--password"}

# perf:cpu-idle-background/3: кэш РАЗОБРАННОГО СЛОВАРЯ job.json по пути файла,
# чтобы list_jobs() не перечитывал и не парсил JSON давно завершённых задач,
# которые больше никогда не меняются, на каждый опрос /status. Кэшируется
# именно dict (то, что вернул json.loads), а не JobRecord: JobRecord —
# изменяемый объект, который боевой код (_pipeline_allows_start ->
# mark_finished) правит на месте ДО save_job, и если бы кэш раздавал один и
# тот же инстанс всем вызовам list_jobs(), такая мутация была бы видна всем
# потребителям немедленно, а при сбое save_job — навсегда разошлась бы с
# диском. JobRecord.from_dict() строится заново на каждый вызов list_jobs(),
# так что вызывающий код всегда получает приватную, свежую запись; кэшу
# принадлежит только дорогая часть — read_text()+json.loads().
# Ключ — путь к job.json (str от Path.resolve(), не зависит от того, был ли
# state_dir относительным); значение — ((mtime_ns, size) на момент чтения,
# разобранный dict). Файл перечитывается заново, только когда mtime ИЛИ
# размер реально изменились (пара, а не один mtime_ns — защита от «racily
# clean» на файловых системах с грубым разрешением времени, где два
# перезаписанных статуса задачи могут попасть в один и тот же тик часов).
_LIST_JOBS_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}
_LIST_JOBS_CACHE_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_id(prefix: str = "job") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{stamp}_{secrets.token_hex(4)}"


@dataclass
class JobRecord:
    id: str
    type: str
    status: str
    created_at: str
    argv: list[str]
    project: str | None = None
    epub: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    result_path: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    command_path: str = ""
    error: str | None = None
    children: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "JobRecord":
        return cls(
            id=str(payload["id"]),
            type=str(payload["type"]),
            status=str(payload["status"]),
            created_at=str(payload["created_at"]),
            argv=[str(item) for item in payload.get("argv", [])],
            project=payload.get("project"),
            epub=payload.get("epub"),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            pid=payload.get("pid"),
            exit_code=payload.get("exit_code"),
            result_path=str(payload.get("result_path", "")),
            stdout_path=str(payload.get("stdout_path", "")),
            stderr_path=str(payload.get("stderr_path", "")),
            command_path=str(payload.get("command_path", "")),
            error=payload.get("error"),
            children=[str(item) for item in payload.get("children", [])],
            metadata=dict(payload.get("metadata") or {}),
        )


def create_job(
    state_dir: Path,
    job_type: str,
    argv: list[str],
    *,
    project: str | None,
    epub: str | None,
    metadata: dict | None = None,
    children: list[str] | None = None,
) -> JobRecord:
    ensure_state_dirs(state_dir)
    job_id = new_job_id(job_type)
    directory = job_dir(state_dir, job_id)
    directory.mkdir(parents=True, exist_ok=False)
    job = JobRecord(
        id=job_id,
        type=job_type,
        status="queued",
        created_at=utc_now(),
        argv=list(argv),
        project=project,
        epub=epub,
        result_path=str(directory / "result.json"),
        stdout_path=str(directory / "stdout.log"),
        stderr_path=str(directory / "stderr.log"),
        command_path=str(directory / "command.json"),
        metadata=dict(metadata or {}),
        children=list(children or []),
    )
    save_job(state_dir, job)
    Path(job.command_path).write_text(json.dumps({"argv": job.argv}, ensure_ascii=False, indent=2), encoding="utf-8")
    return job


def job_path(state_dir: Path, job_id: str) -> Path:
    return job_dir(state_dir, job_id) / "job.json"


def save_job(state_dir: Path, job: JobRecord) -> None:
    directory = job_dir(state_dir, job.id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(job.to_dict(), ensure_ascii=False, indent=2)
    # dups-gt_mcp_ai_bridge-53: общий атомарный хелпер (уникальный temp-файл,
    # fsync, подчистка) вместо собственной temp+replace копии.
    atomic_write_text(directory / "job.json", payload)


def load_job(state_dir: Path, job_id: str) -> JobRecord:
    return load_task_json(job_path(state_dir, job_id), JobRecord.from_dict)


def list_jobs(state_dir: Path) -> list[JobRecord]:
    root = state_dir / "jobs"
    if not root.exists():
        return []
    jobs = []
    seen_keys: set[str] = set()
    for path in sorted(root.glob("*/job.json")):
        cache_key = str(path.resolve())
        seen_keys.add(cache_key)
        stat_result = path.stat()
        stat_key = (stat_result.st_mtime_ns, stat_result.st_size)
        with _LIST_JOBS_CACHE_LOCK:
            cached = _LIST_JOBS_CACHE.get(cache_key)
        if cached is not None and cached[0] == stat_key:
            payload = cached[1]
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            with _LIST_JOBS_CACHE_LOCK:
                _LIST_JOBS_CACHE[cache_key] = (stat_key, payload)
        # Каждый вызов строит свою собственную JobRecord из кэшированного
        # dict: from_dict копирует argv/children/metadata, поэтому мутация
        # записи, которую делает вызывающий код (например, mark_finished
        # в _pipeline_allows_start ДО save_job), не отравляет кэш и не видна
        # другим потокам/вызовам.
        jobs.append(JobRecord.from_dict(payload))
    with _LIST_JOBS_CACHE_LOCK:
        # Задачи, чей job.json больше не существует (директория удалена),
        # не должны держать память бессрочно, пока живёт демон.
        stale_keys = [key for key in _LIST_JOBS_CACHE if key not in seen_keys]
        for key in stale_keys:
            del _LIST_JOBS_CACHE[key]
    return sorted(jobs, key=lambda item: item.created_at, reverse=True)


def mark_running(job: JobRecord, *, pid: int) -> None:
    job.status = "running"
    job.pid = pid
    job.started_at = utc_now()
    job.error = None


def mark_finished(job: JobRecord, *, status: str, exit_code: int | None, error: str | None = None) -> None:
    job.status = status
    job.exit_code = exit_code
    job.finished_at = utc_now()
    job.error = error
    job.pid = None


def _is_secret_key(key: str) -> bool:
    lowered = key.replace("_", "-").lower()
    return any(hint in lowered for hint in SECRET_FIELD_HINTS)


def _is_large_text_key(key: str) -> bool:
    lowered = key.replace("_", "-").lower()
    return any(hint in lowered for hint in TEXT_FIELD_HINTS)


def _redact_argv(argv: list[str]) -> list[str]:
    redacted = []
    skip_next = False
    for item in argv:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        option, separator, _value = item.partition("=")
        if separator and option in SECRET_ARG_OPTIONS:
            redacted.append(f"{option}=<redacted>")
            continue
        redacted.append(item)
        if item in SECRET_ARG_OPTIONS:
            skip_next = True
    return redacted


def redact_for_mcp(payload):
    if isinstance(payload, JobRecord):
        payload = payload.to_dict()
    if isinstance(payload, dict):
        result = {}
        for key, value in payload.items():
            if _is_secret_key(str(key)):
                result[key] = "<redacted>"
            elif _is_large_text_key(str(key)):
                result[key] = "<omitted>"
            elif key == "argv" and isinstance(value, list):
                result[key] = _redact_argv([str(item) for item in value])
            else:
                result[key] = redact_for_mcp(value)
        return result
    if isinstance(payload, list):
        return [redact_for_mcp(item) for item in payload]
    return payload


def tail_log(path: Path | str, *, limit: int = 20) -> list[str]:
    log_path = Path(path)
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max(0, int(limit)) :]
