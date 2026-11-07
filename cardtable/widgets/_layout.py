"""Collect declarations without sharing layout state across threads/tasks."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Protocol, TypeVar

from typing_extensions import Self


class LayoutOwner(Protocol):
    def _declare(self, element: Any) -> None: ...


current_layout: ContextVar[LayoutOwner | None] = ContextVar(
    "cardtable_current_layout", default=None
)


Declared = TypeVar("Declared")


class DeclarativeMeta(type):
    @property
    def __signature__(cls):
        from inspect import Parameter, signature

        original = signature(cls.__init__)
        parameters = list(original.parameters.values())[1:]
        if any(parameter.name == "log_level" for parameter in parameters):
            parameters = [
                parameter.replace(default="DEBUG")
                if parameter.name == "log_level" else parameter
                for parameter in parameters
            ]
        else:
            index = next(
                (i for i, p in enumerate(parameters)
                 if p.kind == Parameter.VAR_KEYWORD),
                len(parameters),
            )
            parameters.insert(index, Parameter(
                "log_level", kind=Parameter.KEYWORD_ONLY,
                default="DEBUG", annotation=str | int,
            ))
        if not any(parameter.name == "log_levels" for parameter in parameters):
            index = next(
                (i for i, p in enumerate(parameters)
                 if p.kind == Parameter.VAR_KEYWORD),
                len(parameters),
            )
            parameters.insert(index, Parameter(
                "log_levels", kind=Parameter.KEYWORD_ONLY,
                default=None, annotation=dict[str, str | int] | None,
            ))
        if not any(parameter.name == "font_scale" for parameter in parameters):
            index = next(
                (
                    i
                    for i, p in enumerate(parameters)
                    if p.kind == Parameter.VAR_KEYWORD
                ),
                len(parameters),
            )
            parameters.insert(
                index,
                Parameter(
                    "font_scale",
                    kind=Parameter.KEYWORD_ONLY,
                    default=1.0,
                    annotation=float,
                ),
            )
        return original.replace(
            parameters=parameters, return_annotation=Parameter.empty
        )

    def __call__(cls: type[Declared], *args: Any, **kwargs: Any) -> Declared:
        from collections.abc import Mapping
        from inspect import signature

        from cardtable._logging import _normalize_level

        from .elements._fonts import validate_font_scale

        font_scale = validate_font_scale(kwargs.pop("font_scale", 1.0))

        if "font_scale" in signature(cls.__init__).parameters:
            kwargs["font_scale"] = font_scale
        explicit_level = "log_level" in kwargs
        requested_level = kwargs.pop("log_level", "DEBUG")
        level = _normalize_level(requested_level)
        explicit_levels = "log_levels" in kwargs
        requested_levels = kwargs.pop("log_levels", None)
        if requested_levels is not None and not isinstance(requested_levels, Mapping):
            raise TypeError("log_levels must be a mapping or None")
        levels = {}
        for name, value in (requested_levels or {}).items():
            if not isinstance(name, str):
                raise TypeError("log_levels method names must be strings")
            method = getattr(cls, name, None)
            if not getattr(method, "_cardtable_logged", False):
                raise ValueError(
                    f"unknown logged operation for {cls.__name__}: {name!r}"
                )
            levels[name] = _normalize_level(value)
        if explicit_level or explicit_levels:
            parameters = signature(cls.__init__).parameters
            if explicit_level and "log_level" in parameters:
                kwargs["log_level"] = requested_level
            if explicit_levels and "log_levels" in parameters:
                kwargs["log_levels"] = requested_levels
        element = type.__call__(cls, *args, **kwargs)
        object.__setattr__(element, "font_scale", font_scale)
        object.__setattr__(element, "_log_level", level)
        object.__setattr__(element, "_log_levels", levels)
        validate = getattr(element, "_validate_declaration", None)
        if validate is not None:
            validate()
        owner = current_layout.get()
        if owner is not None:
            owner._declare(element)
        return element


class Row:
    """Place elements declared inside ``with Row()`` horizontally."""

    def __init__(self) -> None:
        self._declarations: list[Any] = []
        self._owner: LayoutOwner | None = None
        self._layout_token: Token[LayoutOwner | None] | None = None

    def __enter__(self) -> Self:
        owner = current_layout.get()
        if owner is None:
            raise RuntimeError("Row must be used inside a Card context")
        if isinstance(owner, Row):
            raise RuntimeError("Row contexts cannot be nested")
        if self._layout_token is not None:
            raise RuntimeError("row context is already active")
        self._declarations = []
        self._owner = owner
        self._layout_token = current_layout.set(self)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._layout_token is None or self._owner is None:
            raise RuntimeError("row context is not active")
        current_layout.reset(self._layout_token)
        owner = self._owner
        elements = tuple(self._declarations)
        self._layout_token = None
        self._owner = None
        self._declarations = []
        if exc_type is None:
            if not elements:
                raise ValueError("Row requires at least one element")
            owner._declare(elements)

    def _declare(self, element: Any) -> None:
        self._declarations.append(element)


def element_padding(
    parent: Any, *, padx: float = 10, pady: float = 5
) -> dict[str, float]:
    """Share outer spacing between a horizontal Row and its elements."""
    scale = 0.5 if getattr(parent, "_cardtable_row_cell", False) is True else 1
    return {"padx": padx * scale, "pady": pady * scale}
