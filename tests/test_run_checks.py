import sys
from types import SimpleNamespace

import tools.run_checks as run_checks


def test_run_checks_isolates_mcp_daemon_tests_by_default(monkeypatch):
    commands = []

    def fake_run(command, cwd):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_checks.subprocess, "run", fake_run)

    assert run_checks.main([]) == 0
    assert commands == [
        [sys.executable, "-m", "gemini_translator.scripts.check_release_metadata"],
        [sys.executable, "-m", "pytest", "-q", "tests/test_mcp_daemon.py"],
        [sys.executable, "-m", "pytest", "-q", "--ignore=tests/test_mcp_daemon.py"],
    ]


def test_run_checks_keeps_explicit_pytest_args_in_one_process(monkeypatch):
    commands = []

    def fake_run(command, cwd):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_checks.subprocess, "run", fake_run)

    assert run_checks.main(["--", "tests/test_mcp_daemon.py", "-k", "sse"]) == 0
    assert commands == [
        [sys.executable, "-m", "gemini_translator.scripts.check_release_metadata"],
        [sys.executable, "-m", "pytest", "-q", "tests/test_mcp_daemon.py", "-k", "sse"],
    ]
