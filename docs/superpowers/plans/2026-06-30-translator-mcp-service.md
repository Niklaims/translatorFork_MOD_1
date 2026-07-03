# Translator MCP Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standard MCP stdio server backed by a durable local daemon so desktop AI clients can start translatorFork_MOD AI jobs, inspect status, and install client configs without sending full book content back into chat.

**Architecture:** Add a focused `gemini_translator.mcp` package. The MCP stdio process speaks JSON-RPC to AI clients, forwards tool calls to a localhost daemon protected by a per-user token, and the daemon runs existing `gemini_translator.cli` commands as subprocess jobs with persistent state and logs.

**Tech Stack:** Python stdlib only for V1 (`dataclasses`, `json`, `http.server`, `subprocess`, `threading`, `urllib.request`, `argparse`, `pathlib`), existing `gemini_translator.cli`, pytest/unittest-style repo tests.

---

## File Structure

- Create: `gemini_translator/mcp/__init__.py`
  Package marker and exported version string.
- Create: `gemini_translator/mcp/__main__.py`
  CLI entrypoint for `python -m gemini_translator.mcp`.
- Create: `gemini_translator/mcp/paths.py`
  State-directory, log-path, and repository-root helpers.
- Create: `gemini_translator/mcp/jobs.py`
  Job model, persistence, redaction, log tail, and state transition helpers.
- Create: `gemini_translator/mcp/commands.py`
  Validated mapping from MCP tool arguments to `python -m gemini_translator.cli --compact ...` argv lists.
- Create: `gemini_translator/mcp/worker.py`
  Subprocess job runner and best-effort cancellation helpers.
- Create: `gemini_translator/mcp/daemon.py`
  Local loopback daemon, durable queue, worker supervision, and HTTP control API.
- Create: `gemini_translator/mcp/client.py`
  Small daemon client used by the MCP server and CLI lifecycle commands.
- Create: `gemini_translator/mcp/server.py`
  Minimal MCP JSON-RPC stdio server with `initialize`, `tools/list`, `tools/call`, and `ping`.
- Create: `gemini_translator/mcp/client_install.py`
  Config snippet generation, safe backups, and client config writes.
- Create: `tests/test_mcp_jobs.py`
- Create: `tests/test_mcp_commands.py`
- Create: `tests/test_mcp_worker.py`
- Create: `tests/test_mcp_daemon.py`
- Create: `tests/test_mcp_server.py`
- Create: `tests/test_mcp_client_install.py`
- Modify: `README.md`
  Add a short MCP usage section after the CLI/manual launch area.

The future GUI-connected agent bridge from the spec is not implemented in this plan. The code should keep daemon state and APIs reusable so a later GUI page can attach to the same daemon.

---

### Task 1: MCP Package Scaffold And Paths

**Files:**
- Create: `gemini_translator/mcp/__init__.py`
- Create: `gemini_translator/mcp/paths.py`
- Create: `tests/test_mcp_jobs.py`

- [ ] **Step 1: Write failing tests for state paths**

Add this to `tests/test_mcp_jobs.py`:

```python
import os
from pathlib import Path

from gemini_translator.mcp.paths import default_state_dir, job_dir, repo_root


def test_default_state_dir_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSLATOR_MCP_STATE_DIR", str(tmp_path / "state"))

    assert default_state_dir() == tmp_path / "state"


def test_job_dir_lives_under_state_dir(tmp_path):
    assert job_dir(tmp_path, "job_abc") == tmp_path / "jobs" / "job_abc"


def test_repo_root_points_to_checkout():
    root = repo_root()

    assert (root / "gemini_translator").is_dir()
    assert (root / "README.md").is_file()
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_jobs.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gemini_translator.mcp'`.

- [ ] **Step 3: Create the package and path helpers**

Create `gemini_translator/mcp/__init__.py`:

```python
"""Local MCP integration for translatorFork_MOD."""

MCP_PACKAGE_VERSION = "0.1.0"
```

Create `gemini_translator/mcp/paths.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

STATE_DIR_ENV = "TRANSLATOR_MCP_STATE_DIR"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_state_dir() -> Path:
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".translatorFork" / "mcp"


def jobs_dir(state_dir: Path | None = None) -> Path:
    return (state_dir or default_state_dir()) / "jobs"


def job_dir(state_dir: Path, job_id: str) -> Path:
    return state_dir / "jobs" / job_id


def daemon_file(state_dir: Path | None = None) -> Path:
    return (state_dir or default_state_dir()) / "daemon.json"


def daemon_stdout_log(state_dir: Path | None = None) -> Path:
    return (state_dir or default_state_dir()) / "daemon.stdout.log"


def daemon_stderr_log(state_dir: Path | None = None) -> Path:
    return (state_dir or default_state_dir()) / "daemon.stderr.log"


def ensure_state_dirs(state_dir: Path | None = None) -> Path:
    root = state_dir or default_state_dir()
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    return root
```

- [ ] **Step 4: Run the path tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_jobs.py -q
```

Expected: PASS with `3 passed`.

- [ ] **Step 5: Commit**

Run:

```bash
git add gemini_translator/mcp/__init__.py gemini_translator/mcp/paths.py tests/test_mcp_jobs.py
git commit -m "Add MCP path helpers"
```

---

### Task 2: Durable Job Model And Persistence

**Files:**
- Modify: `gemini_translator/mcp/jobs.py`
- Modify: `tests/test_mcp_jobs.py`

- [ ] **Step 1: Extend job tests**

Append this to `tests/test_mcp_jobs.py`:

```python
import json

from gemini_translator.mcp.jobs import (
    JobRecord,
    create_job,
    load_job,
    mark_finished,
    mark_running,
    redact_for_mcp,
    save_job,
    tail_log,
)


def test_create_save_load_job_roundtrip(tmp_path):
    job = create_job(
        state_dir=tmp_path,
        job_type="translation",
        argv=["python", "-m", "gemini_translator.cli", "--api-key", "secret-key"],
        project="/books/project",
        epub="/books/book.epub",
        metadata={"tool": "start_translation"},
    )

    loaded = load_job(tmp_path, job.id)

    assert loaded.id == job.id
    assert loaded.type == "translation"
    assert loaded.status == "queued"
    assert loaded.project == "/books/project"
    assert loaded.epub == "/books/book.epub"
    assert loaded.metadata == {"tool": "start_translation"}
    assert loaded.stdout_path.endswith("stdout.log")
    assert loaded.stderr_path.endswith("stderr.log")
    assert loaded.result_path.endswith("result.json")


def test_job_status_transitions_are_persisted(tmp_path):
    job = create_job(tmp_path, "translation", ["python"], project=None, epub=None)
    mark_running(job, pid=1234)
    save_job(tmp_path, job)
    loaded = load_job(tmp_path, job.id)

    assert loaded.status == "running"
    assert loaded.pid == 1234
    assert loaded.started_at is not None

    mark_finished(loaded, status="succeeded", exit_code=0)
    save_job(tmp_path, loaded)
    finished = load_job(tmp_path, job.id)

    assert finished.status == "succeeded"
    assert finished.exit_code == 0
    assert finished.finished_at is not None


def test_redact_for_mcp_hides_api_keys_and_text_payloads(tmp_path):
    job = create_job(
        tmp_path,
        "translation",
        ["python", "--api-key", "secret", "--prompt-file", "prompt.txt"],
        project="/project",
        epub="/book.epub",
        metadata={"api_key": "secret", "chapter_text": "very long text"},
    )

    redacted = redact_for_mcp(job.to_dict())

    assert "secret" not in json.dumps(redacted)
    assert redacted["metadata"]["api_key"] == "<redacted>"
    assert redacted["metadata"]["chapter_text"] == "<omitted>"


def test_tail_log_returns_last_lines(tmp_path):
    path = tmp_path / "sample.log"
    path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    assert tail_log(path, limit=2) == ["three", "four"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_jobs.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.mcp.jobs`.

- [ ] **Step 3: Implement `jobs.py`**

Create `gemini_translator/mcp/jobs.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets

from .paths import ensure_state_dirs, job_dir

TEXT_FIELD_HINTS = ("text", "prompt", "chapter", "response", "content")
SECRET_FIELD_HINTS = ("api_key", "api-key", "token", "secret", "password")


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
    path = directory / "job.json"
    path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(state_dir: Path, job_id: str) -> JobRecord:
    payload = json.loads(job_path(state_dir, job_id).read_text(encoding="utf-8"))
    return JobRecord.from_dict(payload)


def list_jobs(state_dir: Path) -> list[JobRecord]:
    root = state_dir / "jobs"
    if not root.exists():
        return []
    jobs = []
    for path in sorted(root.glob("*/job.json")):
        jobs.append(JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
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
        redacted.append(item)
        if item in {"--api-key", "--token"}:
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
```

- [ ] **Step 4: Run job tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_jobs.py -q
```

Expected: PASS with all tests in `tests/test_mcp_jobs.py`.

- [ ] **Step 5: Commit**

Run:

```bash
git add gemini_translator/mcp/jobs.py tests/test_mcp_jobs.py
git commit -m "Add durable MCP job records"
```

---

### Task 3: CLI Command Builder For MCP Tools

**Files:**
- Create: `gemini_translator/mcp/commands.py`
- Create: `tests/test_mcp_commands.py`

- [ ] **Step 1: Write command builder tests**

Create `tests/test_mcp_commands.py`:

```python
import sys

import pytest

from gemini_translator.mcp.commands import CommandBuildError, build_cli_command


def test_build_translation_command_uses_compact_cli():
    command = build_cli_command(
        "start_translation",
        {
            "epub": "/books/book.epub",
            "project": "/books/project",
            "provider": "gemini",
            "model": "Gemini 2.5 Flash",
            "chapters": "pending",
            "chapter": ["OEBPS/ch1.xhtml"],
            "workers": 2,
            "force_accept": True,
        },
    )

    assert command.job_type == "translation"
    assert command.project == "/books/project"
    assert command.epub == "/books/book.epub"
    assert command.argv[:4] == [sys.executable, "-m", "gemini_translator.cli", "--compact"]
    assert command.argv[4:] == [
        "translate",
        "--epub", "/books/book.epub",
        "--project", "/books/project",
        "--chapters", "pending",
        "--chapter", "OEBPS/ch1.xhtml",
        "--provider", "gemini",
        "--model", "Gemini 2.5 Flash",
        "--workers", "2",
        "--force-accept",
    ]


def test_build_untranslated_fix_defaults_to_writing_files():
    command = build_cli_command(
        "start_untranslated_fix",
        {
            "epub": "/books/book.epub",
            "project": "/books/project",
            "batch_size": 25,
        },
    )

    assert "untranslated-fix" in command.argv
    assert "--dry-run" not in command.argv
    assert "--batch-size" in command.argv
    assert "25" in command.argv


def test_build_consistency_write_requires_fix():
    with pytest.raises(CommandBuildError, match="write requires fix"):
        build_cli_command(
            "start_consistency_check",
            {
                "epub": "/books/book.epub",
                "project": "/books/project",
                "write": True,
                "fix": False,
            },
        )


def test_build_epub_command_supports_output_and_strict():
    command = build_cli_command(
        "start_epub_build",
        {
            "epub": "/books/book.epub",
            "project": "/books/project",
            "output": "/books/out.epub",
            "strict": True,
        },
    )

    assert command.job_type == "epub_build"
    assert command.argv[-3:] == ["--output", "/books/out.epub", "--strict"]


def test_unknown_tool_is_rejected():
    with pytest.raises(CommandBuildError, match="Unsupported MCP tool"):
        build_cli_command("not_a_tool", {})
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_commands.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.mcp.commands`.

- [ ] **Step 3: Implement command builder**

Create `gemini_translator/mcp/commands.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import sys


class CommandBuildError(ValueError):
    pass


@dataclass(frozen=True)
class BuiltCommand:
    job_type: str
    argv: list[str]
    project: str | None
    epub: str | None
    metadata: dict


COMMON_RUN_OPTIONS = {
    "provider": "--provider",
    "model": "--model",
    "api_key": "--api-key",
    "api_key_file": "--api-key-file",
    "workers": "--workers",
    "rpm": "--rpm",
    "temperature": "--temperature",
    "mode": "--mode",
    "task_size": "--task-size",
    "splits": "--splits",
    "prompt_file": "--prompt-file",
    "glossary": "--glossary",
    "settings_json": "--settings-json",
}

PROJECT_OPTIONS = {
    "epub": "--epub",
    "project": "--project",
    "chapters": "--chapters",
    "chapter": "--chapter",
    "offset": "--offset",
    "limit": "--limit",
}

BOOL_OPTIONS = {
    "all_keys": "--all-keys",
    "force_accept": "--force-accept",
    "json_epub": "--json-epub",
    "verbose": "--verbose",
}


def _base_argv(args: dict) -> list[str]:
    argv = [sys.executable, "-m", "gemini_translator.cli", "--compact"]
    if args.get("settings_profile"):
        argv.extend(["--settings-profile", str(args["settings_profile"])])
    if args.get("settings_dir"):
        argv.extend(["--settings-dir", str(args["settings_dir"])])
    return argv


def _add_value(argv: list[str], flag: str, value) -> None:
    if value is None:
        return
    if isinstance(value, str) and value == "":
        return
    argv.extend([flag, str(value)])


def _add_repeated(argv: list[str], flag: str, values) -> None:
    if values is None:
        return
    if isinstance(values, str):
        values = [values]
    for value in values:
        if value is not None and str(value) != "":
            argv.extend([flag, str(value)])


def _add_common_project(argv: list[str], args: dict) -> None:
    for key, flag in PROJECT_OPTIONS.items():
        if key == "chapter":
            _add_repeated(argv, flag, args.get(key))
        else:
            _add_value(argv, flag, args.get(key))


def _add_common_run(argv: list[str], args: dict) -> None:
    for key, flag in COMMON_RUN_OPTIONS.items():
        if key == "api_key":
            _add_repeated(argv, flag, args.get(key))
        else:
            _add_value(argv, flag, args.get(key))
    for key, flag in BOOL_OPTIONS.items():
        if bool(args.get(key)):
            argv.append(flag)


def _require_project_args(args: dict) -> None:
    if not args.get("epub"):
        raise CommandBuildError("epub is required")
    if not args.get("project"):
        raise CommandBuildError("project is required")


def _command_metadata(tool_name: str, args: dict) -> dict:
    return {
        "tool": tool_name,
        "requested_chapters": args.get("chapters"),
        "chapter_filters": args.get("chapter") or [],
    }


def build_cli_command(tool_name: str, args: dict) -> BuiltCommand:
    args = dict(args or {})
    if tool_name == "start_glossary_review_or_correction":
        return BuiltCommand(
            job_type="glossary_correction",
            argv=[],
            project=args.get("project"),
            epub=args.get("epub"),
            metadata={
                "tool": tool_name,
                "unsupported_in_this_build": True,
                "reason": "The current glossary correction flow is UI-driven and has no validated headless CLI command.",
            },
        )

    _require_project_args(args)
    argv = _base_argv(args)

    if tool_name == "start_translation":
        argv.append("translate")
        _add_common_project(argv, args)
        _add_common_run(argv, args)
        return BuiltCommand("translation", argv, args.get("project"), args.get("epub"), _command_metadata(tool_name, args))

    if tool_name == "start_glossary_generation":
        argv.append("glossary-generate")
        _add_common_project(argv, args)
        _add_common_run(argv, args)
        _add_value(argv, "--batch-size", args.get("batch_size"))
        _add_value(argv, "--merge-mode", args.get("merge_mode"))
        _add_value(argv, "--new-terms-limit", args.get("new_terms_limit"))
        _add_value(argv, "--glossary-prompt-file", args.get("glossary_prompt_file"))
        _add_value(argv, "--timeout", args.get("timeout"))
        return BuiltCommand("glossary_generation", argv, args.get("project"), args.get("epub"), _command_metadata(tool_name, args))

    if tool_name == "start_untranslated_fix":
        argv.append("untranslated-fix")
        _add_common_project(argv, args)
        _add_common_run(argv, args)
        _add_value(argv, "--suffix", args.get("suffix"))
        _add_value(argv, "--exceptions", args.get("exceptions"))
        _add_value(argv, "--fix-prompt-file", args.get("fix_prompt_file"))
        _add_value(argv, "--batch-size", args.get("batch_size"))
        _add_value(argv, "--max-context-chars", args.get("max_context_chars"))
        _add_value(argv, "--timeout", args.get("timeout"))
        if bool(args.get("dry_run")):
            argv.append("--dry-run")
        return BuiltCommand("untranslated_fix", argv, args.get("project"), args.get("epub"), _command_metadata(tool_name, args))

    if tool_name == "start_consistency_check":
        if bool(args.get("write")) and not bool(args.get("fix")):
            raise CommandBuildError("write requires fix for consistency jobs")
        argv.append("consistency")
        _add_common_project(argv, args)
        _add_common_run(argv, args)
        _add_value(argv, "--suffix", args.get("suffix"))
        _add_value(argv, "--consistency-mode", args.get("consistency_mode"))
        _add_value(argv, "--chunk-size", args.get("chunk_size"))
        _add_repeated(argv, "--confidences", args.get("confidences"))
        for key, flag in {
            "glossary_first": "--glossary-first",
            "no_source": "--no-source",
            "fix": "--fix",
            "write": "--write",
        }.items():
            if bool(args.get(key)):
                argv.append(flag)
        return BuiltCommand("consistency", argv, args.get("project"), args.get("epub"), _command_metadata(tool_name, args))

    if tool_name == "start_epub_build":
        argv.append("build-epub")
        _add_value(argv, "--epub", args.get("epub"))
        _add_value(argv, "--project", args.get("project"))
        _add_value(argv, "--output", args.get("output"))
        _add_value(argv, "--provider", args.get("provider"))
        _add_value(argv, "--suffix", args.get("suffix"))
        _add_repeated(argv, "--chapter", args.get("chapter"))
        _add_value(argv, "--offset", args.get("offset"))
        _add_value(argv, "--limit", args.get("limit"))
        if bool(args.get("strict")):
            argv.append("--strict")
        return BuiltCommand("epub_build", argv, args.get("project"), args.get("epub"), _command_metadata(tool_name, args))

    raise CommandBuildError(f"Unsupported MCP tool: {tool_name}")
```

- [ ] **Step 4: Run command builder tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_commands.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add gemini_translator/mcp/commands.py tests/test_mcp_commands.py
git commit -m "Map MCP tools to translator CLI commands"
```

---

### Task 4: Worker Runner For Subprocess Jobs

**Files:**
- Create: `gemini_translator/mcp/worker.py`
- Create: `tests/test_mcp_worker.py`

- [ ] **Step 1: Write worker tests**

Create `tests/test_mcp_worker.py`:

```python
import json
import sys

from gemini_translator.mcp.jobs import create_job, load_job
from gemini_translator.mcp.worker import cancel_process, run_job


def test_run_job_writes_result_and_marks_success(tmp_path):
    job = create_job(
        tmp_path,
        "fake",
        [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'ok': True, 'value': 7}))",
        ],
        project=None,
        epub=None,
    )

    result = run_job(tmp_path, job.id)
    loaded = load_job(tmp_path, job.id)

    assert result.status == "succeeded"
    assert loaded.status == "succeeded"
    assert loaded.exit_code == 0
    assert json.loads(open(loaded.result_path, encoding="utf-8").read()) == {"ok": True, "value": 7}


def test_run_job_marks_nonzero_exit_as_failed(tmp_path):
    job = create_job(
        tmp_path,
        "fake",
        [sys.executable, "-c", "import sys; sys.stderr.write('bad\\n'); sys.exit(3)"],
        project=None,
        epub=None,
    )

    result = run_job(tmp_path, job.id)

    assert result.status == "failed"
    assert result.exit_code == 3
    assert "bad" in open(result.stderr_path, encoding="utf-8").read()


def test_run_job_preserves_invalid_json_stdout(tmp_path):
    job = create_job(
        tmp_path,
        "fake",
        [sys.executable, "-c", "print('not json')"],
        project=None,
        epub=None,
    )

    result = run_job(tmp_path, job.id)

    assert result.status == "failed"
    assert "Could not parse worker JSON result" in result.error


def test_cancel_process_returns_false_for_missing_pid():
    assert cancel_process(999999999) is False
```

- [ ] **Step 2: Run worker tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_worker.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.mcp.worker`.

- [ ] **Step 3: Implement worker runner**

Create `gemini_translator/mcp/worker.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess

from .jobs import JobRecord, load_job, mark_finished, mark_running, save_job
from .paths import repo_root


def _parse_stdout_json(stdout_path: str) -> tuple[dict | None, str | None]:
    text = Path(stdout_path).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None, "Worker produced no JSON result on stdout"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Could not parse worker JSON result: {exc}"
    if not isinstance(payload, dict):
        return None, "Worker JSON result is not an object"
    return payload, None


def run_job(state_dir: Path, job_id: str) -> JobRecord:
    job = load_job(state_dir, job_id)
    stdout_path = Path(job.stdout_path)
    stderr_path = Path(job.stderr_path)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            job.argv,
            cwd=str(repo_root()),
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
        mark_running(job, pid=process.pid)
        save_job(state_dir, job)
        exit_code = process.wait()

    payload, parse_error = _parse_stdout_json(job.stdout_path)
    if payload is not None:
        Path(job.result_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if exit_code == 0 and parse_error is None:
        mark_finished(job, status="succeeded", exit_code=exit_code)
    else:
        error = parse_error or f"Worker exited with code {exit_code}"
        mark_finished(job, status="failed", exit_code=exit_code, error=error)

    save_job(state_dir, job)
    return job


def cancel_process(pid: int) -> bool:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False
```

- [ ] **Step 4: Run worker tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_worker.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add gemini_translator/mcp/worker.py tests/test_mcp_worker.py
git commit -m "Run MCP jobs as subprocesses"
```

---

### Task 5: Local Daemon HTTP API

**Files:**
- Create: `gemini_translator/mcp/daemon.py`
- Create: `tests/test_mcp_daemon.py`

- [ ] **Step 1: Write daemon tests with an inline fake runner**

Create `tests/test_mcp_daemon.py`:

```python
import json
import sys
import time
import urllib.error
import urllib.request

from gemini_translator.mcp.daemon import McpDaemon, read_daemon_info


def _request(method, url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-Translator-MCP-Token", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_daemon_rejects_missing_token(tmp_path):
    daemon = McpDaemon(tmp_path)
    daemon.start_in_thread()
    try:
        request = urllib.request.Request(f"{daemon.base_url}/status", method="GET")
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("request without token must fail")
    finally:
        daemon.stop()


def test_daemon_enqueue_and_status(tmp_path):
    daemon = McpDaemon(tmp_path)
    daemon.start_in_thread()
    try:
        payload = {
            "job_type": "fake",
            "argv": [sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"],
            "project": "/project",
            "epub": "/book.epub",
            "metadata": {"tool": "fake"},
        }
        created = _request("POST", f"{daemon.base_url}/jobs", daemon.token, payload)
        assert created["job"]["status"] in {"queued", "running", "succeeded"}

        deadline = time.time() + 10
        status = {}
        while time.time() < deadline:
            status = _request("GET", f"{daemon.base_url}/jobs/{created['job']['id']}", daemon.token)
            if status["job"]["status"] == "succeeded":
                break
            time.sleep(0.1)

        assert status["job"]["status"] == "succeeded"
        assert status["job"]["project"] == "/project"
    finally:
        daemon.stop()


def test_daemon_info_is_written(tmp_path):
    daemon = McpDaemon(tmp_path)
    daemon.start_in_thread()
    try:
        info = read_daemon_info(tmp_path)
        assert info["pid"] > 0
        assert info["port"] == daemon.port
        assert info["token"] == daemon.token
    finally:
        daemon.stop()
```

- [ ] **Step 2: Run daemon tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_daemon.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.mcp.daemon`.

- [ ] **Step 3: Implement daemon**

Create `gemini_translator/mcp/daemon.py`:

```python
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlparse

from .jobs import create_job, list_jobs, load_job, mark_finished, redact_for_mcp, save_job, tail_log
from .paths import daemon_file, ensure_state_dirs
from .worker import cancel_process, run_job


def read_daemon_info(state_dir: Path) -> dict:
    path = daemon_file(state_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class McpDaemon:
    def __init__(self, state_dir: Path, *, host: str = "127.0.0.1", port: int = 0, concurrency: int = 1):
        self.state_dir = ensure_state_dirs(state_dir)
        self.host = host
        self.port = port
        self.concurrency = max(1, int(concurrency))
        self.token = secrets.token_urlsafe(24)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.active_threads: dict[str, threading.Thread] = {}
        self.shutdown_requested = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start_in_thread(self) -> None:
        handler = self._make_handler()
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = int(self.httpd.server_address[1])
        daemon_file(self.state_dir).write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": self.host,
                    "port": self.port,
                    "token": self.token,
                    "started_at": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="translator-mcp-daemon", daemon=True)
        self.thread.start()

    def serve_forever(self) -> None:
        self.start_in_thread()
        try:
            while not self.shutdown_requested:
                time.sleep(0.2)
        finally:
            self.stop()

    def stop(self) -> None:
        self.shutdown_requested = True
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        daemon_file(self.state_dir).unlink(missing_ok=True)

    def status_payload(self) -> dict:
        jobs = list_jobs(self.state_dir)
        counts = {}
        for job in jobs:
            counts[job.status] = counts.get(job.status, 0) + 1
        return {
            "ok": True,
            "daemon": {
                "pid": os.getpid(),
                "host": self.host,
                "port": self.port,
                "concurrency": self.concurrency,
            },
            "queue": counts,
            "active_jobs": list(self.active_threads.keys()),
        }

    def enqueue(self, payload: dict) -> dict:
        job = create_job(
            self.state_dir,
            str(payload["job_type"]),
            [str(item) for item in payload["argv"]],
            project=payload.get("project"),
            epub=payload.get("epub"),
            metadata=dict(payload.get("metadata") or {}),
        )
        self._start_available_jobs()
        return {"ok": True, "job": redact_for_mcp(job)}

    def get_job_payload(self, job_id: str) -> dict:
        job = load_job(self.state_dir, job_id)
        result = None
        result_path = Path(job.result_path)
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        return {
            "ok": True,
            "job": redact_for_mcp(job),
            "result": redact_for_mcp(result) if result is not None else None,
            "stdout_tail": tail_log(job.stdout_path, limit=20),
            "stderr_tail": tail_log(job.stderr_path, limit=20),
        }

    def list_jobs_payload(self) -> dict:
        return {"ok": True, "jobs": [redact_for_mcp(job) for job in list_jobs(self.state_dir)]}

    def cancel(self, job_id: str) -> dict:
        job = load_job(self.state_dir, job_id)
        cancelled = False
        if job.pid:
            cancelled = cancel_process(int(job.pid))
        mark_finished(job, status="cancelled", exit_code=job.exit_code, error="Cancelled by MCP request")
        save_job(self.state_dir, job)
        return {"ok": True, "cancel_requested": cancelled, "job": redact_for_mcp(job)}

    def _start_available_jobs(self) -> None:
        with self.lock:
            self.active_threads = {job_id: thread for job_id, thread in self.active_threads.items() if thread.is_alive()}
            if len(self.active_threads) >= self.concurrency:
                return
            for job in reversed(list_jobs(self.state_dir)):
                if job.status != "queued":
                    continue
                thread = threading.Thread(target=self._run_and_continue, args=(job.id,), name=f"mcp-job-{job.id}", daemon=True)
                self.active_threads[job.id] = thread
                thread.start()
                if len(self.active_threads) >= self.concurrency:
                    return

    def _run_and_continue(self, job_id: str) -> None:
        try:
            run_job(self.state_dir, job_id)
        finally:
            with self.lock:
                self.active_threads.pop(job_id, None)
            self._start_available_jobs()

    def _make_handler(self):
        daemon = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _send(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                return self.headers.get("X-Translator-MCP-Token") == daemon.token

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length") or "0")
                if length <= 0:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def do_GET(self):
                if not self._authorized():
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return
                path = urlparse(self.path).path
                if path == "/status":
                    self._send(200, daemon.status_payload())
                    return
                if path == "/jobs":
                    self._send(200, daemon.list_jobs_payload())
                    return
                if path.startswith("/jobs/"):
                    self._send(200, daemon.get_job_payload(path.rsplit("/", 1)[-1]))
                    return
                self._send(404, {"ok": False, "error": "not found"})

            def do_POST(self):
                if not self._authorized():
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return
                path = urlparse(self.path).path
                if path == "/jobs":
                    self._send(200, daemon.enqueue(self._read_json()))
                    return
                if path.startswith("/jobs/") and path.endswith("/cancel"):
                    job_id = path.split("/")[-2]
                    self._send(200, daemon.cancel(job_id))
                    return
                if path == "/shutdown":
                    self._send(200, {"ok": True})
                    threading.Thread(target=daemon.stop, daemon=True).start()
                    return
                self._send(404, {"ok": False, "error": "not found"})

        return Handler
```

- [ ] **Step 4: Run daemon tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_daemon.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add gemini_translator/mcp/daemon.py tests/test_mcp_daemon.py
git commit -m "Add local MCP daemon"
```

---

### Task 6: Daemon Client And CLI Entrypoint

**Files:**
- Create: `gemini_translator/mcp/client.py`
- Create: `gemini_translator/mcp/__main__.py`
- Modify: `tests/test_mcp_daemon.py`

- [ ] **Step 1: Add client and CLI tests**

Append this to `tests/test_mcp_daemon.py`:

```python
import subprocess

from gemini_translator.mcp.client import DaemonClient, DaemonClientError


def test_daemon_client_status(tmp_path):
    daemon = McpDaemon(tmp_path)
    daemon.start_in_thread()
    try:
        client = DaemonClient.from_info(read_daemon_info(tmp_path))
        payload = client.status()
        assert payload["ok"] is True
        assert payload["daemon"]["port"] == daemon.port
    finally:
        daemon.stop()


def test_module_cli_status_without_daemon(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gemini_translator.mcp",
            "--state-dir",
            str(tmp_path),
            "daemon",
            "status",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 1
    assert "daemon is not running" in result.stdout
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_daemon.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.mcp.client` or missing module entrypoint.

- [ ] **Step 3: Implement daemon client**

Create `gemini_translator/mcp/client.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .daemon import read_daemon_info
from .paths import daemon_stderr_log, daemon_stdout_log, default_state_dir


class DaemonClientError(RuntimeError):
    pass


class DaemonClient:
    def __init__(self, *, host: str, port: int, token: str):
        self.host = host
        self.port = int(port)
        self.token = token

    @classmethod
    def from_info(cls, info: dict) -> "DaemonClient":
        if not info:
            raise DaemonClientError("daemon is not running")
        return cls(host=info["host"], port=int(info["port"]), token=info["token"])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        request.add_header("X-Translator-MCP-Token", self.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise DaemonClientError(str(exc)) from exc

    def status(self) -> dict:
        return self.request("GET", "/status")

    def enqueue(self, payload: dict) -> dict:
        return self.request("POST", "/jobs", payload)

    def get_job(self, job_id: str) -> dict:
        return self.request("GET", f"/jobs/{job_id}")

    def list_jobs(self) -> dict:
        return self.request("GET", "/jobs")

    def cancel_job(self, job_id: str) -> dict:
        return self.request("POST", f"/jobs/{job_id}/cancel", {})

    def shutdown(self) -> dict:
        return self.request("POST", "/shutdown", {})


def load_client(state_dir: Path | None = None) -> DaemonClient:
    return DaemonClient.from_info(read_daemon_info(state_dir or default_state_dir()))


def ensure_daemon_process(state_dir: Path | None = None) -> DaemonClient:
    root = state_dir or default_state_dir()
    info = read_daemon_info(root)
    if info:
        try:
            client = DaemonClient.from_info(info)
            client.status()
            return client
        except DaemonClientError:
            pass

    root.mkdir(parents=True, exist_ok=True)
    stdout = daemon_stdout_log(root).open("a", encoding="utf-8")
    stderr = daemon_stderr_log(root).open("a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "gemini_translator.mcp", "--state-dir", str(root), "daemon", "serve"],
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )

    deadline = time.time() + 10
    while time.time() < deadline:
        info = read_daemon_info(root)
        if info:
            try:
                client = DaemonClient.from_info(info)
                client.status()
                return client
            except DaemonClientError:
                pass
        time.sleep(0.1)
    raise DaemonClientError(f"daemon did not start; see {daemon_stderr_log(root)}")
```

- [ ] **Step 4: Implement module CLI**

Create `gemini_translator/mcp/__main__.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .client import DaemonClientError, load_client
from .daemon import McpDaemon
from .paths import default_state_dir


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="translator-mcp")
    parser.add_argument("--state-dir", help="Override MCP state directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daemon = subparsers.add_parser("daemon")
    daemon_sub = daemon.add_subparsers(dest="daemon_command", required=True)
    daemon_sub.add_parser("serve")
    daemon_sub.add_parser("status")
    daemon_sub.add_parser("stop")

    subparsers.add_parser("server")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir).expanduser().resolve() if args.state_dir else default_state_dir()

    if args.command == "daemon":
        if args.daemon_command == "serve":
            McpDaemon(state_dir).serve_forever()
            return 0
        try:
            client = load_client(state_dir)
            if args.daemon_command == "status":
                _print(client.status())
                return 0
            if args.daemon_command == "stop":
                _print(client.shutdown())
                return 0
        except DaemonClientError as exc:
            _print({"ok": False, "error": str(exc)})
            return 1

    if args.command == "server":
        from .server import run_stdio_server

        run_stdio_server(state_dir=state_dir)
        return 0

    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run daemon tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_daemon.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add gemini_translator/mcp/client.py gemini_translator/mcp/__main__.py tests/test_mcp_daemon.py
git commit -m "Add MCP daemon lifecycle CLI"
```

---

### Task 7: Minimal MCP Stdio Server And Tool Calls

**Files:**
- Create: `gemini_translator/mcp/server.py`
- Create: `tests/test_mcp_server.py`
- Modify: `gemini_translator/mcp/__main__.py` only if imports need adjustment

- [ ] **Step 1: Write MCP server tests**

Create `tests/test_mcp_server.py`:

```python
from gemini_translator.mcp.server import McpStdioServer, TOOL_NAMES


class FakeClient:
    def __init__(self):
        self.enqueued = []

    def status(self):
        return {"ok": True, "daemon": {"pid": 1}, "queue": {}}

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"ok": True, "job": {"id": "job_1", "status": "queued", "type": payload["job_type"]}}

    def get_job(self, job_id):
        return {"ok": True, "job": {"id": job_id, "status": "succeeded"}}

    def list_jobs(self):
        return {"ok": True, "jobs": []}

    def cancel_job(self, job_id):
        return {"ok": True, "job": {"id": job_id, "status": "cancelled"}}


def test_tools_list_contains_translation_tools():
    server = McpStdioServer(client_factory=lambda: FakeClient())
    result = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tool_names = [tool["name"] for tool in result["result"]["tools"]]

    assert "start_translation" in tool_names
    assert "get_job_status" in tool_names
    assert tool_names == TOOL_NAMES


def test_initialize_response_uses_mcp_protocol_version():
    server = McpStdioServer(client_factory=lambda: FakeClient())
    result = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})

    assert result["result"]["protocolVersion"] == "2025-06-18"
    assert result["result"]["serverInfo"]["name"] == "translatorFork"


def test_start_translation_enqueues_daemon_job():
    fake = FakeClient()
    server = McpStdioServer(client_factory=lambda: fake)
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "start_translation",
                "arguments": {"epub": "/book.epub", "project": "/project"},
            },
        }
    )

    assert response["result"]["isError"] is False
    assert fake.enqueued[0]["job_type"] == "translation"
    assert fake.enqueued[0]["project"] == "/project"


def test_glossary_correction_returns_structured_unsupported_response():
    server = McpStdioServer(client_factory=lambda: FakeClient())
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "start_glossary_review_or_correction",
                "arguments": {"epub": "/book.epub", "project": "/project"},
            },
        }
    )

    assert response["result"]["isError"] is True
    assert "unsupported_in_this_build" in response["result"]["content"][0]["text"]


def test_get_job_status_calls_client():
    server = McpStdioServer(client_factory=lambda: FakeClient())
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_job_status", "arguments": {"job_id": "job_1"}},
        }
    )

    assert response["result"]["isError"] is False
    assert "job_1" in response["result"]["content"][0]["text"]
```

- [ ] **Step 2: Run MCP server tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.mcp.server`.

- [ ] **Step 3: Implement MCP server**

Create `gemini_translator/mcp/server.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
import sys

from .client import ensure_daemon_process
from .commands import CommandBuildError, build_cli_command
from .jobs import redact_for_mcp

PROTOCOL_VERSION = "2025-06-18"

TOOL_NAMES = [
    "translator_status",
    "start_translation",
    "start_glossary_generation",
    "start_glossary_review_or_correction",
    "start_untranslated_fix",
    "start_consistency_check",
    "start_epub_build",
    "start_full_pipeline",
    "get_job_status",
    "list_jobs",
    "cancel_job",
    "install_mcp_client",
    "print_mcp_config",
]


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


TOOL_DEFINITIONS = [
    {"name": "translator_status", "description": "Show translator MCP daemon and queue status.", "inputSchema": _schema({})},
    {"name": "start_translation", "description": "Start a headless EPUB translation job.", "inputSchema": _schema({"epub": {"type": "string"}, "project": {"type": "string"}}, ["epub", "project"])},
    {"name": "start_glossary_generation", "description": "Start AI glossary generation for selected EPUB chapters.", "inputSchema": _schema({"epub": {"type": "string"}, "project": {"type": "string"}}, ["epub", "project"])},
    {"name": "start_glossary_review_or_correction", "description": "Report headless glossary correction support status.", "inputSchema": _schema({"epub": {"type": "string"}, "project": {"type": "string"}}, ["epub", "project"])},
    {"name": "start_untranslated_fix", "description": "Use AI to fix untranslated residue and write changes to disk by default.", "inputSchema": _schema({"epub": {"type": "string"}, "project": {"type": "string"}}, ["epub", "project"])},
    {"name": "start_consistency_check", "description": "Run AI consistency analysis and optional auto-fix.", "inputSchema": _schema({"epub": {"type": "string"}, "project": {"type": "string"}}, ["epub", "project"])},
    {"name": "start_epub_build", "description": "Build an EPUB from translated project files.", "inputSchema": _schema({"epub": {"type": "string"}, "project": {"type": "string"}}, ["epub", "project"])},
    {"name": "start_full_pipeline", "description": "Create a parent pipeline job with child translator operations.", "inputSchema": _schema({"epub": {"type": "string"}, "project": {"type": "string"}}, ["epub", "project"])},
    {"name": "get_job_status", "description": "Get status, log tails, and result summary for a job.", "inputSchema": _schema({"job_id": {"type": "string"}}, ["job_id"])},
    {"name": "list_jobs", "description": "List recent MCP jobs.", "inputSchema": _schema({})},
    {"name": "cancel_job", "description": "Request best-effort cancellation for a job.", "inputSchema": _schema({"job_id": {"type": "string"}}, ["job_id"])},
    {"name": "install_mcp_client", "description": "Install or print MCP config for supported desktop AI clients.", "inputSchema": _schema({"client": {"type": "string"}, "mode": {"type": "string"}})},
    {"name": "print_mcp_config", "description": "Print a manual MCP config snippet.", "inputSchema": _schema({"client": {"type": "string"}})},
]


class McpStdioServer:
    def __init__(self, *, client_factory):
        self.client_factory = client_factory

    def handle_request(self, request: dict) -> dict | None:
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None and method and method.startswith("notifications/"):
            return None
        try:
            if method == "initialize":
                return self._response(request_id, self._initialize())
            if method == "ping":
                return self._response(request_id, {})
            if method == "tools/list":
                return self._response(request_id, {"tools": TOOL_DEFINITIONS})
            if method == "tools/call":
                params = request.get("params") or {}
                return self._response(request_id, self._call_tool(str(params.get("name")), dict(params.get("arguments") or {})))
            return self._error(request_id, -32601, f"Method not found: {method}")
        except Exception as exc:
            return self._error(request_id, -32603, f"{type(exc).__name__}: {exc}")

    def _initialize(self) -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "translatorFork", "version": "0.1.0"},
        }

    def _call_tool(self, name: str, arguments: dict) -> dict:
        client = self.client_factory()
        if name == "translator_status":
            return self._tool_result(client.status())
        if name == "get_job_status":
            return self._tool_result(client.get_job(str(arguments["job_id"])))
        if name == "list_jobs":
            return self._tool_result(client.list_jobs())
        if name == "cancel_job":
            return self._tool_result(client.cancel_job(str(arguments["job_id"])))
        if name in {"install_mcp_client", "print_mcp_config"}:
            from .client_install import handle_install_tool

            return self._tool_result(handle_install_tool(name, arguments))
        if name == "start_full_pipeline":
            return self._tool_result(_pipeline_not_implemented(arguments), is_error=True)

        built = build_cli_command(name, arguments)
        if built.metadata.get("unsupported_in_this_build"):
            return self._tool_result(built.metadata, is_error=True)
        payload = {
            "job_type": built.job_type,
            "argv": built.argv,
            "project": built.project,
            "epub": built.epub,
            "metadata": built.metadata,
        }
        return self._tool_result(client.enqueue(payload))

    def _tool_result(self, payload: dict, *, is_error: bool = False) -> dict:
        text = json.dumps(redact_for_mcp(payload), ensure_ascii=False, indent=2)
        return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}

    def _response(self, request_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(self, request_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _pipeline_not_implemented(arguments: dict) -> dict:
    return {
        "ok": False,
        "unsupported_in_this_build": True,
        "reason": "Pipeline orchestration is added in the pipeline task after single-job tools are validated.",
        "requested": redact_for_mcp(arguments),
    }


def run_stdio_server(*, state_dir: Path) -> None:
    server = McpStdioServer(client_factory=lambda: ensure_daemon_process(state_dir))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = server.handle_request(json.loads(line))
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
```

- [ ] **Step 4: Run MCP server tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add gemini_translator/mcp/server.py tests/test_mcp_server.py
git commit -m "Add MCP stdio server"
```

---

### Task 8: Client Config Snippets And Safe Installer

**Files:**
- Create: `gemini_translator/mcp/client_install.py`
- Create: `tests/test_mcp_client_install.py`
- Modify: `gemini_translator/mcp/__main__.py`

- [ ] **Step 1: Write installer tests**

Create `tests/test_mcp_client_install.py`:

```python
import json

from gemini_translator.mcp.client_install import (
    build_config_snippet,
    handle_install_tool,
    install_claude_config,
)


def test_build_claude_snippet_uses_module_entrypoint():
    snippet = build_config_snippet("claude", server_name="translatorFork")

    assert snippet["mcpServers"]["translatorFork"]["args"][-2:] == ["server"]
    assert "-m" in snippet["mcpServers"]["translatorFork"]["args"]
    assert "gemini_translator.mcp" in snippet["mcpServers"]["translatorFork"]["args"]


def test_build_codex_snippet_uses_toml_shape():
    snippet = build_config_snippet("codex", server_name="translatorFork")

    assert "[mcp_servers.translatorFork]" in snippet["text"]
    assert "gemini_translator.mcp" in snippet["text"]


def test_install_claude_config_creates_backup_and_preserves_existing(tmp_path):
    path = tmp_path / "claude.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "old"}}}), encoding="utf-8")

    result = install_claude_config(path, server_name="translatorFork", mode="write")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert result["written"] is True
    assert result["backup_path"]
    assert "other" in payload["mcpServers"]
    assert "translatorFork" in payload["mcpServers"]


def test_install_tool_print_mode_does_not_write(tmp_path):
    path = tmp_path / "claude.json"
    result = handle_install_tool(
        "install_mcp_client",
        {"client": "claude", "mode": "print", "config_path": str(path), "server_name": "translatorFork"},
    )

    assert result["written"] is False
    assert path.exists() is False
    assert result["snippet"]
```

- [ ] **Step 2: Run installer tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_client_install.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `gemini_translator.mcp.client_install`.

- [ ] **Step 3: Implement installer**

Create `gemini_translator/mcp/client_install.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys


def _server_command() -> dict:
    return {
        "command": sys.executable,
        "args": ["-m", "gemini_translator.mcp", "server"],
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_config_snippet(client: str, *, server_name: str = "translatorFork") -> dict:
    client = (client or "generic").strip().lower()
    command = _server_command()
    if client in {"claude", "generic", "antigravity"}:
        return {"mcpServers": {server_name: command}}
    if client == "codex":
        args = ", ".join(json.dumps(item) for item in command["args"])
        return {
            "text": (
                f"[mcp_servers.{server_name}]\n"
                f"command = {json.dumps(command['command'])}\n"
                f"args = [{args}]\n"
            )
        }
    raise ValueError(f"Unsupported client: {client}")


def _backup(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + f".bak-{_timestamp()}")
    shutil.copy2(path, backup_path)
    return backup_path


def install_claude_config(path: Path, *, server_name: str, mode: str) -> dict:
    snippet = build_config_snippet("claude", server_name=server_name)
    if mode == "print":
        return {"ok": True, "written": False, "backup_path": None, "snippet": json.dumps(snippet, ensure_ascii=False, indent=2)}

    backup_path = None
    payload = {}
    if path.exists():
        backup_path = _backup(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("mcpServers", {})
    payload["mcpServers"][server_name] = snippet["mcpServers"][server_name]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "written": True,
        "backup_path": str(backup_path) if backup_path else None,
        "snippet": json.dumps(snippet, ensure_ascii=False, indent=2),
    }


def handle_install_tool(tool_name: str, arguments: dict) -> dict:
    client = str(arguments.get("client") or "generic").lower()
    mode = str(arguments.get("mode") or "print").lower()
    server_name = str(arguments.get("server_name") or "translatorFork")
    config_path = arguments.get("config_path")

    if tool_name == "print_mcp_config":
        snippet = build_config_snippet(client, server_name=server_name)
        return {"ok": True, "written": False, "snippet": json.dumps(snippet, ensure_ascii=False, indent=2)}

    if mode not in {"auto", "print", "write"}:
        return {"ok": False, "written": False, "error": "mode must be auto, print, or write"}

    if client == "claude" and config_path:
        return install_claude_config(Path(config_path).expanduser(), server_name=server_name, mode="print" if mode == "auto" else mode)

    snippet = build_config_snippet(client, server_name=server_name)
    return {
        "ok": True,
        "written": False,
        "warning": "automatic config path was not detected; paste this snippet manually",
        "snippet": json.dumps(snippet, ensure_ascii=False, indent=2) if "mcpServers" in snippet else snippet["text"],
    }
```

- [ ] **Step 4: Add CLI config commands**

Modify `gemini_translator/mcp/__main__.py`:

```python
from .client_install import handle_install_tool
```

Add parser commands inside `build_parser()` before `return parser`:

```python
    install = subparsers.add_parser("install")
    install.add_argument("--client", default="generic", choices=["codex", "claude", "antigravity", "generic"])
    install.add_argument("--mode", default="print", choices=["auto", "print", "write"])
    install.add_argument("--config-path")
    install.add_argument("--server-name", default="translatorFork")

    config = subparsers.add_parser("config")
    config.add_argument("--client", default="generic", choices=["codex", "claude", "antigravity", "generic"])
    config.add_argument("--server-name", default="translatorFork")
```

Add command handling inside `main()` before `parser.error`:

```python
    if args.command == "install":
        _print(handle_install_tool(
            "install_mcp_client",
            {
                "client": args.client,
                "mode": args.mode,
                "config_path": args.config_path,
                "server_name": args.server_name,
            },
        ))
        return 0

    if args.command == "config":
        _print(handle_install_tool(
            "print_mcp_config",
            {"client": args.client, "server_name": args.server_name},
        ))
        return 0
```

- [ ] **Step 5: Run installer tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_client_install.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add gemini_translator/mcp/client_install.py gemini_translator/mcp/__main__.py tests/test_mcp_client_install.py
git commit -m "Add MCP client config installer"
```

---

### Task 9: Pipeline Orchestration And Tool Completion

**Files:**
- Modify: `gemini_translator/mcp/daemon.py`
- Modify: `gemini_translator/mcp/server.py`
- Modify: `tests/test_mcp_daemon.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Add pipeline tests**

Append this to `tests/test_mcp_server.py`:

```python
def test_start_full_pipeline_enqueues_pipeline_job():
    fake = FakeClient()
    server = McpStdioServer(client_factory=lambda: fake)
    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "start_full_pipeline",
                "arguments": {
                    "epub": "/book.epub",
                    "project": "/project",
                    "steps": ["glossary", "translation", "untranslated_fix", "consistency", "epub_build"],
                },
            },
        }
    )

    assert response["result"]["isError"] is False
    assert fake.enqueued[0]["job_type"] == "pipeline"
    assert fake.enqueued[0]["metadata"]["steps"][0]["tool"] == "start_glossary_generation"
```

Append this to `tests/test_mcp_daemon.py`:

```python
def test_pipeline_skips_later_steps_after_failure(tmp_path):
    daemon = McpDaemon(tmp_path)
    daemon.start_in_thread()
    try:
        payload = {
            "job_type": "pipeline",
            "argv": [],
            "project": "/project",
            "epub": "/book.epub",
            "metadata": {
                "tool": "start_full_pipeline",
                "continue_on_error": False,
                "steps": [
                    {
                        "name": "first",
                        "tool": "start_translation",
                        "job_type": "fake",
                        "argv": [sys.executable, "-c", "import sys; sys.exit(2)"],
                    },
                    {
                        "name": "second",
                        "tool": "start_epub_build",
                        "job_type": "fake",
                        "argv": [sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"],
                    },
                ],
            },
        }
        created = _request("POST", f"{daemon.base_url}/jobs", daemon.token, payload)
        parent_id = created["job"]["id"]

        deadline = time.time() + 10
        parent = {}
        while time.time() < deadline:
            parent = _request("GET", f"{daemon.base_url}/jobs/{parent_id}", daemon.token)
            if parent["job"]["status"] == "failed":
                break
            time.sleep(0.1)

        children = parent["job"]["children"]
        first = _request("GET", f"{daemon.base_url}/jobs/{children[0]}", daemon.token)
        second = _request("GET", f"{daemon.base_url}/jobs/{children[1]}", daemon.token)

        assert parent["job"]["status"] == "failed"
        assert first["job"]["status"] == "failed"
        assert second["job"]["status"] == "cancelled"
    finally:
        daemon.stop()
```

- [ ] **Step 2: Run pipeline test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py::test_start_full_pipeline_enqueues_pipeline_job -q
```

Expected: FAIL because `start_full_pipeline` returns `unsupported_in_this_build`.

- [ ] **Step 3: Implement pipeline payload construction in `server.py`**

Replace `_pipeline_not_implemented()` in `gemini_translator/mcp/server.py` with:

```python
PIPELINE_STEP_TO_TOOL = {
    "glossary": "start_glossary_generation",
    "translation": "start_translation",
    "untranslated_fix": "start_untranslated_fix",
    "consistency": "start_consistency_check",
    "epub_build": "start_epub_build",
}


def build_pipeline_payload(arguments: dict) -> dict:
    requested_steps = arguments.get("steps") or ["translation", "untranslated_fix", "consistency", "epub_build"]
    steps = []
    for step_name in requested_steps:
        tool = PIPELINE_STEP_TO_TOOL[str(step_name)]
        step_args = dict(arguments)
        step_args.pop("steps", None)
        built = build_cli_command(tool, step_args)
        steps.append({"name": str(step_name), "tool": tool, "job_type": built.job_type, "argv": built.argv})
    return {
        "job_type": "pipeline",
        "argv": [],
        "project": arguments.get("project"),
        "epub": arguments.get("epub"),
        "metadata": {"tool": "start_full_pipeline", "steps": steps, "continue_on_error": bool(arguments.get("continue_on_error"))},
    }
```

Change the `start_full_pipeline` branch in `_call_tool()` to:

```python
        if name == "start_full_pipeline":
            return self._tool_result(client.enqueue(build_pipeline_payload(arguments)))
```

- [ ] **Step 4: Make daemon create sequential pipeline children**

Add this branch at the top of `McpDaemon.enqueue()` in `gemini_translator/mcp/daemon.py`:

```python
        if str(payload["job_type"]) == "pipeline":
            parent = create_job(
                self.state_dir,
                "pipeline",
                [],
                project=payload.get("project"),
                epub=payload.get("epub"),
                metadata=dict(payload.get("metadata") or {}),
            )
            children = []
            steps = list(parent.metadata.get("steps", []))
            for index, step in enumerate(steps):
                child = create_job(
                    self.state_dir,
                    str(step["job_type"]),
                    [str(item) for item in step["argv"]],
                    project=parent.project,
                    epub=parent.epub,
                    metadata={
                        "tool": step["tool"],
                        "pipeline_parent": parent.id,
                        "pipeline_step": step["name"],
                        "pipeline_index": index,
                        "pipeline_total": len(steps),
                    },
                )
                children.append(child.id)
            parent.children = children
            parent.status = "running"
            parent.started_at = parent.created_at
            save_job(self.state_dir, parent)
            self._start_available_jobs()
            return {"ok": True, "job": redact_for_mcp(parent)}
```

Add these helper methods to `McpDaemon` before `_start_available_jobs()`:

```python
    def _pipeline_allows_start(self, job) -> bool:
        parent_id = job.metadata.get("pipeline_parent")
        if not parent_id:
            return True
        parent = load_job(self.state_dir, str(parent_id))
        continue_on_error = bool(parent.metadata.get("continue_on_error"))
        index = int(job.metadata.get("pipeline_index", 0))
        siblings = [
            item
            for item in list_jobs(self.state_dir)
            if item.metadata.get("pipeline_parent") == parent.id
        ]
        prior = [
            item
            for item in siblings
            if int(item.metadata.get("pipeline_index", 0)) < index
        ]
        if any(item.status in {"failed", "cancelled"} for item in prior) and not continue_on_error:
            mark_finished(job, status="cancelled", exit_code=None, error="Skipped because an earlier pipeline step failed")
            save_job(self.state_dir, job)
            self._refresh_pipeline_parent(parent.id)
            return False
        return all(
            item.status == "succeeded" or continue_on_error and item.status in {"succeeded", "failed", "cancelled"}
            for item in prior
        )

    def _refresh_pipeline_parent(self, parent_id: str) -> None:
        parent = load_job(self.state_dir, parent_id)
        children = [load_job(self.state_dir, child_id) for child_id in parent.children]
        terminal = {"succeeded", "failed", "cancelled"}
        if not children or not all(child.status in terminal for child in children):
            return
        if all(child.status == "succeeded" for child in children):
            mark_finished(parent, status="succeeded", exit_code=0)
        else:
            mark_finished(parent, status="failed", exit_code=1, error="One or more pipeline steps failed")
        save_job(self.state_dir, parent)
```

Change the queued-job loop in `_start_available_jobs()` from:

```python
                if job.status != "queued":
                    continue
                thread = threading.Thread(target=self._run_and_continue, args=(job.id,), name=f"mcp-job-{job.id}", daemon=True)
```

to:

```python
                if job.status != "queued":
                    continue
                if not self._pipeline_allows_start(job):
                    continue
                thread = threading.Thread(target=self._run_and_continue, args=(job.id,), name=f"mcp-job-{job.id}", daemon=True)
```

Replace `_run_and_continue()` with:

```python
    def _run_and_continue(self, job_id: str) -> None:
        parent_id = None
        try:
            run_job(self.state_dir, job_id)
            finished_job = load_job(self.state_dir, job_id)
            parent_id = finished_job.metadata.get("pipeline_parent")
        finally:
            with self.lock:
                self.active_threads.pop(job_id, None)
            if parent_id:
                self._refresh_pipeline_parent(str(parent_id))
            self._start_available_jobs()
```

- [ ] **Step 5: Run MCP server and daemon tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_server.py tests/test_mcp_daemon.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add gemini_translator/mcp/server.py gemini_translator/mcp/daemon.py tests/test_mcp_server.py tests/test_mcp_daemon.py
git commit -m "Add MCP pipeline job orchestration"
```

---

### Task 10: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-06-30-translator-mcp-service-design.md` only if implementation changed a public command name

- [ ] **Step 1: Add README MCP usage section**

Add this section after the manual launch instructions in `README.md`:

````markdown
## MCP-сервер для AI-клиентов

translatorFork_MOD может запускать локальный MCP-сервер, чтобы Codex, Claude Desktop, Antigravity и другие MCP-совместимые клиенты могли стартовать долгие AI-задачи переводчика без передачи текста книги обратно в чат.

Показать конфиг для ручного подключения:

```bash
python -m gemini_translator.mcp config --client generic
```

Запустить MCP stdio-сервер вручную:

```bash
python -m gemini_translator.mcp server
```

Проверить daemon:

```bash
python -m gemini_translator.mcp daemon status
```

MCP tools возвращают `job_id`, статус, хвост логов и пути к файлам. Полные результаты переводов, глоссариев и проверок сохраняются на диск в проекте и в служебной папке `~/.translatorFork/mcp/`.
````

- [ ] **Step 2: Run focused MCP tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_mcp_jobs.py tests/test_mcp_commands.py tests/test_mcp_worker.py tests/test_mcp_daemon.py tests/test_mcp_server.py tests/test_mcp_client_install.py -q
```

Expected: PASS.

- [ ] **Step 3: Run existing CLI regression tests**

Run:

```bash
GT_DISABLE_LOCAL_MODEL_DISCOVERY=1 .venv/bin/python -m pytest tests/test_cli_tools.py -q
```

Expected: PASS.

- [ ] **Step 4: Smoke test config command**

Run:

```bash
.venv/bin/python -m gemini_translator.mcp config --client codex
```

Expected: stdout contains `[mcp_servers.translatorFork]`, `command =`, and `gemini_translator.mcp`.

- [ ] **Step 5: Smoke test daemon status failure path**

Run:

```bash
TRANSLATOR_MCP_STATE_DIR=/tmp/translator-mcp-empty .venv/bin/python -m gemini_translator.mcp daemon status
```

Expected: exit code `1` and JSON containing `"ok": false` and `"daemon is not running"`.

- [ ] **Step 6: Commit docs**

Run:

```bash
git add README.md
git commit -m "Document translator MCP server usage"
```

- [ ] **Step 7: Final git status check**

Run:

```bash
git status --short
```

Expected: no output.

---

## Self-Review Checklist

- Spec coverage: Tasks 1-6 cover daemon foundation and durable jobs; Task 7 covers MCP stdio tools; Task 8 covers client installer; Task 9 covers full pipeline and glossary-correction unsupported response; Task 10 covers docs and verification. The future GUI-connected agent bridge remains deliberately outside this implementation plan.
- Placeholder scan: Search this plan for the banned marker words listed in the writing-plans skill. The only match should be this checklist sentence if the search query includes the word `placeholder`.
- Type consistency: Use `JobRecord`, `BuiltCommand`, `McpDaemon`, `DaemonClient`, and `McpStdioServer` exactly as named here across tasks.
