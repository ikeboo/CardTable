"""Value-oriented building blocks used by cards."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from threading import RLock
from typing import Any, Generic, Protocol, TypeVar
from uuid import uuid4

from .._layout import DeclarativeMeta, element_padding

Value = TypeVar("Value")
InputValue = TypeVar("InputValue")
_logger = logging.getLogger(__name__)
_active_operations: ContextVar[tuple[int, ...]] = ContextVar(
    "cardtable_element_operations", default=()
)
_public_operations = frozenset({
    "get", "set", "reset", "append", "extend", "expand", "configure",
    "enable", "disable", "is_enabled", "clear", "flash",
})


def _log_operation(method):
    if getattr(method, "_cardtable_logged", False):
        return method

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        active = _active_operations.get()
        if id(self) in active:
            return method(self, *args, **kwargs)
        level = self._log_levels.get(method.__name__, self._log_level)
        enabled = _logger.isEnabledFor(level)
        if not enabled and not any(
            _logger.isEnabledFor(override) for override in self._log_levels.values()
        ):
            return method(self, *args, **kwargs)
        token = _active_operations.set((*active, id(self)))
        try:
            if enabled:
                _logger.log(
                    level,
                    "Element operation: element_id=%s",
                    self.name,
                    extra={
                        "cardtable_caller": f"{type(self).__name__}.{method.__name__}"
                    },
                )
            return method(self, *args, **kwargs)
        finally:
            _active_operations.reset(token)

    wrapper._cardtable_logged = True
    return wrapper


@dataclass(frozen=True)
class DisplayRequest:
    """Internal UI request, distinct from an element's public input value."""

    width: int
    revision: int
    serial: int


class ElementOwner(Protocol):
    def _element_changed(self, element: Element, value: Any) -> None: ...


class Element(Generic[Value, InputValue], metaclass=DeclarativeMeta):
    """Base class for an independent value owned by at most one card.

    Subclasses only need to define ``initial_value`` and
    ``normalize``.  The base provides the public ``get``/``set`` API and the
    binding hook used by a Card.  This keeps value validation out of card
    implementations and makes new elements small and easy to test.

    ``font_scale`` multiplies Tk's standard font size (default 1.0). Custom
    renderers can use ``_scaled_font()`` when creating CTk text controls.
    """

    __slots__ = (
        "_lock",
        "_owner",
        "_value",
        "_key",
        "_ui",
        "_log_level",
        "_log_levels",
        "font_scale",
    )
    font_scale: float
    _deferred_display = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in _public_operations:
            method = cls.__dict__.get(name)
            if callable(method):
                setattr(cls, name, _log_operation(method))

    def _controller_value(self) -> Any:
        """Cheap value retained by Card; deferred elements own their samples."""
        return self.get()

    def _display_request(self, request: DisplayRequest) -> Any:
        """Produce a self-contained display snapshot for a UI request."""
        raise TypeError("this element does not support display requests")

    def __new__(cls, *args: Any, **kwargs: Any):
        # Subclasses (including slotted dataclasses) need not call super().__init__.
        element = super().__new__(cls)
        object.__setattr__(element, "_lock", RLock())
        object.__setattr__(element, "_owner", None)
        object.__setattr__(element, "_key", uuid4().hex)
        object.__setattr__(element, "_log_level", logging.DEBUG)
        object.__setattr__(element, "_log_levels", {})
        return element

    def __init__(
        self,
        *,
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        pass

    @property
    def name(self) -> str:
        """Private transport key; application code uses the element reference."""
        return self._key

    @property
    def initial_value(self) -> Value:
        raise NotImplementedError

    def normalize(self, value: InputValue) -> Value:
        raise NotImplementedError

    def display_value(self, value: Value) -> Any:
        """Encode a value for UI transport without involving the container."""
        return value

    def build_ui(self, parent: Any, emit: Callable[[Any], None]) -> None:
        """Build in the UI process; override to provide a custom display."""
        import customtkinter as ctk

        self._ui = ctk.CTkLabel(
            parent, text=str(self.get()), anchor="w", font=self._scaled_font()
        )
        self._ui.pack(fill="x", **element_padding(parent))

    def _scaled_font(self, font=None, *, bold: bool = False):
        """Build a UI-only font; native font objects never enter transport state."""
        from ._fonts import ctk_font

        return ctk_font(self.font_scale, font, bold=bold)

    def update_ui(self, value: Any) -> None:
        self._ui.configure(text=str(self.normalize(value)))

    @_log_operation
    def get(self) -> Value:
        with self._operation():
            return self._value

    @_log_operation
    def set(self, value: InputValue) -> None:
        with self._operation():
            self._commit(self.normalize(value))

    @_log_operation
    def reset(self) -> None:
        """Restore the initial value, including an empty image."""
        with self._operation():
            self._commit(self.initial_value)

    @contextmanager
    def _operation(self):
        """Poll before locking; serialize validation, state and publication."""
        owner = self._owner
        if owner is not None and getattr(owner, "_started", False):
            owner.poll()
        with self._synchronized():
            if not hasattr(self, "_value"):
                object.__setattr__(self, "_value", self.initial_value)
            yield

    def _commit(self, normalized: Value) -> None:
        with self._synchronized():
            object.__setattr__(self, "_value", normalized)
            owner = getattr(self, "_owner", None)
            if owner is not None:
                owner._element_changed(self, normalized)

    @property
    def value(self) -> Value:
        return self.get()

    @value.setter
    def value(self, value: InputValue) -> None:
        self.set(value)

    def _bind(self, owner: ElementOwner) -> None:
        # Never replace the element lock when ownership changes. An operation
        # already running on an unbound element must finish before binding it.
        with self._lock:
            current = self._owner
            if current is not None and current is not owner:
                raise ValueError(
                    f"element {self.name!r} already belongs to another card"
                )
            object.__setattr__(self, "_owner", owner)

    def _store(self, value: Any) -> Any:
        """Store a validated UI value without publishing it back to the UI."""
        with self._synchronized():
            normalized = self.normalize(value)
            self._store_normalized(normalized)
            return normalized

    def _store_normalized(self, value: Value) -> None:
        """Store an already validated UI value while holding the element lock."""
        object.__setattr__(self, "_value", value)

    def __getstate__(self) -> dict[str, Any]:
        """Return only data that may cross into the UI process.

        Controller synchronization and ownership are local implementation
        details. In particular, thread locks cannot be pickled by the
        multiprocessing command queue.
        """
        with self._synchronized():
            state = {
                name: value
                for name, value in getattr(self, "__dict__", {}).items()
                if name not in {"_lock", "_owner", "_ui"}
            }
            for cls in type(self).__mro__:
                slots = cls.__dict__.get("__slots__", ())
                if isinstance(slots, str):
                    slots = (slots,)
                for name in slots:
                    if name in {"_lock", "_owner", "_ui", "__dict__", "__weakref__"}:
                        continue
                    if hasattr(self, name):
                        state[name] = getattr(self, name)
            return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        for name, value in state.items():
            object.__setattr__(self, name, value)

    @contextmanager
    def _synchronized(self):
        # Validation and display encoding belong to this element. The owner
        # takes its own short lock only when publishing shared transport state.
        with self._lock:
            yield


__all__ = ["Element"]
