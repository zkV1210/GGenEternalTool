"""Immutable layout data and shared geometry validation."""

from dataclasses import dataclass
from math import ceil, floor, isfinite

SCALE = 10000
POINT_ORDER = ("TL", "TR", "BR", "BL")
Point = tuple[float, float]
Quad = tuple[Point, Point, Point, Point]
Bounds = tuple[int, int, int, int]


class LayoutError(ValueError):
    """Invalid layout configuration or incompatible image geometry."""


def integer(value: object, field: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = f" >= {minimum}" if minimum is not None else ""
        raise LayoutError(f"{field}: expected an integer{suffix}")
    return value


def pair(value: object, field: str, *, minimum: int | None = None) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise LayoutError(f"{field}: expected two integers")
    return tuple(integer(v, f"{field}[{i}]", minimum) for i, v in enumerate(value))


def validate_quad(vertices: Quad, field: str) -> None:
    if len(vertices) != 4:
        raise LayoutError(f"{field}: expected four vertices in TL, TR, BR, BL order")
    if any(len(p) != 2 or any(isinstance(v, bool) or not isfinite(v) for v in p)
           for p in vertices):
        raise LayoutError(f"{field}: vertices must contain finite numeric coordinates")
    # In image coordinates (Y down), these turns must all be strictly positive.
    # A single winding/area check would also admit a wrongly labelled start point.
    turns = []
    for i in range(4):
        a, b, c = vertices[i], vertices[(i + 1) % 4], vertices[(i + 2) % 4]
        turns.append((b[0] - a[0]) * (c[1] - b[1])
                     - (b[1] - a[1]) * (c[0] - b[0]))
    tl, tr, br, bl = vertices
    if (any(t <= 0 for t in turns) or not
            (tl[0] < tr[0] and bl[0] < br[0] and tl[1] < bl[1] and tr[1] < br[1])):
        raise LayoutError(f"{field}: expected a strictly convex, non-degenerate quad "
                          "with correctly labelled TL, TR, BR, BL vertices; "
                          "self-intersections are not allowed")


@dataclass(frozen=True)
class GridSpec:
    rows: int
    columns: int
    first_card: Quad
    horizontal_step: tuple[int, int]
    vertical_step: tuple[int, int]

    def __post_init__(self) -> None:
        integer(self.rows, "grid.rows", 1)
        integer(self.columns, "grid.columns", 1)
        if not isinstance(self.first_card, (list, tuple)) or len(self.first_card) != 4:
            raise LayoutError("grid.first_card: expected four vertices")
        points = tuple(pair(p, f"grid.first_card[{i}]", minimum=0)
                       for i, p in enumerate(self.first_card))
        if any(v > SCALE for p in points for v in p):
            raise LayoutError("grid.first_card: coordinates must be in [0, 10000]")
        validate_quad(points, "grid.first_card")
        object.__setattr__(self, "first_card", points)
        for name, count in (("horizontal_step", self.columns), ("vertical_step", self.rows)):
            step = pair(getattr(self, name), f"grid.{name}")
            if count > 1 and step == (0, 0):
                raise LayoutError(f"grid.{name}: repeated cards require a nonzero step")
            object.__setattr__(self, name, step)


@dataclass(frozen=True)
class LayoutProfile:
    profile_id: str
    reference_size: tuple[int, int]
    grid: GridSpec
    schema_version: int = 1

    def __post_init__(self) -> None:
        integer(self.schema_version, "schema_version", 1)
        if self.schema_version != 1:
            raise LayoutError("schema_version: only version 1 is supported")
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise LayoutError("profile_id: expected a nonempty string")
        object.__setattr__(self, "reference_size", pair(self.reference_size, "screen.reference_size", minimum=1))
        if not isinstance(self.grid, GridSpec):
            raise LayoutError("grid: expected GridSpec")


@dataclass(frozen=True)
class ResolvedCard:
    row: int
    column: int
    index: int
    vertices: Quad

    @property
    def bounds(self) -> Bounds:
        """Outward-rounded, half-open pixel boundary rectangle."""
        xs, ys = zip(*self.vertices)
        return floor(min(xs)), floor(min(ys)), ceil(max(xs)), ceil(max(ys))


@dataclass(frozen=True)
class ResolvedLayout:
    profile_id: str
    image_size: tuple[int, int]
    viewport: Bounds
    cards: tuple[ResolvedCard, ...]
