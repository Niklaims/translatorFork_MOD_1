import sys
from types import SimpleNamespace

import tools.run_checks as run_checks


def test_skip_tests_still_runs_ruff_runtime_safety(monkeypatch):
    """--skip-tests описан как флаг, отключающий только проверки, требующие
    pytest/тестовых зависимостей. "ruff runtime safety" — статический линт,
    pytest ему не нужен, поэтому он должен выполняться и при --skip-tests;
    выключаться должен только сам pytest."""
    commands = []

    def fake_run(command, cwd, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(run_checks.subprocess, "run", fake_run)

    assert run_checks.main(["--skip-tests"]) == 0
    assert commands == [
        [sys.executable, "-m", "gemini_translator.scripts.check_release_metadata"],
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            ".",
            "--select",
            run_checks.RUFF_RUNTIME_RULES,
        ],
    ]
