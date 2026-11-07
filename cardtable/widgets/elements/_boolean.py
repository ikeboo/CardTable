"""Shared validation and defaults for boolean inputs."""

from __future__ import annotations

from dataclasses import dataclass

from ._input import InputElement


@dataclass(slots=True)
class _BooleanElement(InputElement[bool, bool]):
    default: bool = False
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.default, bool):
            raise TypeError("default must be a bool")
        if self.label is not None and not isinstance(self.label, str):
            raise TypeError("label must be a string or None")

    @property
    def initial_value(self) -> bool:
        return self.default

    def normalize(self, value: bool) -> bool:
        if not isinstance(value, bool):
            raise TypeError("value must be a bool")
        return value
