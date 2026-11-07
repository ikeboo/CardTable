"""Shared validation and defaults for string choice inputs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from ._input import InputElement


def _choice_values(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("values must be a sequence of strings")
    normalized = tuple(values)
    if not normalized:
        raise ValueError("values must not be empty")
    if any(not isinstance(value, str) for value in normalized):
        raise TypeError("values must be a sequence of strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("values must not contain duplicates")
    return normalized


@dataclass(slots=True)
class _ChoiceElement(InputElement[str, str]):
    values: Sequence[str]
    label: str | None = None
    default: str | None = None

    def __post_init__(self) -> None:
        self.values = _choice_values(self.values)
        self.default = self.values[0] if self.default is None else self.default
        if not isinstance(self.default, str) or self.default not in self.values:
            raise ValueError("default must be one of values")
        if self.label is not None and not isinstance(self.label, str):
            raise TypeError("label must be a string or None")

    @property
    def initial_value(self) -> str:
        return cast(str, self.default)

    def normalize(self, value: str) -> str:
        if not isinstance(value, str) or value not in self.values:
            raise ValueError(f"value must be one of {self.values!r}")
        return value
