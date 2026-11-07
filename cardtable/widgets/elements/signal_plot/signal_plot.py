"""Lightweight, bounded, single-channel signal plotting."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal, localcontext
from numbers import Real
from typing import Any, Literal

import numpy as np

from ..base import DisplayRequest, Element
from ._signal_buffer import SignalBuffer, clip_segments

_UNSET = object()
_LIMIT = np.finfo(np.float64).max


def _number(value, name, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"invalid {name}")
    return value


def _range(value, name):
    if value is None:
        return None
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError(f"{name} must be a tuple of two real numbers or None")
    lo, hi = (_number(v, name) for v in value)
    if lo >= hi:
        raise ValueError(f"{name} requires min < max")
    return lo, hi


def _finite_range(lo, hi):
    lo = max(-_LIMIT, min(_LIMIT, float(lo)))
    hi = max(-_LIMIT, min(_LIMIT, float(hi)))
    if lo == hi:
        with np.errstate(over="ignore"):
            lower, upper = np.nextafter(lo, -np.inf), np.nextafter(hi, np.inf)
        lo = float(lower) if np.isfinite(lower) else lo
        hi = float(upper) if np.isfinite(upper) else hi
    return lo, hi


class SignalPlot(Element[np.ndarray, Any]):
    """An equally spaced signal, retaining at most ``max_points`` samples.

    ``append`` adds one scalar, ``expand`` adds a chunk, and ``set`` replaces
    all samples. Axis ranges use samples, or seconds when sample_rate is set.
    """

    _deferred_display = True

    def __init__(
        self,
        label: str | None = None,
        *,
        sample_rate: float | None = None,
        x_origin: float = 0.0,
        x_range: tuple[float, float] | None = None,
        y_range: tuple[float, float] | None = None,
        follow_window: float | None = None,
        max_points: int = 1_000_000,
        max_fps: float = 30.0,
        dtype: Literal["float32", "float64"] = "float32",
        aspect: Sequence[float] = (4, 3),
        log_level: str | int = "DEBUG",
        log_levels: dict[str, str | int] | None = None,
        font_scale: float = 1.0,
    ) -> None:
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if isinstance(max_points, bool) or not isinstance(max_points, int):
            raise TypeError("max_points must be an integer")
        if max_points <= 0:
            raise ValueError("max_points must be positive")
        if dtype not in ("float32", "float64"):
            raise ValueError("dtype must be 'float32' or 'float64'")
        self.label = label
        if isinstance(aspect, (str, bytes)) or not isinstance(aspect, Sequence):
            raise TypeError("aspect must be a two-item numeric sequence")
        if len(aspect) != 2:
            raise TypeError("aspect must be a two-item numeric sequence")
        self.aspect = tuple(_number(v, "aspect", positive=True) for v in aspect)
        self._sample_rate = (
            None
            if sample_rate is None
            else _number(sample_rate, "sample_rate", positive=True)
        )
        self._x_origin = _number(x_origin, "x_origin")
        self._max_points = max_points
        self._dtype = dtype
        self._settings = self._validate_settings(
            dict(
                x_range=x_range,
                y_range=y_range,
                follow_window=follow_window,
                max_fps=max_fps,
            )
        )
        self._initial_settings = self._settings.copy()
        self._buffer = SignalBuffer(max_points, dtype)
        self._revision = 0
        self._generation = 0

    @staticmethod
    def _validate_settings(settings):
        result = dict(settings)
        for name in ("x_range", "y_range"):
            result[name] = _range(result[name], name)
        if result["follow_window"] is not None:
            result["follow_window"] = _number(
                result["follow_window"], "follow_window", positive=True
            )
        result["max_fps"] = _number(result["max_fps"], "max_fps", positive=True)
        if result["max_fps"] > 60:
            raise ValueError("max_fps must be <= 60")
        return result

    @property
    def initial_value(self):
        return np.empty(0, dtype=self._dtype)

    def normalize(self, values):
        if not isinstance(values, (list, tuple, np.ndarray)):
            raise TypeError("samples must be a one-dimensional list, tuple or ndarray")
        # Reject bools before NumPy can silently coerce a mixed list to integers.
        if isinstance(values, (list, tuple)) and any(
            isinstance(v, (bool, np.bool_)) for v in values
        ):
            raise TypeError("boolean samples are not supported")
        try:
            array = np.asarray(values)
        except (TypeError, ValueError) as error:
            raise TypeError("samples must be a flat real numeric array") from error
        if array.ndim != 1 or array.dtype.kind not in "iuf":
            raise TypeError("samples must be a one-dimensional real numeric array")
        with np.errstate(over="ignore", invalid="ignore"):
            array = np.asarray(array, dtype=self._dtype)
        if not np.isfinite(array).all():
            raise ValueError("samples must remain finite in the storage dtype")
        return np.ascontiguousarray(array)

    def _updated(self):
        # Revision is the dirty marker. UI pulls at most once per frame; no
        # full-value publication, snapshot, or timer on the ingestion path.
        self._revision += 1

    def set(
        self,
        values: list[float] | tuple[float, ...] | np.ndarray,
        *,
        x_range=_UNSET,
        y_range=_UNSET,
    ) -> None:
        with self._operation():
            array = self.normalize(values)
            settings = self._changed_settings(x_range=x_range, y_range=y_range)
            buffer = SignalBuffer(self.max_points, self.dtype)
            buffer.extend(array)
            self._buffer = buffer
            self._settings = settings
            self._generation += 1
            self._updated()

    def append(self, value: float) -> None:
        with self._operation():
            value = _number(value, "sample")
            with np.errstate(over="ignore"):
                converted = np.dtype(self.dtype).type(value)
            if not np.isfinite(converted):
                raise ValueError("sample must remain finite in the storage dtype")
            self._buffer.append(converted)
            self._updated()

    def expand(self, values: list[float] | tuple[float, ...] | np.ndarray) -> None:
        with self._operation():
            array = self.normalize(values)
            if len(array):
                self._buffer.extend(array)
                self._updated()

    def _changed_settings(self, **changes):
        return self._validate_settings(
            {
                **self._settings,
                **{
                    name: value
                    for name, value in changes.items()
                    if value is not _UNSET
                },
            }
        )

    def configure(
        self,
        *,
        x_range=_UNSET,
        y_range=_UNSET,
        follow_window=_UNSET,
        max_fps=_UNSET,
    ) -> None:
        with self._operation():
            settings = self._changed_settings(
                x_range=x_range,
                y_range=y_range,
                follow_window=follow_window,
                max_fps=max_fps,
            )
            if settings != self._settings:
                self._settings = settings
                self._updated()

    def get(self) -> np.ndarray:
        with self._operation():
            return self._buffer.get()

    def reset(self) -> None:
        with self._operation():
            self._buffer = SignalBuffer(self.max_points, self.dtype)
            self._settings = self._initial_settings.copy()
            self._generation += 1
            self._updated()

    def _controller_value(self):
        return None

    @property
    def sample_rate(self):
        return self._sample_rate

    @property
    def x_origin(self):
        return self._x_origin

    @property
    def max_points(self):
        return self._max_points

    @property
    def dtype(self):
        return self._dtype

    @property
    def sample_count(self):
        with self._synchronized():
            return self._buffer.count

    @property
    def start_index(self):
        with self._synchronized():
            return self._buffer.start

    def _setting(self, name):
        with self._synchronized():
            return self._settings[name]

    @property
    def x_range(self):
        return self._setting("x_range")

    @property
    def y_range(self):
        return self._setting("y_range")

    @property
    def follow_window(self):
        return self._setting("follow_window")

    @property
    def max_fps(self):
        return self._setting("max_fps")

    def __getstate__(self):
        # copy()/deepcopy()/spawn must never duplicate the recording or tree.
        with self._synchronized():
            return {
                name: value
                for name, value in super().__getstate__().items()
                if name not in {"_buffer", "_value"}
            }

    def __setstate__(self, state):
        super().__setstate__(state)
        self._buffer = SignalBuffer(self.max_points, self.dtype)

    def _x(self, indices):
        with np.errstate(over="ignore", invalid="ignore"):
            result = self.x_origin + np.asarray(indices, dtype=np.float64) / (
                self.sample_rate or 1
            )
        return np.nan_to_num(result, nan=self.x_origin, posinf=_LIMIT, neginf=-_LIMIT)

    def _axes_x(self):
        if self.x_range is not None:
            return self.x_range
        count, start = self._buffer.count, self._buffer.start
        # Decimal is only used for a few scalar axis calculations, preventing
        # overflow even on platforms where longdouble equals float64.
        with localcontext() as ctx:
            ctx.prec = 50
            origin = Decimal.from_float(self.x_origin)
            dx = 1 / Decimal.from_float(self.sample_rate or 1.0)
            end = origin + max(0, count - 1) * dx
            if self.follow_window is not None:
                return _finite_range(end - Decimal.from_float(self.follow_window), end)
            if not count:
                return _finite_range(origin, origin + dx)
            if count - start == 1:
                return _finite_range(end - dx / 2, end + dx / 2)
            return _finite_range(origin + start * dx, end)

    def _sample_bounds(self, xr):
        with np.errstate(over="ignore", invalid="ignore"):
            bounds = (np.asarray(xr) - self.x_origin) * (self.sample_rate or 1)
        if not np.isfinite(bounds).all():
            with localcontext() as ctx:
                ctx.prec = 50
                origin = Decimal.from_float(self.x_origin)
                rate = Decimal.from_float(self.sample_rate or 1.0)
                bounds = [(Decimal.from_float(x) - origin) * rate for x in xr]
        return bounds

    @staticmethod
    def _unit(values, bounds):
        lo, hi = bounds
        scale = max(abs(lo), abs(hi), np.finfo(np.float64).tiny)
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            return (values / scale - lo / scale) / (hi / scale - lo / scale)

    def _snapshot(self, width):
        xr = self._axes_x()
        count, start = self._buffer.count, self._buffer.start
        lower, upper = self._sample_bounds(xr)
        # Clip before integer conversion, so a huge fixed range stays cheap.
        first = int(math.ceil(max(start, min(count, lower))))
        last = int(math.floor(max(start - 1, min(count - 1, upper)))) + 1
        indices, samples = self._buffer.envelope(first, last, width)
        xs = self._x(indices)
        ys = samples.astype(np.float64)
        # Aggregate only interior samples. Boundary intersections must use the
        # actual adjacent raw samples, never two distant envelope vertices.
        for boundary, position, prepend in (
            (xr[0], lower, True),
            (xr[1], upper, False),
        ):
            if start <= position < count - 1 and position != math.floor(position):
                before = int(math.floor(position))
                fraction = float(position - before)
                a, b = self._buffer.at([before, before + 1]).astype(np.float64)
                value = (1 - fraction) * a + fraction * b
                if prepend:
                    xs, ys = np.r_[boundary, xs], np.r_[value, ys]
                else:
                    xs, ys = np.r_[xs, boundary], np.r_[ys, value]
        yr = self.y_range
        if yr is None:
            if not len(ys):
                yr = (-1.0, 1.0)
            else:
                lo, hi = float(np.min(ys)), float(np.max(ys))
                # Halving first keeps the span finite for opposite extremes.
                padding = (hi / 2 - lo / 2) * 0.1
                if lo == hi:
                    padding = max(abs(lo) * 0.05, 1e-6)
                with np.errstate(over="ignore"):
                    yr = _finite_range(lo - padding, hi + padding)
        segments = None
        points = np.empty((len(xs), 2), dtype=np.float64)
        if len(xs):
            points[:, 0] = self._unit(xs, xr)
            # Values outside a very narrow fixed Y range may normalize beyond
            # float64. Retain their finite source values for exact clipping.
            unit_y = self._unit(ys, yr)
            if not np.isfinite(unit_y).all() and len(xs) > 1:
                segments = clip_segments(np.column_stack((points[:, 0], ys)), yr)
            points[:, 1] = np.nan_to_num(unit_y, posinf=_LIMIT, neginf=-_LIMIT)
        return dict(
            revision=self._revision,
            generation=self._generation,
            width=width,
            x_range=xr,
            y_range=yr,
            points=points,
            segments=segments,
            max_fps=self.max_fps,
        )

    def display_value(self, value):
        with self._synchronized():
            return {**self._snapshot(1000), "serial": -1}

    def _display_request(self, request: DisplayRequest):
        if not isinstance(request.width, int) or not 1 <= request.width <= 16384:
            raise ValueError("invalid display width")
        if request.revision == self._revision:
            return dict(unchanged=True, serial=request.serial, max_fps=self.max_fps)
        return {**self._snapshot(request.width), "serial": request.serial}

    def build_ui(self, parent, emit):
        from ._signal_plot_control import SignalPlotControl

        self._ui = SignalPlotControl(
            parent,
            emit,
            label=self.label,
            aspect=self.aspect,
            max_fps=self.max_fps,
            font_scale=self.font_scale,
        )

    def update_ui(self, value):
        self._ui.update(value)
