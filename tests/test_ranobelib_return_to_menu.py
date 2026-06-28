import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TESTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
RANOBELIB_DIR = os.path.join(PROJECT_ROOT, "ranobelib")

if RANOBELIB_DIR not in sys.path:
    sys.path.insert(0, RANOBELIB_DIR)

from main_window import RanobeUploaderApp


class _RanobeUploaderHarness:
    _return_to_menu = RanobeUploaderApp._return_to_menu

    def __init__(self, handler=None):
        self._return_to_menu_handler = handler
        self.calls = []

    def _save_settings(self):
        self.calls.append("save")

    def hide(self):
        self.calls.append("hide")

    def close(self):
        self.calls.append("close")


class _Field:
    def __init__(self, value=""):
        self._value = value

    def text(self):
        return self._value

    def setText(self, value):
        self._value = value

    def clear(self):
        self._value = ""

    def toPlainText(self):
        return self._value

    def setPlainText(self, value):
        self._value = value


class _SettingsStub:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, fallback=None, type=None):
        return self.values.get(key, fallback)

    def setValue(self, key, value):
        self.values[key] = value


class _RanobeMediaMetadataHarness:
    _apply_rulate_media_metadata = RanobeUploaderApp._apply_rulate_media_metadata
    _settings_text = RanobeUploaderApp._settings_text
    _media_translator_team_text = RanobeUploaderApp._media_translator_team_text

    def __init__(self, translator_team="", saved_team=""):
        self.settings = _SettingsStub({"media_translator_team": saved_team})
        self._rulate_media_metadata = {}
        self.logs = []
        self.saved = False
        self.media_rulate_url_input = _Field()
        self.media_title_ru_edit = _Field()
        self.media_original_title_edit = _Field()
        self.media_alt_hieroglyph_edit = _Field()
        self.media_title_en_edit = _Field()
        self.media_alt_names_edit = _Field()
        self.media_author_edit = _Field()
        self.media_publisher_edit = _Field()
        self.media_translator_team_edit = _Field(translator_team)
        self.media_cover_url_edit = _Field()
        self.media_year_edit = _Field()
        self.media_description_edit = _Field()
        self.media_rulate_genres_edit = _Field()
        self.media_rulate_tags_edit = _Field()
        self.media_genres_edit = _Field("old genres")
        self.media_tags_edit = _Field("old tags")
        self.media_status_combo = object()

    def _refresh_media_cover_preview(self):
        pass

    def _set_combo_data(self, combo, value):
        self.combo_value = value

    def _save_rulate_media_state(self, sync=False):
        self.saved = sync

    def _process_log(self, process_key, level, message):
        self.logs.append((process_key, level, message))


class RanobeUploaderReturnToMenuTests(unittest.TestCase):
    def test_return_to_menu_closes_window_before_handler(self):
        handler_calls = []

        harness = _RanobeUploaderHarness(
            handler=lambda: handler_calls.append("handler")
        )

        harness._return_to_menu()

        self.assertEqual(harness.calls, ["save", "hide", "close"])
        self.assertEqual(handler_calls, ["handler"])

    def test_return_to_menu_without_handler_just_closes_window(self):
        harness = _RanobeUploaderHarness()

        harness._return_to_menu()

        self.assertEqual(harness.calls, ["save", "close"])

    def test_rulate_media_metadata_preserves_saved_translator_team_when_new_metadata_is_empty(self):
        harness = _RanobeMediaMetadataHarness(translator_team="Required Team")

        harness._apply_rulate_media_metadata(
            {
                "rulate_edit_url": "https://tl.rulate.ru/book/123/edit/info",
                "title_ru": "Новая новелла",
                "source_url": "https://www.qidian.com/book/1041604040/",
            }
        )

        self.assertEqual(harness.media_translator_team_edit.text(), "Required Team")
        self.assertEqual(harness.settings.values["media_translator_team"], "Required Team")
        self.assertEqual(harness._rulate_media_metadata["translator_team"], "Required Team")


if __name__ == "__main__":
    unittest.main()
