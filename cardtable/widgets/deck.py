"""Shared configuration for the application window hosted by the UI process."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from threading import RLock
from typing import TYPE_CHECKING

from . import theme as themes
from ._geometry import (
    DEFAULT_GEOMETRY_UNIT,
    DEFAULT_GRID_ASPECT,
    DEFAULT_GRID_COLUMNS,
    DEFAULT_WINDOW_WIDTH,
    Geometry,
    normalize_geometry,
    normalize_geometry_unit,
    normalize_grid_aspect,
    normalize_grid_columns,
    normalize_window_width,
)

if TYPE_CHECKING:
    from .card import Card


@dataclass(frozen=True)
class _DeckSettings:
    geometry_unit: str = DEFAULT_GEOMETRY_UNIT
    grid_columns: int = DEFAULT_GRID_COLUMNS
    grid_aspect: tuple[float, float] = DEFAULT_GRID_ASPECT
    window_width: int = DEFAULT_WINDOW_WIDTH
    theme: str = "DEFAULT_DARK"
    theme_definition: themes.Theme | None = None


class Deck:
    """Manage the shared window and its connected Cards.

    The actual CTk window is created and managed in the separate UI process.
    Configuration stays fixed after the first Card, including across UI restarts.
    """

    _lock = RLock()
    _settings = _DeckSettings()
    _frozen = False

    @classmethod
    def disable(cls) -> None:
        """Block mouse/keyboard input to the main window; updates continue.

        Calls nest: each disable() needs a matching enable(). No UI is started.
        Independent popup windows remain interactive.
        """
        from ._runtime import CardRuntime

        CardRuntime.instance().disable_deck()

    @classmethod
    def enable(cls) -> None:
        """Release one disable() request, preserving other outstanding requests."""
        from ._runtime import CardRuntime

        CardRuntime.instance().enable_deck()

    @classmethod
    def print(cls, *values: object, sep: str = " ") -> None:
        """Replace the left status text; line breaks become spaces.

        With no values, clear the text. Before UI startup, retain the text for
        the next window without starting a UI process.
        """
        from ._runtime import CardRuntime

        text = " ".join(sep.join(str(value) for value in values).splitlines())
        CardRuntime.instance().set_status_text(text)

    @classmethod
    def get_cards(cls) -> list[Card]:
        """Return connected Cards in attachment order as a new list.

        Hidden Cards are included; unstarted and stopped Cards are excluded.
        This does not start the UI or wait for rendering to finish.
        """
        from ._runtime import CardRuntime

        return CardRuntime.instance().get_cards()

    @classmethod
    def configure(
        cls,
        *,
        geometry_unit: str | None = None,
        grid_columns: int | None = None,
        grid_aspect: Sequence[float] | None = None,
        window_width: int | None = None,
        theme: str | None = None,
    ) -> None:
        """Update supplied settings; omitted values retain their current defaults.

        Raise RuntimeError if a Card has already been created.
        """
        with cls._lock:
            if cls._frozen:
                raise RuntimeError(
                    "Deck.configure() must be called before creating Cards"
                )
            changes = {}
            if geometry_unit is not None:
                changes["geometry_unit"] = normalize_geometry_unit(geometry_unit)
            if grid_columns is not None:
                changes["grid_columns"] = normalize_grid_columns(grid_columns)
            if grid_aspect is not None:
                changes["grid_aspect"] = normalize_grid_aspect(grid_aspect)
            if window_width is not None:
                changes["window_width"] = normalize_window_width(window_width)
            if theme is not None:
                changes["theme_definition"] = themes.resolve(theme)
                changes["theme"] = theme
            cls._settings = replace(cls._settings, **changes)

    @classmethod
    def _for_card(cls, geometry: Geometry) -> _DeckSettings:
        # Freeze and validate together so configure cannot race Card creation.
        with cls._lock:
            settings = cls._settings
            normalize_geometry(
                geometry,
                unit=settings.geometry_unit,
                grid_columns=settings.grid_columns,
            )
            cls._frozen = True
            return settings

    @classmethod
    def _snapshot(cls) -> _DeckSettings:
        with cls._lock:
            return cls._settings


__all__ = ["Deck"]
