"""Named palettes cover native Tk colors and CTk's default widget colors."""

import tkinter as tk
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import customtkinter as ctk

from cardtable import Image, Text
from cardtable.widgets import theme


class ThemeTest(unittest.TestCase):
    def setUp(self):
        colors = {
            name: deepcopy(getattr(theme, name)) for name in theme.DEFAULT_DARK.colors
        }
        ctk_colors = deepcopy(ctk.ThemeManager.theme)
        mode = ctk.get_appearance_mode()

        def restore():
            for name, color in colors.items():
                setattr(theme, name, color)
            ctk.ThemeManager.theme = ctk_colors
            ctk.set_appearance_mode(mode)

        self.addCleanup(restore)

    def test_switching_presets_resets_ctk_overrides_and_native_colors(self):
        custom = replace(
            theme.DEFAULT_DARK,
            colors={**theme.DEFAULT_DARK.colors, "TEXT_FONT_COLOR": "#123456"},
            ctk_colors={"CTkEntry": {"fg_color": "#234567"}},
        )
        theme.apply(custom)
        self.assertEqual(ctk.get_appearance_mode(), "Dark")
        self.assertEqual(theme.color(theme.TEXT_FONT_COLOR), "#123456")
        self.assertEqual(ctk.ThemeManager.theme["CTkEntry"]["fg_color"], "#234567")
        theme.apply(theme.resolve("DEFAULT_LIGHT"))
        self.assertEqual(ctk.get_appearance_mode(), "Light")
        self.assertEqual(theme.color(theme.TEXT_FONT_COLOR), "#1f1f1f")
        self.assertNotEqual(ctk.ThemeManager.theme["CTkEntry"]["fg_color"], "#234567")
        theme.apply(theme.resolve("DEFAULT_DARK"))
        for name, color in theme.DEFAULT_DARK.colors.items():
            self.assertEqual(getattr(theme, name), color)

    def test_incomplete_palettes_are_rejected_before_ui_startup(self):
        for invalid in (
            replace(theme.DEFAULT_DARK, colors={}),
            replace(theme.DEFAULT_DARK, appearance_mode="System"),
        ):
            with patch.dict(theme.THEMES, {"INVALID": invalid}):
                with self.assertRaises(ValueError):
                    theme.resolve("INVALID")

    def test_custom_palette_reaches_real_controls_and_native_renderers(self):
        theme.apply(
            replace(
                theme.DEFAULT_DARK,
                colors={
                    **theme.DEFAULT_DARK.colors,
                    "TEXT_FONT_COLOR": "#123456",
                    "IMAGE_PADDING_COLOR": "#345678",
                    "COPY_ICON_COLOR": "#456789",
                },
                ctk_colors={"CTkEntry": {"fg_color": "#234567"}},
            )
        )
        try:
            root = ctk.CTk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.addCleanup(root.destroy)
        entry = ctk.CTkEntry(root)
        self.assertEqual(entry.cget("fg_color"), "#234567")
        image = Image()._create_renderer(root)
        self.assertEqual(image._label.cget("background"), "#345678")
        text = Text()._create_renderer(root)
        self.assertEqual(text._text_widget.cget("foreground"), "#123456")
