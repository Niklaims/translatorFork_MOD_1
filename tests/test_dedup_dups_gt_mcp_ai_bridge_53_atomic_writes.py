"""Дедуп dups-gt_mcp_ai_bridge-53 (mcp-atomic-write-triplicated), хвост.

ai_bridge.py уже пишет через utils/io_utils.atomic_write_text; jobs.save_job и
client_sessions.McpClientSession.touch держали собственные temp+replace-копии
(без fsync, у сессий — с предсказуемым именем .tmp). Теперь оба места идут
через тот же канонический хелпер.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import gemini_translator.mcp.client_sessions as sessions_mod
import gemini_translator.mcp.jobs as jobs_mod
from gemini_translator.mcp.client_sessions import McpClientSession
from gemini_translator.mcp.jobs import create_job, job_path, load_job


def _spy(calls):
    def atomic_write_text(path, text, **kwargs):
        calls.append((Path(path), text, kwargs))
        Path(path).write_text(text, encoding="utf-8")

    return atomic_write_text


def test_save_job_routes_through_atomic_write_text(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(jobs_mod, "atomic_write_text", _spy(calls))
    job = create_job(tmp_path, "translation", ["python"], project=None, epub=None)
    calls.clear()

    jobs_mod.save_job(tmp_path, job)

    assert [c[0] for c in calls] == [job_path(tmp_path, job.id)]
    assert json.loads(calls[0][1])["id"] == job.id
    assert load_job(tmp_path, job.id).id == job.id


def test_client_session_touch_routes_through_atomic_write_text(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sessions_mod, "atomic_write_text", _spy(calls))
    session = McpClientSession(tmp_path, client_name="MCP client")
    calls.clear()

    session.touch("tools/list")

    assert len(calls) == 1
    path, text, kwargs = calls[0]
    assert path == session.path
    assert json.loads(text)["last_method"] == "tools/list"
    # Прежнее поведение: права 0o600 на POSIX, без chmod на Windows.
    assert kwargs.get("mode") == (None if os.name == "nt" else 0o600)
    assert not list(session.path.parent.glob("*.tmp"))
