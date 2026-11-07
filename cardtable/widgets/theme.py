"""Named palettes selected by Deck.configure(theme="DEFAULT_DARK").

Register Theme definitions in THEMES before configuring the Deck. Explicit
per-element and per-card colors take precedence over the selected palette.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

DEFAULT_GRID_ASPECT = (4, 3)  # Width and height of one grid cell.
DEFAULT_WINDOW_WIDTH = 1280  # Pixel width of a full DEFAULT_GRID_COLUMNS grid.

WINDOW_BG_COLOR = ("#EBEBEB", "#151515")
CARD_BG_COLOR = ("#DBDBDB", "#1C1C1C")
CARD_BORDER_COLOR = ("#A6A6A6", "#363636")
TITLE_BG_COLOR = "#925DD8"
TITLE_FONT_COLOR = ("#1A1A1A", "#DCE4EE")
RESIZE_HANDLE_COLOR = "#FFFFFF"
STATUS_BAR_BG_COLOR = "#151515"
STATUS_BAR_FONT_COLOR = "#666666"
SEPARATOR_COLOR = ("#A6A6A6", "#666666")

BUTTON_BG_COLOR = ("#3B8ED0", "#1F6AA5")
BUTTON_HOVER_COLOR = ("#36719F", "#144870")
BUTTON_FONT_COLOR = "#DCE4EE"
BUTTON_DISABLED_FONT_COLOR = ("gray74", "gray60")
COPY_BUTTON_HOVER_COLOR = ("#e0e0e0", "#383838")

# Material Design palettes: active, hover, disabled backgrounds.
BUTTON_COLOR_PALETTES = {
    "blue": ("#1E88E5", "#1976D2", "#90CAF9"),
    "gray": ("#546E7A", "#455A64", "#B0BEC5"),
    "orange": ("#FB8C00", "#F57C00", "#FFCC80"),
    "red": ("#E53935", "#D32F2F", "#EF9A9A"),
    "green": ("#43A047", "#388E3C", "#A5D6A7"),
}

# Colors used by native Tk widgets and Markdown, outside CTk's theme manager.
TEXT_FONT_COLOR = ("#1f1f1f", "#f0f0f0")
TEXT_SELECTION_COLOR = "#3b82f6"
TEXT_SELECTION_FONT_COLOR = "#ffffff"
TEXT_LINK_COLOR = ("#2563eb", "#60a5fa")
TEXT_CODE_BG_COLOR = ("#e8e8e8", "#303030")
TEXT_CODE_BLOCK_BG_COLOR = ("#eeeeee", "#252525")
TEXT_QUOTE_COLOR = ("#555555", "#b8b8b8")
TEXT_QUOTE_MARKER_COLOR = "#6b7280"
TEXT_RULE_COLOR = "#777777"
TEXT_SYNTAX_COLORS = {
    "syntax_text": TEXT_FONT_COLOR,
    "syntax_key": ("#0550ae", "#7dd3fc"),
    "syntax_string": ("#0a7a33", "#a7f3d0"),
    "syntax_number": ("#953800", "#f0abfc"),
    "syntax_keyword": ("#8250df", "#c4b5fd"),
    "syntax_comment": ("#6e7781", "#9ca3af"),
    "syntax_punctuation": ("#57606a", "#d1d5db"),
    "syntax_error": ("#cf222e", "#f87171"),
}
COPY_ICON_COLOR = ("#555555", "#b8b8b8")
IMAGE_PADDING_COLOR = "black"
FALLBACK_BG_COLOR = ("#f2f2f2", "#242424")


# A theme contains every CardTable color plus optional CTk widget color overrides.
# Copy a preset to THEMES under a new name to add an application-specific theme.
@dataclass(frozen=True)
class Theme:
    """Named palette, appearance mode, and CTk colors (e.g. CTkEntry.fg_color)."""

    colors: dict[str, Any]
    appearance_mode: str = "Dark"
    ctk_colors: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def pop(cls) -> "Theme":
        """Build POP with its palette constants scoped to this theme."""
        # Base colors and shared widget styles belong to this preset.
        black = "#151517"
        dark_gray = "#242325"
        gray = "#54585c"
        light_gray = "#abbec0"
        yellow = "#ffd166"
        light_yellow = "#ffeec5"
        dark_yellow = "#847247"
        green = "#06d6a0"
        pink = "#ef476f"
        white = "#ffffff"
        text = {"text_color": white, "text_color_disabled": "#94b8c3"}
        button = {
            "fg_color": yellow,
            "hover_color": "#05bb8c",
            "border_color": yellow,
            "text_color": black,
            "text_color_disabled": "#507981",
        }
        input_colors = {
            **text,
            "fg_color": black,
            "border_color": gray,
        }
        return cls(
            colors={
                "WINDOW_BG_COLOR": black,
                "CARD_BG_COLOR": dark_gray,
                "CARD_BORDER_COLOR": gray,
                "TITLE_BG_COLOR": light_gray,
                "TITLE_FONT_COLOR": black,
                "RESIZE_HANDLE_COLOR": white,
                "STATUS_BAR_BG_COLOR": black,
                "STATUS_BAR_FONT_COLOR": gray,
                "SEPARATOR_COLOR": gray,
                "BUTTON_BG_COLOR": yellow,
                "BUTTON_HOVER_COLOR": light_yellow,
                "BUTTON_FONT_COLOR": black,
                "BUTTON_DISABLED_FONT_COLOR": "#507981",
                "COPY_BUTTON_HOVER_COLOR": light_gray,
                "BUTTON_COLOR_PALETTES": {
                    "blue": (yellow, "#edbd50", "#a99768"),
                    "gray": ("#6ba99f", "#5a958d", "#507981"),
                    "orange": (yellow, "#edbd50", "#a99768"),
                    "red": (pink, "#d9365c", "#af7b8a"),
                    "green": (green, "#05bb8c", "#6ba99f"),
                },
                "TEXT_FONT_COLOR": white,
                "TEXT_SELECTION_COLOR": pink,
                "TEXT_SELECTION_FONT_COLOR": white,
                "TEXT_LINK_COLOR": yellow,
                "TEXT_CODE_BG_COLOR": black,
                "TEXT_CODE_BLOCK_BG_COLOR": black,
                "TEXT_QUOTE_COLOR": yellow,
                "TEXT_QUOTE_MARKER_COLOR": pink,
                "TEXT_RULE_COLOR": yellow,
                "TEXT_SYNTAX_COLORS": {
                    "syntax_text": white,
                    "syntax_key": "#7dd3fc",
                    "syntax_string": "#a7f3d0",
                    "syntax_number": "#f0abfc",
                    "syntax_keyword": "#c4b5fd",
                    "syntax_comment": "#9ca3af",
                    "syntax_punctuation": "#d1d5db",
                    "syntax_error": "#f87171",
                },
                "COPY_ICON_COLOR": yellow,
                "IMAGE_PADDING_COLOR": black,
                "FALLBACK_BG_COLOR": black,
            },
            ctk_colors={
                "CTk": {"fg_color": black},
                "CTkToplevel": {"fg_color": dark_gray},
                "CTkFrame": {
                    "fg_color": dark_gray,
                    "top_fg_color": dark_gray,
                    "border_color": yellow,
                },
                "CTkButton": button,
                "CTkLabel": {"text_color": white},
                "CTkEntry": {**input_colors, "placeholder_text_color": dark_yellow},
                "CTkCheckBox": {
                    **text,
                    "fg_color": yellow,
                    "hover_color": light_yellow,
                    "border_color": yellow,
                    "checkmark_color": black,
                },
                "CTkSwitch": {
                    **text,
                    "fg_color": black,
                    "progress_color": green,
                    "button_color": yellow,
                    "button_hover_color": light_yellow,
                },
                "CTkRadioButton": {
                    **text,
                    "fg_color": yellow,
                    "hover_color": light_yellow,
                    "border_color": yellow,
                },
                "CTkProgressBar": {
                    "fg_color": black,
                    "progress_color": light_yellow,
                    "border_color": yellow,
                },
                "CTkSlider": {
                    "fg_color": black,
                    "progress_color": light_yellow,
                    "button_color": yellow,
                    "button_hover_color": light_yellow,
                },
                "CTkOptionMenu": {
                    **text,
                    "text_color": black,
                    "fg_color": green,
                    "button_color": "#05bb8c",
                    "button_hover_color": yellow,
                },
                "CTkComboBox": {
                    **input_colors,
                    "button_color": yellow,
                    "button_hover_color": light_yellow,
                },
                "CTkScrollbar": {
                    "button_color": gray,
                    "button_hover_color": light_gray,
                },
                "CTkSegmentedButton": {
                    **text,
                    "text_color": black,
                    "fg_color": dark_gray,
                    "selected_color": green,
                    "selected_hover_color": "#05bb8c",
                    "unselected_color": yellow,
                    "unselected_hover_color": pink,
                },
                "CTkTextbox": {
                    **input_colors,
                    "scrollbar_button_color": gray,
                    "scrollbar_button_hover_color": light_gray,
                },
                "CTkScrollableFrame": {"label_fg_color": dark_gray},
                "DropdownMenu": {
                    "fg_color": black,
                    "hover_color": dark_gray,
                    "text_color": white,
                },
            },
        )


_COLOR_NAMES = tuple(
    name for name in globals() if name.endswith(("_COLOR", "_COLORS", "_PALETTES"))
)
DEFAULT_DARK = Theme({name: deepcopy(globals()[name]) for name in _COLOR_NAMES})
DEFAULT_LIGHT = Theme(
    colors={
        **deepcopy(DEFAULT_DARK.colors),
        "TITLE_FONT_COLOR": "#FFFFFF",
        "RESIZE_HANDLE_COLOR": "#666666",
        "STATUS_BAR_BG_COLOR": "#EBEBEB",
        "STATUS_BAR_FONT_COLOR": "#666666",
    },
    appearance_mode="Light",
)

POP = Theme.pop()

THEMES = {"DEFAULT_DARK": DEFAULT_DARK, "DEFAULT_LIGHT": DEFAULT_LIGHT, "POP": POP}


def resolve(name: str) -> Theme:
    """Validate and snapshot a palette for transport to the UI process."""
    if not isinstance(name, str):
        raise TypeError("theme must be a theme name string")
    if name not in THEMES:
        raise ValueError(f"unknown theme {name!r}; choose from {', '.join(THEMES)}")
    selected = THEMES[name]
    if not isinstance(selected, Theme):
        raise TypeError("THEMES entries must be Theme instances")
    if selected.appearance_mode not in {"Dark", "Light"}:
        raise ValueError("theme appearance_mode must be 'Dark' or 'Light'")
    if selected.colors.keys() != DEFAULT_DARK.colors.keys():
        raise ValueError("theme colors must contain every DEFAULT_DARK color")
    return deepcopy(selected)


def apply(selected: Theme) -> None:
    """Apply a transported palette before constructing any UI widgets."""
    import customtkinter as ctk

    ctk.set_default_color_theme("blue")
    for widget, colors in selected.ctk_colors.items():
        ctk.ThemeManager.theme[widget].update(deepcopy(colors))
    ctk.set_appearance_mode(selected.appearance_mode)
    globals().update(deepcopy(selected.colors))


def color(value: Any) -> str:
    """Resolve a color pair for native Tk widgets."""
    if isinstance(value, (tuple, list)):
        import customtkinter as ctk

        return value[ctk.get_appearance_mode() == "Dark"]
    return value
