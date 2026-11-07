"""Generic card with heterogeneous elements and input transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextvars import Token
from copy import copy
from queue import Empty, Queue
from threading import RLock
from time import monotonic, sleep
from typing import Any, ClassVar
from uuid import uuid4

import customtkinter as ctk
from typing_extensions import Self

from cardtable.core.closure import Closure

from .._geometry import (
    DEFAULT_GRID_GEOMETRY,
    DEFAULT_PIXEL_GEOMETRY,
    normalize_geometry,
)
from .._layout import LayoutOwner, current_layout, element_padding
from .._runtime import CardRuntime
from .._scrolling import update_scrollbar
from ..deck import Deck
from ..elements._input import InputElement
from ..elements.base import DisplayRequest, Element
from ..elements.button import Button, ButtonControl, _BtnPressed

_MISSING = object()


class Card:
    """Collect typed element references in a vertical layout using ``with``."""

    _class_path: ClassVar[str] = f"{__name__}:Card"
    _latest_only_updates: ClassVar[bool] = True

    # UI-side attributes initialized by _create_ui(), which bypasses __init__.
    _buttons: dict[str, ctk.CTkButton]
    _button_definitions: dict[str, Button]

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        title: str | None,
        *,
        title_bg_color: str | None = None,
        title_font_color: str | None = None,
        border_color: str | None = None,
        runtime: CardRuntime | None = None,
        **ui_options: Any,
    ) -> None:
        self._display_values: dict[str, Any] = {}
        self._state_lock = RLock()
        self.name = title
        self.widget_id = uuid4().hex
        for option in (
            "geometry_unit",
            "grid_columns",
            "grid_aspect",
            "window_width",
            "theme",
        ):
            if option in ui_options:
                raise TypeError(f"configure {option} using Deck.configure()")
        self._deck_settings = Deck._for_card((x, y, w, h))
        self._geometry = self._normalize_geometry((x, y, w, h))
        self._ui_options = dict(ui_options, show_on_create=True)
        for option, color in (
            ("title_bg_color", title_bg_color),
            ("title_font_color", title_font_color),
            ("border_color", border_color),
        ):
            if color is not None:
                if not isinstance(color, str):
                    raise TypeError(f"{option} must be a Tk color string or None")
                self._ui_options[option] = color
        if self._geometry is not None:
            self._ui_options["geometry"] = self._geometry

        self._runtime = runtime or CardRuntime.instance()
        self._started = False
        self._latest_payload: Any = _MISSING
        self._input_queue: Queue[Any] = Queue()
        self._close_handler: Callable[[], None] | None = None
        self._button_triggers: dict[str, ButtonControl] = {}
        self._elements: dict[str, Any] = {}
        self._elements_by_name: dict[str, Element] = {}
        self._values: dict[str, Any] = {}
        self._element_states: dict[str, dict[str, Any]] = {}

        self._buttons_by_id: dict[str, Button] = {}

        self._install_elements(())
        self._layout_token: Token[LayoutOwner | None] | None = None
        self._declarations: list[Any] = []
        self._layout_defined = False
        Closure.add(self)

    def __enter__(self) -> Self:
        with self._state_lock:
            if self._started or self._layout_token is not None or self._layout_defined:
                raise RuntimeError("card layout can only be defined once, before start")
            if self.elements or self._ui_options["elements"]:
                raise RuntimeError(
                    "cannot combine explicit elements with a Card context"
                )
            self._declarations = []
            self._layout_token = current_layout.set(self)
            return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        with self._state_lock:
            if self._layout_token is None:
                raise RuntimeError("card context is not active")
            current_layout.reset(self._layout_token)
            if exc_type is not None:
                self._layout_token = None
                self._declarations = []
                return
            elements: list[Any] = []
            layout: list[int | tuple[int, ...]] = []
            for declaration in self._declarations:
                if isinstance(declaration, tuple):
                    layout.append(
                        tuple(range(len(elements), len(elements) + len(declaration)))
                    )
                    elements.extend(declaration)
                else:
                    layout.append(len(elements))
                    elements.append(declaration)
        self._install_elements(tuple(elements))
        with self._state_lock:
            self._ui_options["layout"] = tuple(layout)
            self._layout_token = None
            self._layout_defined = True
            self._declarations = []

    def _declare(self, element: Any) -> None:
        with self._state_lock:
            elements = element if isinstance(element, tuple) else (element,)
            if any(not self._accepts_element(item) for item in elements):
                raise TypeError("Card accepts only Element instances")
            self._declarations.append(element)

    def _install_elements(self, elements: tuple[Any, ...]) -> None:
        self._bind_elements(elements)
        # Encode outside the card lock: custom elements may do expensive work.
        for element in self.elements:
            if not isinstance(element, Button):
                with element._synchronized():
                    self._element_changed(element, element._controller_value())

    def start(self) -> None:
        with self._state_lock:
            if self._started:
                return
        # Deferred recordings change without publishing every input sample.
        # Refresh their initial snapshots outside the Card lock, including on
        # restart, before attach serializes the lightweight UI definitions.
        for element in self.elements:
            if element._deferred_display:
                with element._synchronized():
                    self._element_changed(element, element._controller_value())
        with self._state_lock:
            if self._layout_token is not None:
                raise RuntimeError("finish the Card context before starting it")
            if self._started:
                return

            self._runtime.attach(self)
            self._started = True
            if self._latest_payload is not _MISSING:
                self._runtime.update(self.widget_id, self._latest_payload)

    @staticmethod
    def _accepts_element(element: Any) -> bool:
        return isinstance(element, Element)

    @staticmethod
    def _is_named_element(element: Any) -> bool:
        return isinstance(element, Element)

    def _element_changed(self, element: Element, value: Any) -> None:
        display = self._display_value(element, value)
        with self._state_lock:
            self._values[element.name] = value
            self._display_values[element.name] = display
            self._latest_payload = dict(self._display_values)
            if self._started:
                self._runtime.update(self.widget_id, {element.name: display})

    @staticmethod
    def _display_value(element: Element, value: Any) -> Any:
        return element.display_value(value)

    def _build_ui(self, *args: Any, **kwargs: Any) -> None:
        self._build_controls(*args, **kwargs)

    def _build_element_ui(
        self, parent: Any, element: Any, emit: Callable[[Any], None]
    ) -> None:
        if isinstance(element, Button):
            row = self._row(parent)
            control = element.build_ui(row, emit)
            control.pack(fill="x")
            self._buttons[element.id] = control
            self._button_definitions[element.id] = element
        else:

            def emit_value(value: Any) -> None:
                if not self._applying_update:
                    emit({element.name: value})

            element.build_ui(parent, emit_value)

    def _update_element_value_ui(self, element: Element, value: Any) -> None:
        element.update_ui(value)

    def _bind_elements(self, elements: tuple[Any, ...]) -> None:
        for element in elements:
            if not self._accepts_element(element):
                raise TypeError("card accepts only Element instances")
            if isinstance(element, Button):
                self._add_button(element)
            elif self._is_named_element(element):
                self.add_element(element)
                self._elements_by_name[element.name] = element
                self._values[element.name] = element._controller_value()
                if isinstance(element, InputElement):
                    self._element_states[element.name] = {
                        "state": "normal",
                        "label": element.display_label,
                    }
        self._ui_options["elements"] = tuple(
            element._ui_copy() if isinstance(element, Button) else copy(element)
            for element in elements
        )
        self._ui_options["element_states"] = self._element_states

    def values(self) -> tuple[Any, ...]:
        """Return values in declaration order without exposing transport keys."""
        self._poll_if_started()
        with self._state_lock:
            values = tuple(
                (self._elements[name], value) for name, value in self._values.items()
            )
        return tuple(
            element.get() if element._deferred_display else value
            for element, value in values
        )

    def _set_element_state(
        self,
        element_id: str,
        *,
        state: str,
        label: str | None,
    ) -> None:
        with self._state_lock:
            if not isinstance(element_id, str):
                raise TypeError("element_id must be a string")
            if label is not None and not isinstance(label, str):
                raise TypeError("label must be a string or None")
            is_button = element_id in self._button_triggers
        if is_button:
            self._set_button(element_id, state=state, label=label)
            return
        with self._state_lock:
            element = self._element(element_id)
            current = self._element_states[element.name]
            updated_label = current["label"] if label is None else label
            self._element_states[element.name] = {
                "state": state,
                "label": updated_label,
            }
            self._ui_options["element_states"] = self._element_states
            if self._started:
                self._runtime.update_element(
                    self.widget_id,
                    element.name,
                    state=state,
                    label=updated_label,
                )

    def _element(self, name: str) -> Element:
        if not isinstance(name, str):
            raise TypeError("name must be a string")
        try:
            return self._elements_by_name[name]
        except KeyError:
            raise KeyError(f"unknown input element: {name!r}") from None

    def _receive_input(self, payload: Any, *, _attachment: str | None = None) -> None:
        with self._state_lock:
            if not self._accept_event(_attachment):
                return
            if self._receive_button_press(payload):
                return
            if not isinstance(payload, Mapping) or len(payload) != 1:
                raise ValueError("Card received an invalid input event")
            name, value = next(iter(payload.items()))
            element = self._element(name)
        # Always take Element before Card. Slow validation must not hold the
        # shared card lock or block operations on sibling elements.
        with element._synchronized():
            if isinstance(value, DisplayRequest):
                display = element._display_request(value)
                with self._state_lock:
                    if self._accept_event(_attachment) and self._started:
                        self._runtime.update(self.widget_id, {name: display})
                return
            normalized = element.normalize(value)
            display = self._display_value(element, normalized)
            with self._state_lock:
                if not self._accept_event(_attachment):
                    return
                element._store_normalized(normalized)
                self._values[name] = normalized
                self._display_values[name] = display
                self._latest_payload = dict(self._display_values)
        if isinstance(element, InputElement):
            element._notify_input(normalized)

    def _build_controls(
        self,
        parent: ctk.CTkFrame,
        *,
        emit: Callable[[Any], None],
        elements: Sequence[Element],
        element_states: Mapping[str, Mapping[str, Any]],
        layout: Sequence[int | tuple[int, ...]] | None = None,
        message_dialog: bool = False,
        **_options: Any,
    ) -> None:
        self._emit = emit
        self._applying_update = False
        self._ui_elements = {
            element.name: element
            for element in elements
            if isinstance(element, Element) and not isinstance(element, Button)
        }
        container = ctk.CTkScrollableFrame(
            parent, fg_color="transparent", corner_radius=0, border_width=0
        )
        container._scrollbar.configure(width=6, border_spacing=1)
        container._scrollbar.grid_forget()
        # CTkScrollableFrame exposes its scrolling canvas only internally.
        container._parent_canvas.configure(
            yscrollcommand=lambda first, last: update_scrollbar(
                container._scrollbar, first, last, target=container._parent_canvas
            )
        )
        container.pack(fill="both", expand=True)
        self._container = container

        for item in layout if layout is not None else range(len(elements)):
            if isinstance(item, int):
                self._build_element_ui(container, elements[item], emit)
            else:
                row = ctk.CTkFrame(container, fg_color="transparent")
                row.pack(
                    padx=5, pady=2.5,
                    **({} if message_dialog else {"fill": "x"}),
                )
                for column, index in enumerate(item):
                    row.grid_columnconfigure(
                        column, weight=0 if message_dialog else 1, uniform="row"
                    )
                    cell = ctk.CTkFrame(row, fg_color="transparent")
                    cell.grid(row=0, column=column, sticky="nsew")
                    cell._cardtable_row_cell = True
                    self._build_element_ui(cell, elements[index], emit)
                if message_dialog:
                    buttons = [self._buttons[elements[index].id] for index in item]
                    width = max(
                        button._font.measure(button.cget("text")) for button in buttons
                    ) + 28
                    for button in buttons:
                        button.configure(width=width)

        for element_id, settings in element_states.items():
            self._update_element(
                element_id,
                state=settings["state"],
                label=settings.get("label"),
            )

    @staticmethod
    def _row(parent: Any) -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", **element_padding(parent))
        return row

    def _update_element(
        self, element_id: str, *, state: str, label: str | None
    ) -> None:
        try:
            element = self._ui_elements[element_id]
        except KeyError:
            raise KeyError(f"unknown input element: {element_id!r}") from None
        element.update_state_ui(state, label)

    def _update_ui(self, payload: Any) -> bool:
        if not isinstance(payload, Mapping):
            raise TypeError("Card updates must be a mapping")
        self._applying_update = True
        try:
            for name, value in payload.items():
                try:
                    element = self._ui_elements[name]
                except KeyError:
                    raise KeyError(f"unknown input element: {name!r}") from None
                self._update_element_value_ui(element, value)
        finally:
            self._applying_update = False
        # A response to an outstanding viewport request may arrive after hide.
        # Background display refreshes must not reveal that card again.
        return any(not self._ui_elements[name]._deferred_display for name in payload)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._class_path = f"{cls.__module__}:{cls.__qualname__}"

    def add_element(self, element: Any) -> None:
        """Attach an Element without creating dynamic attributes."""
        if not isinstance(element, Element):
            raise TypeError("card elements must inherit from Element")
        with element._synchronized(), self._state_lock:
            if element.name in self._elements:
                raise ValueError(f"element names must be unique: {element.name!r}")
            element._bind(self)
            self._elements[element.name] = element

    def _add_button(self, button: Button) -> None:
        # Button binding spans two cards when the same Button is reused.
        with button._synchronized(), self._state_lock, Button._binding_lock:
            if button._control is not None:
                raise ValueError("button already belongs to a card")
            self.add_element(button)
            self._values[button.name] = None
            control = ButtonControl(button, owner=self)
            button._control = control
            self._buttons_by_id[button.id] = button
            self._button_triggers[button.id] = control

    @property
    def elements(self) -> tuple[Any, ...]:
        """Elements owned by this card, in declaration order."""
        with self._state_lock:
            return tuple(self._elements.values())

    def get_elements(self) -> list[Element]:
        """Return a new list of owned Elements in declaration order."""
        with self._state_lock:
            return list(self._elements.values())

    @classmethod
    def _create_ui(
        cls,
        parent: Any,
        *,
        emit: Callable[[Any], None],
        **options: Any,
    ) -> Self:
        """Create the UI-side instance without initializing a controller."""
        ui = object.__new__(cls)
        ui._buttons = {}
        ui._button_definitions = {}
        ui._build_ui(parent, emit=emit, **options)
        return ui

    def _set_button(
        self,
        button_id: str,
        *,
        state: str | None = None,
        label: str | None = None,
    ) -> None:
        if not isinstance(button_id, str):
            raise TypeError("button_id must be a string")
        with self._state_lock:
            try:
                button = self._buttons_by_id[button_id]
            except KeyError:
                raise KeyError(f"unknown button: {button_id!r}") from None
        with button._synchronized(), self._state_lock:
            if state is None and label is None:
                raise TypeError("state or label must be specified")
            if state is not None and not isinstance(state, str):
                raise TypeError("button state must be a string or None")
            if state is not None and state not in {"normal", "disabled"}:
                raise ValueError("button state must be 'normal' or 'disabled'")
            if label is not None and not isinstance(label, str):
                raise TypeError("button label must be a string or None")

            changes: dict[str, str] = {}
            if state is not None:
                changes["state"] = state
            if label is not None:
                changes["label"] = label
            for attribute, value in changes.items():
                setattr(button, attribute, value)
            self._replace_button_definition("elements", button)

            if self._started:
                self._runtime.update_button(
                    self.widget_id,
                    button_id,
                    state=button.state,
                    label=button.label,
                )

    def _replace_button_definition(self, option: str, updated: Button) -> None:
        definitions = self._ui_options.get(option)
        if definitions is None:
            return
        ui_button = updated._ui_copy()
        self._ui_options[option] = tuple(
            ui_button
            if isinstance(definition, Button) and definition.id == updated.id
            else definition
            for definition in definitions
        )

    def _update_button(
        self,
        button_id: str,
        *,
        state: str,
        label: str,
    ) -> None:
        """Apply a button update on the UI-side instance."""
        try:
            button = self._buttons[button_id]
        except KeyError:
            raise KeyError(f"unknown button: {button_id!r}") from None
        definition = self._button_definitions[button_id]
        definition.update_state_ui(button, state, label)

    def _button_finished(self, button_id: str) -> None:
        with self._state_lock:
            if self._started:
                self._runtime.button_finished(self.widget_id, button_id)

    def _finish_button_ui(self, button_id: str) -> None:
        definition = self._button_definitions[button_id]
        definition._ui_busy = False
        definition.update_state_ui(
            self._buttons[button_id], definition.state, definition.label
        )

    def wait_ready(self, timeout: float = 10.0) -> None:
        with self._state_lock:
            started = self._started
        if started:
            self._runtime.wait_ready(self.widget_id, timeout=timeout)

    def stop(self) -> None:
        with self._state_lock:
            if not self._started:
                return
            self._runtime.detach(self.widget_id)
            self._started = False

    def poll(self) -> None:
        # Delivery may invoke callbacks that acquire other cards' locks.
        # Never poll while holding this card's state lock.
        self._runtime.poll()
        with self._state_lock:
            if self._started:
                self._runtime.raise_for_widget(self.widget_id)

    def _poll_if_started(self) -> None:
        with self._state_lock:
            started = self._started
        if started:
            self.poll()

    def _accept_event(self, attachment: str | None) -> bool:
        # Called under _state_lock: stop/restart cannot race this check and
        # applying the event. Direct controller-side notifications omit the id.
        return attachment is None or (
            self._started and self._runtime.is_attached(self.widget_id, attachment)
        )

    def show(self) -> None:
        with self._state_lock:
            if self._started:
                self._runtime.set_visibility(self.widget_id, visible=True)
            else:
                self._ui_options["show_on_create"] = True

    def hide(self) -> None:
        with self._state_lock:
            if self._started:
                self._runtime.set_visibility(self.widget_id, visible=False)
            else:
                self._ui_options["show_on_create"] = False

    def _publish(self, payload: Any) -> None:
        """Send display data, retaining the latest value until start."""
        with self._state_lock:
            self._latest_payload = payload
            if self._started:
                self._runtime.update(self.widget_id, payload)

    def _get_input(self, timeout: float | None = None) -> Any:
        """Read input while continuing to route UI-process events."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")

        deadline = None if timeout is None else monotonic() + timeout
        while True:
            self.poll()
            try:
                return self._input_queue.get_nowait()
            except Empty:
                if deadline is not None and monotonic() >= deadline:
                    raise
                sleep(0.01)

    def _get_input_nowait(self) -> Any:
        self.poll()
        return self._input_queue.get_nowait()

    def _receive_button_press(self, payload: Any) -> bool:
        if not isinstance(payload, _BtnPressed):
            return False
        try:
            trigger = self._button_triggers[payload.button_id]
        except KeyError:
            raise ValueError(
                f"{type(self).__name__} received an unknown button event"
            ) from None
        trigger._press()
        return True

    def _set_close_handler(self, handler: Callable[[], None]) -> None:
        with self._state_lock:
            self._close_handler = handler

    def _receive_close_requested(self, *, _attachment: str | None = None) -> None:
        with self._state_lock:
            if not self._accept_event(_attachment):
                return
            close_handler = self._close_handler
        if close_handler is not None:
            close_handler()

    def _receive_geometry(
        self, geometry: tuple[int, int, int, int], *, _attachment: str | None = None
    ) -> None:
        with self._state_lock:
            if self._accept_event(_attachment):
                self._geometry = self._normalize_geometry(geometry)

    def _normalize_geometry(
        self,
        geometry: Sequence[int] | None,
    ) -> tuple[int, int, int, int] | None:
        return normalize_geometry(
            geometry,
            unit=self._deck_settings.geometry_unit,
            grid_columns=self._deck_settings.grid_columns,
        )

    @property
    def geometry_unit(self) -> str:
        return self._deck_settings.geometry_unit

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        """Return current (x, y, width, height), in grid units by default.

        Read pending UI updates after start so dragging and resizing are
        reflected. With geometry_unit="px", values are in pixels instead.
        """
        self._poll_if_started()
        with self._state_lock:
            if self._geometry is not None:
                return self._geometry
            if self._deck_settings.geometry_unit == "grid":
                return DEFAULT_GRID_GEOMETRY
            return DEFAULT_PIXEL_GEOMETRY


__all__ = ["Card"]
