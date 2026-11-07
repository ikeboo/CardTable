"""Bounded samples and vectorized range extrema; no Tk dependencies."""

from __future__ import annotations

import numpy as np


class SignalBuffer:
    """Ring indexed by absolute sample number, with an extrema segment tree."""

    def __init__(self, capacity: int, dtype: str):
        self.capacity = capacity
        self.dtype = np.dtype(dtype)
        self.count = 0
        self.size = 1 << (capacity - 1).bit_length()
        self.data = None
        self.low = None
        self.high = None

    @property
    def start(self):
        return max(0, self.count - self.capacity)

    def _allocate(self):
        if self.data is None:
            self.data = np.zeros(self.capacity, dtype=self.dtype)
            index_dtype = (
                np.int32 if self.capacity <= np.iinfo(np.int32).max else np.int64
            )
            self.low = np.full(2 * self.size, -1, dtype=index_dtype)
            self.high = np.full(2 * self.size, -1, dtype=index_dtype)

    def _pick(self, a, b, *, minimum):
        av = self.data[np.maximum(a, 0)]
        bv = self.data[np.maximum(b, 0)]
        better = av <= bv if minimum else av >= bv
        return np.where((b < 0) | ((a >= 0) & better), a, b)

    def _refresh(self, first, last):
        self.low[self.size + first : self.size + last] = np.arange(first, last)
        self.high[self.size + first : self.size + last] = np.arange(first, last)
        left, right = (self.size + first) // 2, (self.size + last - 1) // 2
        while left:
            nodes = np.arange(left, right + 1)
            children = nodes * 2
            self.low[nodes] = self._pick(
                self.low[children], self.low[children + 1], minimum=True
            )
            self.high[nodes] = self._pick(
                self.high[children], self.high[children + 1], minimum=False
            )
            left //= 2
            right //= 2

    def append(self, value):
        self._allocate()
        physical = self.count % self.capacity
        self.data[physical] = value
        node = self.size + physical
        self.low[node] = self.high[node] = physical
        node //= 2
        # Scalar path avoids allocating ~20 temporary arrays per single sample.
        while node:
            for tree, minimum in ((self.low, True), (self.high, False)):
                a, b = int(tree[2 * node]), int(tree[2 * node + 1])
                if a < 0:
                    best = b
                elif b < 0:
                    best = a
                elif minimum:
                    best = a if self.data[a] <= self.data[b] else b
                else:
                    best = a if self.data[a] >= self.data[b] else b
                tree[node] = best
            node //= 2
        self.count += 1

    def extend(self, values):
        if not len(values):
            return
        self._allocate()
        total = self.count + len(values)
        values = values[-self.capacity :]
        first = (total - len(values)) % self.capacity
        length = min(len(values), self.capacity - first)
        self.data[first : first + length] = values[:length]
        self._refresh(first, first + length)
        if length < len(values):
            remaining = len(values) - length
            self.data[:remaining] = values[length:]
            self._refresh(0, remaining)
        self.count = total

    def get(self):
        if not self.count:
            return np.empty(0, dtype=self.dtype)
        length = min(self.count, self.capacity)
        first = self.start % self.capacity
        split = min(length, self.capacity - first)
        result = np.empty(length, dtype=self.dtype)
        result[:split] = self.data[first : first + split]
        result[split:] = self.data[: length - split]
        return result

    def at(self, indices):
        return self.data[np.asarray(indices) % self.capacity]

    def _query(self, left, right):
        """Batch half-open physical ranges, returning physical extrema indices."""
        left, right = left + self.size, right + self.size
        low = np.full(len(left), -1, dtype=np.int64)
        high = low.copy()
        while np.any(left < right):
            active = left < right
            take_left = active & ((left & 1) != 0)
            take_right = active & ((right & 1) != 0)
            for mask, nodes in ((take_left, left), (take_right, right - 1)):
                if np.any(mask):
                    low[mask] = self._pick(
                        low[mask], self.low[nodes[mask]], minimum=True
                    )
                    high[mask] = self._pick(
                        high[mask], self.high[nodes[mask]], minimum=False
                    )
            left = (left + take_left) // 2
            right = (right - take_right) // 2
        return low, high

    def envelope(self, first: int, last: int, width: int):
        """At most four ordered samples per bin, preserving both extrema."""
        if last <= first:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=self.dtype)
        if last - first <= width * 4:
            indices = np.arange(first, last, dtype=np.int64)
            return indices, self.at(indices)
        # Integer bin edges retain every sample even at non-divisible widths.
        edges = first + np.arange(width + 1, dtype=np.int64) * (last - first) // width
        begins, ends = edges[:-1], edges[1:]
        physical = begins % self.capacity
        lengths = ends - begins
        split = np.minimum(physical + lengths, self.capacity)
        low, high = self._query(physical.copy(), split.copy())
        wrap = physical + lengths > self.capacity
        if np.any(wrap):
            lo2, hi2 = self._query(
                np.zeros(np.count_nonzero(wrap), dtype=np.int64),
                physical[wrap] + lengths[wrap] - self.capacity,
            )
            low[wrap] = self._pick(low[wrap], lo2, minimum=True)
            high[wrap] = self._pick(high[wrap], hi2, minimum=False)
        # Map physical leaves back into the absolute interval for each bin.
        lo_abs = begins + (low - physical) % self.capacity
        hi_abs = begins + (high - physical) % self.capacity
        ordered = np.sort(np.stack((begins, lo_abs, hi_abs, ends - 1)), axis=0)
        indices = ordered.T.reshape(-1)
        return indices, self.at(indices)


def clip_segments(points, y_range=(0.0, 1.0)):
    """Clip a normalized polyline to Y=[0, 1] without joining hidden parts."""
    a, b = points[:-1], points[1:]
    lo, hi = y_range
    scale = np.maximum(
        max(abs(lo), abs(hi), 1e-300), np.maximum(np.abs(a[:, 1]), np.abs(b[:, 1]))
    )
    ay, by = a[:, 1] / scale, b[:, 1] / scale
    delta = by - ay
    with np.errstate(divide="ignore", invalid="ignore", under="ignore"):
        zero = (lo / scale - ay) / delta
        one = (hi / scale - ay) / delta
    lower = np.maximum(0, np.minimum(zero, one))
    upper = np.minimum(1, np.maximum(zero, one))
    flat = delta == 0
    lower[flat], upper[flat] = 0, 1
    valid = (lower <= upper) & (~flat | ((a[:, 1] >= lo) & (a[:, 1] <= hi)))
    a, b, lower, upper, zero, one = (v[valid] for v in (a, b, lower, upper, zero, one))
    result = np.empty((len(a), 4))
    result[:, 0] = (1 - lower) * a[:, 0] + lower * b[:, 0]
    result[:, 2] = (1 - upper) * a[:, 0] + upper * b[:, 0]
    rising = b[:, 1] > a[:, 1]
    axis_scale = max(abs(lo), abs(hi), np.finfo(np.float64).tiny)
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        ya = (a[:, 1] / axis_scale - lo / axis_scale) / (
            hi / axis_scale - lo / axis_scale
        )
        yb = (b[:, 1] / axis_scale - lo / axis_scale) / (
            hi / axis_scale - lo / axis_scale
        )
    result[:, 1] = np.where(lower > 0, np.where(rising, 0, 1), ya)
    result[:, 3] = np.where(upper < 1, np.where(rising, 1, 0), yb)
    return result
