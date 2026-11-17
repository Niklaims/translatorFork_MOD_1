from pathlib import Path

from gemini_translator.scripts import check_release_metadata as release_metadata
from gemini_translator.scripts.check_release_metadata import check_release_metadata


def _write_note(project_root: Path, filename: str) -> None:
    notes_dir = project_root / "docs" / "release_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / filename).write_text("# note\n", encoding="utf-8")


def test_release_metadata_check_accepts_current_project():
    assert check_release_metadata() == []


def test_release_metadata_dev_mode_tolerates_missing_release_notes(tmp_path: Path):
    assert check_release_metadata(tmp_path) == []


def test_release_metadata_reads_notes_from_docs_release_notes(monkeypatch, tmp_path: Path):
    _write_note(tmp_path, "v1.2.3.md")
    monkeypatch.setattr(release_metadata, "__version__", "1.2.1")
    monkeypatch.setattr(release_metadata, "APP_VERSION", "V 1.2.1")

    errors = check_release_metadata(tmp_path)

    assert errors == ["Application version '1.2.1' is older than latest release notes v1.2.3."]


def test_release_metadata_release_mode_rejects_dev_version(monkeypatch, tmp_path: Path):
    _write_note(tmp_path, "v1.2.3.md")
    monkeypatch.setattr(release_metadata, "__version__", "1.2.3-dev")
    monkeypatch.setattr(release_metadata, "APP_VERSION", "V 1.2.3-dev")

    errors = check_release_metadata(tmp_path, release=True)

    assert "Release mode requires a final semantic version, got '1.2.3-dev'." in errors


def test_release_metadata_release_mode_requires_matching_release_notes(monkeypatch, tmp_path: Path):
    _write_note(tmp_path, "v1.2.2.md")
    monkeypatch.setattr(release_metadata, "__version__", "1.2.3")
    monkeypatch.setattr(release_metadata, "APP_VERSION", "V 1.2.3")

    errors = check_release_metadata(tmp_path, release=True)

    assert errors == ["Missing release notes for release version v1.2.3."]
