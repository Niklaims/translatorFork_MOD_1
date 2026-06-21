from gemini_translator.ui.dialogs.validation import (
    ValidationThread,
    ai_repair_candidate_warning,
    apply_line_review_selection,
    build_line_review_segments,
    should_auto_accept_line_review_change,
)
from gemini_translator.utils.text import (
    escape_stray_angle_brackets,
    find_stray_angle_bracket_snippets,
    find_unwrapped_body_text_snippets,
    is_well_formed_xml,
    repair_ai_html_artifacts,
)


def _worker():
    return ValidationThread(
        translated_folder="",
        original_epub_path="",
        checks_config={},
        word_exceptions_set=set(),
        project_manager=None,
    )


def test_escape_stray_angle_brackets_preserves_real_tags():
    html = '<body><p>2 < 3 and 5 > 4</p><a href="notes.xhtml#n1">note</a></body>'

    repaired = escape_stray_angle_brackets(html)

    assert '<body><p>' in repaired
    assert '<a href="notes.xhtml#n1">note</a>' in repaired
    assert '2 &lt; 3 and 5 &gt; 4' in repaired


def test_repair_ai_html_artifacts_wraps_body_text_and_escapes_angles():
    original = '<html><body><p>One.</p><p>Two.</p></body></html>'
    translated = '<html><body><p>One < stray ></p>Loose text<p>Two ></p></body></html>'

    repaired = repair_ai_html_artifacts(original, translated)

    assert is_well_formed_xml(repaired)
    assert '<p>One &lt; stray &gt;</p>' in repaired
    assert '<p>Loose text</p>' in repaired
    assert '<p>Two &gt;</p>' in repaired
    assert find_unwrapped_body_text_snippets(repaired) == []
    assert find_stray_angle_bracket_snippets(repaired) == []


def test_validation_analysis_flags_stray_angle_brackets():
    result = {
        "path": "Text/chapter.xhtml",
        "internal_html_path": "Text/chapter.xhtml",
    }
    original = '<html><body><p>One.</p></body></html>'
    translated = '<html><body><p>One > Two.</p></body></html>'

    analyzed = _worker()._analyze_html_content(original, translated, result)

    assert "stray_angle_brackets" in analyzed["structural_errors"]


def test_line_review_selection_can_accept_single_changed_line():
    old_html = "<body>\n<p>2 < 3</p>\nLoose text\n</body>\n"
    new_html = "<body>\n<p>2 &lt; 3</p>\n<p>Loose text</p>\n</body>\n"

    segments, changes = build_line_review_segments(old_html, new_html)

    assert len(changes) == 2
    accepted_ids = {changes[0]["id"]}
    selected_html = apply_line_review_selection(segments, accepted_ids)

    assert "<p>2 &lt; 3</p>" in selected_html
    assert "Loose text\n" in selected_html
    assert "<p>Loose text</p>" not in selected_html


def test_line_review_selection_accepts_insert_and_rejects_delete():
    old_html = "<body>\n<p>Keep.</p>\n<p>Remove.</p>\n</body>\n"
    new_html = "<body>\n<p>Keep.</p>\n<p>Added.</p>\n</body>\n"

    segments, changes = build_line_review_segments(old_html, new_html)
    accepted_ids = {change["id"] for change in changes if change["new_text"] and "Added" in change["new_text"]}
    selected_html = apply_line_review_selection(segments, accepted_ids)

    assert "<p>Added.</p>" in selected_html
    assert "<p>Remove.</p>" not in selected_html


def test_line_review_splits_minified_body_without_deleting_unchanged_paragraphs():
    old_html = "<body>\n<h1>Title</h1>\n<p>Keep.</p>\n<p>Also keep.</p>\n</body>\n"
    new_html = "<body><h1>Title</h1><p>Keep.</p><p>Also keep.</p><p>Added.</p></body>"

    _segments, changes = build_line_review_segments(old_html, new_html)

    assert any(change["kind"] == "insert" and "Added" in (change["new_text"] or "") for change in changes)
    assert not any(change["kind"] == "delete" and "Keep" in (change["old_text"] or "") for change in changes)


def test_line_review_does_not_auto_accept_deletions():
    change = {
        "kind": "delete",
        "old_text": "<p>Normal paragraph.</p>\n",
        "new_text": None,
    }

    assert not should_auto_accept_line_review_change(change)


def test_line_review_selection_uses_manual_edit_text():
    old_html = "<body>\n<p>Bad.</p>\n</body>\n"
    new_html = "<body>\n<p>Good.</p>\n</body>\n"

    segments, changes = build_line_review_segments(old_html, new_html)
    replace_change = next(change for change in changes if change["kind"] == "replace")
    selected_html = apply_line_review_selection(
        segments,
        {replace_change["id"]},
        {replace_change["id"]: "<p>Manual.</p>\n"},
    )

    assert "<p>Manual.</p>" in selected_html
    assert "<p>Good.</p>" not in selected_html


def test_ai_repair_candidate_warning_flags_large_text_loss():
    original = "<body>" + "".join(f"<p>Visible paragraph {idx} with text.</p>" for idx in range(8)) + "</body>"
    repaired = "<body><p>Visible paragraph 1 with text.</p></body>"

    assert ai_repair_candidate_warning(original, repaired)
