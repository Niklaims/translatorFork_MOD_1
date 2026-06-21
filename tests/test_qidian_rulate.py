import json

from qidian_rulate.models import QidianBookMetadata
from qidian_rulate import workers
from gemini_translator.ui.dialogs import qidian_rulate_creator as creator_module
from gemini_translator.ui.dialogs.qidian_rulate_creator import QidianRulateCreatorWindow
from qidian_rulate.workers import (
    _is_browser_missing_error,
    _tag_file_candidates,
    RULATE_BOOK_TYPE_DESCRIPTION,
    RULATE_BOOK_TYPE_SELECTOR,
    RULATE_BOOK_TYPE_TITLE,
    RULATE_CATEGORY_URL,
    RULATE_CHINESE_CATEGORY_TITLE,
    RULATE_INFO_URL,
    RULATE_PROFILE_DIR,
    build_ai_prompt,
    normalize_rulate_tags,
    parse_prepared_metadata,
    validate_qidian_url,
)


FANTASY = "\u0444\u044d\u043d\u0442\u0435\u0437\u0438"
MYSTIC = "\u043c\u0438\u0441\u0442\u0438\u043a\u0430"
ADVENTURE = "\u043f\u0440\u0438\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f"


class _QidianCreatorHarness:
    _return_to_menu = QidianRulateCreatorWindow._return_to_menu

    def __init__(self, handler=None):
        self._return_to_menu_handler = handler
        self.calls = []

    def hide(self):
        self.calls.append("hide")

    def close(self):
        self.calls.append("close")


def test_validate_qidian_url_accepts_book_links_only():
    assert validate_qidian_url("https://www.qidian.com/book/1041604040/")
    assert validate_qidian_url("http://qidian.com/book/1041604040")
    assert validate_qidian_url("https://www.qidian.com/book/1041604040/?source=m")
    assert not validate_qidian_url("https://www.qidian.com/author/4362948/")
    assert not validate_qidian_url("https://www.qidian.com/book/1041604040/catalog/")
    assert not validate_qidian_url("https://example.com/book/1041604040/")


def test_qidian_rulate_profile_is_separate_from_ranobelib_uploader():
    assert ".qidian_rulate_creator" in str(RULATE_PROFILE_DIR)
    assert ".ranobelib_uploader" not in str(RULATE_PROFILE_DIR)


def test_tag_file_candidates_use_program_area(monkeypatch):
    monkeypatch.delenv("RULATE_TAGS_FILE", raising=False)

    candidates = list(_tag_file_candidates())
    candidate_strings = [str(path).lower() for path in candidates]

    assert any("qidian_rulate" in path and path.endswith("tags.txt") for path in candidate_strings)
    assert not any(
        path.name.lower() == "tags.txt" and path.parent.name.lower() == "downloads"
        for path in candidates
    )


def test_rulate_fill_uses_category_page_before_info_page():
    assert RULATE_CATEGORY_URL == "https://tl.rulate.ru/book/0/edit/cat"
    assert RULATE_BOOK_TYPE_TITLE == "Книга"
    assert RULATE_BOOK_TYPE_DESCRIPTION == "Публикуйте свои произведения"
    assert RULATE_BOOK_TYPE_SELECTOR == 'a.create-card.card-book[href*="typ=A"]'
    assert RULATE_CHINESE_CATEGORY_TITLE == "Китайские"
    assert RULATE_INFO_URL == "https://tl.rulate.ru/book/0/edit/info#general"


def test_qidian_creator_return_to_menu_closes_before_handler():
    handler_calls = []
    harness = _QidianCreatorHarness(handler=lambda: handler_calls.append("handler"))

    harness._return_to_menu()

    assert harness.calls == ["hide", "close"]
    assert handler_calls == ["handler"]


def test_qidian_creator_return_to_menu_without_handler_closes_then_reboots(monkeypatch):
    reboot_calls = []
    monkeypatch.setattr(creator_module, "return_to_main_menu", lambda: reboot_calls.append("menu"))
    harness = _QidianCreatorHarness()

    harness._return_to_menu()

    assert harness.calls == ["close"]
    assert reboot_calls == ["menu"]


def test_parse_prepared_metadata_strips_json_fence_and_normalizes_lists(monkeypatch):
    allowed_tags = [
        "sci-fi",
        "\u0442\u0430\u0439\u043d\u044b",
        "\u043c\u0438\u0441\u0442\u0438\u043a\u0430",
        "\u043f\u0443\u0442\u0435\u0448\u0435\u0441\u0442\u0432\u0438\u0435 \u0432 \u0434\u0440\u0443\u0433\u043e\u0439 \u043c\u0438\u0440",
    ]
    monkeypatch.setattr(workers, "load_rulate_tags", lambda: allowed_tags)
    payload = {
        "english_title": "Otherworldly Inn",
        "translated_title": "\u0418\u043d\u043e\u043c\u0435\u0440\u043d\u0430\u044f \u0433\u043e\u0441\u0442\u0438\u043d\u0438\u0446\u0430",
        "translated_description": "\u0422\u0435\u043a\u0441\u0442\n\n\n\u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f",
        "genres": [FANTASY.upper(), MYSTIC, "unknown"],
        "tags": [
            "SCI-FI",
            "\u0422\u0430\u0439\u043d\u044b",
            "\u043d\u0435\u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u044e\u0449\u0438\u0439 \u0442\u0435\u0433",
        ],
    }
    prepared = parse_prepared_metadata(f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```")

    assert prepared.english_title == "Otherworldly Inn"
    assert prepared.translated_title
    assert prepared.translated_description == "\u0422\u0435\u043a\u0441\u0442\n\n\u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f"
    assert prepared.genres[:3] == [FANTASY, MYSTIC, ADVENTURE]
    assert prepared.tags[:3] == [
        "sci-fi",
        "\u0442\u0430\u0439\u043d\u044b",
        "\u043c\u0438\u0441\u0442\u0438\u043a\u0430",
    ]


def test_normalize_rulate_tags_requires_tags_from_allowed_file(monkeypatch):
    allowed_tags = ["sci-fi", "\u0442\u0430\u0439\u043d\u044b", "\u043c\u0438\u0441\u0442\u0438\u043a\u0430"]
    monkeypatch.setattr(workers, "load_rulate_tags", lambda: allowed_tags)

    tags = normalize_rulate_tags(["SCI-FI", "\u0447\u0443\u0436\u043e\u0439 \u0442\u0435\u0433"])

    assert tags == ["sci-fi", "\u043c\u0438\u0441\u0442\u0438\u043a\u0430", "\u0442\u0430\u0439\u043d\u044b"]


def test_build_ai_prompt_contains_source_context_and_description_rule():
    metadata = QidianBookMetadata(
        source_url="https://www.qidian.com/book/1041604040/",
        title_original="\u5f02\u5ea6\u65c5\u793e",
        author_name="\u8fdc\u77b3",
        description="\u63cf\u8ff0",
    )

    prompt = build_ai_prompt(metadata, "Otherworldly Inn")

    assert "\u5f02\u5ea6\u65c5\u793e" in prompt
    assert "\u8fdc\u77b3" in prompt
    assert "Otherworldly Inn" in prompt
    assert "\u041d\u0435 \u0432\u0441\u0442\u0430\u0432\u043b\u044f\u0439 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435" in prompt


def test_browser_missing_error_is_detected_for_playwright_install_message():
    error = RuntimeError(
        "BrowserType.launch: Executable doesn't exist at "
        "C:\\Users\\test\\AppData\\Local\\ms-playwright\\chromium_headless_shell-1223\\chrome.exe\n"
        "Looks like Playwright was just installed or updated. Please run: playwright install"
    )

    assert _is_browser_missing_error(error)
