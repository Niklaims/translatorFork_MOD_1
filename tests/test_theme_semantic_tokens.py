# tests/test_theme_semantic_tokens.py
import re
import unittest

import pytest
from PyQt6 import QtWidgets

from gemini_translator.ui import themes
from gemini_translator.ui import theme_manager as tm


def _pal(window_bg):
    return themes.build_theme_palette(
        {"window_bg": window_bg, "panel_bg": window_bg, "accent": "#d87a3a"}
    )


def test_semantic_tokens_present():
    pal = _pal("#0f141b")
    for key in ("success", "warning", "danger", "info"):
        assert key in pal and pal[key].startswith("#")


def test_status_tokens_adapt_to_base_lightness():
    dark = _pal("#0f141b")
    light = _pal("#f4f4f6")
    # On a dark window the success green is lighter than on a light window.
    assert themes._luminance(dark["success"]) > themes._luminance(light["success"])


class PaletteHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_color_reflects_applied_mode(self):
        tm.apply(self.app, mode="light", manual_colors={})
        light_muted = tm.color("text_muted", self.app)
        tm.apply(self.app, mode="dark", manual_colors={})
        dark_muted = tm.color("text_muted", self.app)
        self.assertTrue(light_muted.startswith("#") and dark_muted.startswith("#"))
        self.assertNotEqual(light_muted, dark_muted)

    def test_color_has_semantic_tokens_and_fallback(self):
        tm.apply(self.app, mode="dark", manual_colors={})
        self.assertTrue(tm.color("success", self.app).startswith("#"))
        # Unknown token returns a safe fallback string, not a crash.
        self.assertIsInstance(tm.color("does_not_exist", self.app), str)


_SCHEMES = {
    "light": themes.LIGHT_DEFAULT_THEME_COLORS,
    "dark": themes.DARK_DEFAULT_THEME_COLORS,
}


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _over(color: str, surface: str) -> tuple[int, int, int]:
    """Blend an rgba() token over an opaque surface, the way the screen shows it."""
    match = re.fullmatch(r"rgba\((\d+), (\d+), (\d+), ([0-9.]+)\)", color)
    if match is None:
        return _rgb(color)
    alpha = float(match.group(4))
    under = _rgb(surface)
    return tuple(
        round(alpha * int(match.group(index + 1)) + (1 - alpha) * under[index])
        for index in range(3)
    )


def _ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    """WCAG 2.x contrast ratio, written independently of themes.py."""

    def luminance(rgb):
        def channel(value):
            scaled = value / 255
            return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4

        red, green, blue = (channel(value) for value in rgb)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("scheme", sorted(_SCHEMES))
@pytest.mark.parametrize("tone", ["success", "warning", "danger"])
@pytest.mark.parametrize("surface", ["panel_bg", "list_bg", "list_alt_bg"])
def test_status_text_reads_on_its_soft_background(scheme, tone, surface):
    """Фишка статуса и опасная кнопка — не ниже 4.5:1 в обеих темах."""
    palette = themes.build_theme_palette(_SCHEMES[scheme])

    background = _over(palette[f"{tone}_soft_bg"], palette[surface])

    assert _ratio(_rgb(palette[f"{tone}_text"]), background) >= 4.5


@pytest.mark.parametrize("scheme", sorted(_SCHEMES))
def test_the_danger_button_still_reads_under_the_pointer(scheme):
    palette = themes.build_theme_palette(_SCHEMES[scheme])

    background = _over(palette["danger_hover_bg"], palette["panel_bg"])

    assert _ratio(_rgb(palette["danger_text"]), background) >= 4.5


@pytest.mark.parametrize("scheme", sorted(_SCHEMES))
def test_a_neutral_chip_reads(scheme):
    palette = themes.build_theme_palette(_SCHEMES[scheme])

    assert _ratio(_rgb(palette["text_secondary"]), _rgb(palette["chip_bg"])) >= 4.5


def test_the_dark_theme_keeps_the_status_colours_that_already_read():
    """Тёмная тема и так читалась: зелёный и жёлтый там не сдвигаются.

    The danger text is left out on purpose: it must also read on the stronger
    fill under the pointer, and the dark theme's red does not reach 4.5:1 there.
    """
    palette = themes.build_theme_palette(themes.DARK_DEFAULT_THEME_COLORS)

    for tone in ("success", "warning"):
        assert palette[f"{tone}_text"] == palette[tone]


def test_the_danger_button_and_the_status_chip_are_built_from_tokens():
    palette = themes.build_theme_palette(themes.LIGHT_DEFAULT_THEME_COLORS)
    sheet = themes.build_stylesheet(themes.LIGHT_DEFAULT_THEME_COLORS)

    danger = sheet.split("QPushButton#dangerActionButton {", 1)[1].split("}", 1)[0]
    assert palette["danger_soft_bg"] in danger
    assert palette["danger_text"] in danger
    assert "#412026" not in sheet
    assert "QPushButton#dangerActionButton:disabled" in sheet
    success = sheet.split('QLabel#statusChip[tone="success"] {', 1)[1].split("}", 1)[0]
    assert palette["success_text"] in success
    assert "__SUCCESS_TEXT__" not in sheet and "__DANGER_HOVER_BG__" not in sheet


ROW_STATUS_TONES = ("success", "warning", "danger", "info", "pending")


@pytest.mark.parametrize("scheme", sorted(_SCHEMES))
@pytest.mark.parametrize("tone", ROW_STATUS_TONES)
@pytest.mark.parametrize("surface", ["list_bg", "list_alt_bg"])
def test_row_text_reads_on_every_row_status_fill(scheme, tone, surface):
    """Строка таблицы со статусом: обычный текст на её заливке не ниже 4.5:1."""
    palette = themes.build_theme_palette(_SCHEMES[scheme])

    background = _over(palette[f"{tone}_row_bg"], palette[surface])

    assert _ratio(_rgb(palette["text_primary"]), background) >= 4.5
