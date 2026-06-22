import os
import zipfile

from gemini_translator.cli import (
    _choose_translation_rel_path,
    _collect_untranslated_fix_items,
    _load_translated_chapter_records,
    _safe_settings_for_output,
    _scan_untranslated_records,
    build_parser,
    build_task_plan,
    select_chapters,
)
from gemini_translator.utils.project_manager import TranslationProjectManager


def _build_epub(path):
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
</package>
""",
        )
        epub.writestr("OEBPS/ch1.xhtml", "<html><body><p>One</p></body></html>")
        epub.writestr("OEBPS/ch2.xhtml", "<html><body><p>Two</p></body></html>")


def test_select_chapters_pending_skips_project_map_entries(tmp_path):
    epub_path = tmp_path / "book.epub"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _build_epub(epub_path)

    translated = project_dir / "OEBPS" / "ch1_translated.html"
    translated.parent.mkdir()
    translated.write_text("<html><body><p>One translated</p></body></html>", encoding="utf-8")

    manager = TranslationProjectManager(str(project_dir))
    manager.register_translation(
        "OEBPS/ch1.xhtml",
        "_translated.html",
        os.path.relpath(translated, project_dir).replace("\\", "/"),
    )

    assert select_chapters(str(epub_path), manager, mode="pending") == ["OEBPS/ch2.xhtml"]
    assert select_chapters(str(epub_path), manager, mode="translated") == ["OEBPS/ch1.xhtml"]


def test_build_task_plan_uses_batch_mode(tmp_path):
    epub_path = tmp_path / "book.epub"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _build_epub(epub_path)

    settings = {
        "file_path": str(epub_path),
        "output_folder": str(project_dir),
        "use_batching": True,
        "chunking": False,
        "task_size_limit": 10000,
    }
    chapters = ["OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml"]

    plan = build_task_plan(str(epub_path), chapters, settings, TranslationProjectManager(str(project_dir)))

    assert plan.summary["task_count"] == 1
    assert plan.summary["task_types"] == {"epub_batch": 1}
    assert plan.payloads[0][2] == tuple(chapters)


def test_choose_translation_rel_path_prefers_explicit_suffix():
    versions = {
        "_translated.html": "a.html",
        "_validated.html": "b.html",
    }

    assert _choose_translation_rel_path(versions, "_translated.html") == "a.html"
    assert _choose_translation_rel_path(versions) == "b.html"


def test_safe_settings_masks_active_keys_by_provider():
    safe = _safe_settings_for_output({
        "api_keys": ["abcd1234"],
        "active_keys_by_provider": {
            "gemini": ["full-secret-key"],
            "local": [],
        },
        "custom_prompt": "prompt",
    })

    assert safe["api_keys"] == ["...1234"]
    assert safe["active_keys_by_provider"]["gemini"] == ["...-key"]
    assert "full-secret-key" not in str(safe)
    assert safe["custom_prompt_chars"] == 6


def test_new_cli_commands_parse_common_arguments():
    parser = build_parser()

    args = parser.parse_args(["providers"])
    assert args.func.__name__ == "command_providers"

    args = parser.parse_args(["models", "--provider", "gemini"])
    assert args.func.__name__ == "command_models"
    assert args.provider == "gemini"

    args = parser.parse_args([
        "consistency",
        "--epub", "book.epub",
        "--project", "project",
        "--consistency-mode", "fast",
        "--suffix", "_validated.html",
    ])
    assert args.func.__name__ == "command_consistency"
    assert args.chapters == "translated"
    assert args.suffix == "_validated.html"

    args = parser.parse_args([
        "untranslated-fix",
        "--epub", "book.epub",
        "--project", "project",
        "--dry-run",
    ])
    assert args.func.__name__ == "command_untranslated_fix"
    assert args.dry_run is True


def test_untranslated_scan_reads_project_translations(tmp_path):
    epub_path = tmp_path / "book.epub"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _build_epub(epub_path)

    translated = project_dir / "OEBPS" / "ch1_validated.html"
    translated.parent.mkdir()
    translated.write_text("<html><body><p>Перевод Alpha остался.</p></body></html>", encoding="utf-8")

    manager = TranslationProjectManager(str(project_dir))
    manager.register_translation(
        "OEBPS/ch1.xhtml",
        "_validated.html",
        os.path.relpath(translated, project_dir).replace("\\", "/"),
    )

    records, missing = _load_translated_chapter_records(
        str(epub_path),
        str(project_dir),
        manager,
        ["OEBPS/ch1.xhtml"],
        suffix="_validated.html",
    )
    issues = _scan_untranslated_records(records, word_exceptions=set())

    assert missing == []
    assert records[0]["file"] == str(translated)
    assert issues[0]["chapter"] == "OEBPS/ch1.xhtml"
    assert "Alpha" in issues[0]["untranslated_words"]


def test_untranslated_fix_collector_groups_html_context(tmp_path):
    epub_path = tmp_path / "book.epub"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _build_epub(epub_path)

    translated = project_dir / "OEBPS" / "ch1_validated.html"
    translated.parent.mkdir()
    translated.write_text("<html><body><p>Перевод Alpha остался.</p></body></html>", encoding="utf-8")

    manager = TranslationProjectManager(str(project_dir))
    manager.register_translation(
        "OEBPS/ch1.xhtml",
        "_validated.html",
        os.path.relpath(translated, project_dir).replace("\\", "/"),
    )
    records, _ = _load_translated_chapter_records(
        str(epub_path),
        str(project_dir),
        manager,
        ["OEBPS/ch1.xhtml"],
        suffix="_validated.html",
    )

    data_items, soup_cache, scan_issues = _collect_untranslated_fix_items(records, word_exceptions=set())

    assert scan_issues
    assert str(translated) in soup_cache
    assert data_items[0]["internal_html_path"] == "OEBPS/ch1.xhtml"
    assert "Alpha" in data_items[0]["context"]
