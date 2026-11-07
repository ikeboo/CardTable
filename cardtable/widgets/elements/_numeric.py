"""Shared range validation, stepping and numeric display formatting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Generic, cast

from ._input import InputElement, InputValue, Value, _InputUI


@dataclass(slots=True)
class _NumericElement(InputElement[Value, InputValue], Generic[Value, InputValue]):
    min: float
    max: float
    step: float
    label: str | None = None
    default: Value | None = None

    def __post_init__(self) -> None:
        for field_name in ("min", "max", "step"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(f"{field_name} must be a finite number")
            if not math.isfinite(float(value)):
                raise ValueError(f"{field_name} must be a finite number")
        self.min, self.max, self.step = (
            float(self.min),
            float(self.max),
            float(self.step),
        )
        if self.max <= self.min:
            raise ValueError("max must be greater than min")
        if self.step <= 0:
            raise ValueError("step must be positive")
        step_count = (self.max - self.min) / self.step
        if not math.isclose(step_count, round(step_count), abs_tol=1e-9):
            raise ValueError("step must divide the slider range evenly")
        self.default = (
            self._default_value()
            if self.default is None
            else self.normalize(cast(InputValue, self.default))
        )
        if self.label is not None and not isinstance(self.label, str):
            raise TypeError("label must be a string or None")

    def _default_value(self) -> Value:
        raise NotImplementedError

    @property
    def initial_value(self) -> Value:
        return cast(Value, self.default)

    @property
    def number_of_steps(self) -> int:
        return round((self.max - self.min) / self.step)

    def _normalize_number(self, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("value must be a finite number")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError("value must be a finite number")
        if normalized < self.min or normalized > self.max:
            raise ValueError(f"value must be between {self.min} and {self.max}")
        step_number = round((normalized - self.min) / self.step)
        stepped = self.min + step_number * self.step
        if not math.isclose(normalized, stepped, abs_tol=1e-9):
            raise ValueError(f"value must be aligned to step {self.step}")
        return (
            self.max
            if math.isclose(stepped, self.max, abs_tol=1e-9)
            else float(stepped)
        )


class _NumericUI(_InputUI):
    __slots__ = ()

    @staticmethod
    def _format_number(value: float) -> str:
        return f"{value:g}"
