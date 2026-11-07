from __future__ import annotations

from collections.abc import Sequence
from math import ceil, floor
from numbers import Integral, Real

from .theme import DEFAULT_GRID_ASPECT
from .theme import DEFAULT_WINDOW_WIDTH as DEFAULT_WINDOW_WIDTH

Geometry = tuple[int, int, int, int]

DEFAULT_GEOMETRY_UNIT = "grid"
DEFAULT_GRID_COLUMNS = 12
DEFAULT_GRID_GEOMETRY: Geometry = (0, 0, 4, 4)
DEFAULT_PIXEL_GEOMETRY: Geometry = (0, 0, 480, 320)


def normalize_geometry_unit(unit: str) -> str:
    if not isinstance(unit, str):
        raise TypeError("geometry_unit must be 'grid' or 'px'")
    normalized = unit.lower()
    if normalized not in {"grid", "px"}:
        raise ValueError("geometry_unit must be 'grid' or 'px'")
    return normalized


def normalize_grid_columns(columns: int) -> int:
    if not isinstance(columns, Integral):
        raise TypeError("grid_columns must be an integer")
    columns = int(columns)
    if columns <= 0:
        raise ValueError("grid_columns must be positive")
    return columns


def normalize_grid_aspect(aspect: Sequence[Real]) -> tuple[float, float]:
    if isinstance(aspect, (str, bytes)) or len(aspect) != 2:
        raise ValueError("grid_aspect must be (width, height)")
    if not all(isinstance(value, Real) for value in aspect):
        raise TypeError("grid_aspect values must be numbers")
    width, height = (float(value) for value in aspect)
    if width <= 0 or height <= 0:
        raise ValueError("grid_aspect values must be positive")
    return width, height


def normalize_window_width(width: int) -> int:
    if not isinstance(width, Integral):
        raise TypeError("window_width must be an integer")
    width = int(width)
    if width <= 0:
        raise ValueError("window_width must be positive")
    return width


def normalize_geometry(
    geometry: Sequence[int] | None,
    *,
    unit: str,
    grid_columns: int,
) -> Geometry | None:
    if geometry is None:
        return None
    if isinstance(geometry, (str, bytes)) or len(geometry) != 4:
        if unit == "grid":
            raise ValueError(
                "geometry must be "
                "(start_grid_col, start_grid_row, width_grid, height_grid)"
            )
        raise ValueError("geometry must be (x, y, width, height)")
    if not all(isinstance(value, Integral) for value in geometry):
        raise TypeError("geometry values must be integers")

    x, y, width, height = (int(value) for value in geometry)
    if x < 0 or y < 0:
        raise ValueError("geometry start positions must be non-negative")
    if width <= 0 or height <= 0:
        raise ValueError("geometry width and height must be positive")
    if unit == "grid" and x + width > grid_columns:
        raise ValueError(
            "grid geometry must fit within "
            f"{grid_columns} columns (start_grid_col + width_grid)"
        )
    return x, y, width, height


def grid_cell_size(
    window_width: int,
    grid_columns: int = DEFAULT_GRID_COLUMNS,
    grid_aspect: tuple[float, float] = DEFAULT_GRID_ASPECT,
) -> tuple[float, float]:
    cell_width = max(1, window_width) / grid_columns
    cell_height = cell_width * grid_aspect[1] / grid_aspect[0]
    return cell_width, cell_height


def grid_to_pixels(
    geometry: Geometry,
    window_width: int,
    grid_columns: int = DEFAULT_GRID_COLUMNS,
    grid_aspect: tuple[float, float] = DEFAULT_GRID_ASPECT,
) -> Geometry:
    """Convert grid lines to pixels without accumulating rounding gaps."""
    x, y, width, height = geometry
    cell_width, cell_height = grid_cell_size(window_width, grid_columns, grid_aspect)
    left = round(x * cell_width)
    top = round(y * cell_height)
    right = round((x + width) * cell_width)
    bottom = round((y + height) * cell_height)
    return left, top, max(1, right - left), max(1, bottom - top)


def _snap_delta(delta: int, cell_size: float, *, threshold: float = 0.5) -> int:
    cells = delta / cell_size
    if cells >= 0:
        return floor(cells + (1 - threshold))
    return ceil(cells - (1 - threshold))


def move_grid_geometry(
    geometry: Geometry,
    dx: int,
    dy: int,
    *,
    cell_width: float,
    cell_height: float,
    grid_columns: int,
) -> Geometry:
    x, y, width, height = geometry
    next_x = x + _snap_delta(dx, cell_width)
    next_y = y + _snap_delta(dy, cell_height)
    return (
        min(max(0, next_x), grid_columns - width),
        max(0, next_y),
        width,
        height,
    )


def resize_grid_geometry(
    geometry: Geometry,
    dx: int,
    dy: int,
    *,
    cell_width: float,
    cell_height: float,
    grid_columns: int,
    min_width: int = 1,
) -> Geometry:
    x, y, width, height = geometry
    return (
        x,
        y,
        min(
            max(min_width, width + _snap_delta(dx, cell_width, threshold=0.1)),
            grid_columns - x,
        ),
        max(1, height + _snap_delta(dy, cell_height, threshold=0.1)),
    )
