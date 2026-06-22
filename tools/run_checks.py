from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, command: list[str]) -> int:
    print(f"[checks] {label}", flush=True)
    completed = subprocess.run(command, cwd=PROJECT_ROOT)
    if completed.returncode:
        print(f"[checks] {label} failed with exit code {completed.returncode}", file=sys.stderr)
    return completed.returncode


def _env_release_mode_enabled() -> bool:
    value = (
        os.environ.get("GT_RUN_CHECKS_RELEASE")
        or os.environ.get("GT_RELEASE_METADATA_MODE")
        or ""
    ).strip().lower()
    return value in {"1", "true", "yes", "release", "strict"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run project smoke checks.")
    parser.add_argument(
        "--release",
        action="store_true",
        help="Run release metadata checks in strict release mode.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Run only checks that do not require pytest or project test dependencies.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments forwarded to pytest. Prefix with -- to separate them.",
    )
    args = parser.parse_args(argv)

    release_metadata_command = [sys.executable, "-m", "gemini_translator.scripts.check_release_metadata"]
    if args.release or _env_release_mode_enabled():
        release_metadata_command.append("--release")

    checks = [
        (
            "release metadata",
            release_metadata_command,
        )
    ]

    if not args.skip_tests:
        pytest_args = list(args.pytest_args)
        if pytest_args[:1] == ["--"]:
            pytest_args = pytest_args[1:]
        checks.append(("pytest", [sys.executable, "-m", "pytest", "-q", *pytest_args]))

    for label, command in checks:
        exit_code = _run(label, command)
        if exit_code:
            return exit_code

    print("[checks] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
