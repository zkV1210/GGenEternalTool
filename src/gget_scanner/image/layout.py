"""Expand a normalized grid into original-image pixel boundary coordinates."""

from gget_scanner.config.layout_models import (
    Bounds, LayoutError, LayoutProfile, ResolvedCard, ResolvedLayout, SCALE, integer, pair,
)


def resolve_layout(
    profile: LayoutProfile,
    image_size: tuple[int, int],
    viewport: Bounds | None = None,
) -> ResolvedLayout:
    width, height = pair(image_size, "image_size", minimum=1)
    if viewport is None:
        viewport = (0, 0, width, height)
    if not isinstance(viewport, (tuple, list)) or len(viewport) != 4:
        raise LayoutError("viewport: expected (left, top, right, bottom)")
    left, top, right, bottom = (integer(v, f"viewport[{i}]", 0) for i, v in enumerate(viewport))
    if not (left < right <= width and top < bottom <= height):
        raise LayoutError("viewport: must be a nonempty rectangle inside the input image")
    vw, vh = right - left, bottom - top
    rw, rh = profile.reference_size
    if vw * rh != vh * rw:
        raise LayoutError(f"screen.reference_size: aspect ratio {rw}:{rh} is incompatible "
                          f"with effective image size {vw}x{vh}; provide a matching layout or viewport")
    grid = profile.grid
    cards = []
    for row in range(grid.rows):
        for column in range(grid.columns):
            dx = column * grid.horizontal_step[0] + row * grid.vertical_step[0]
            dy = column * grid.horizontal_step[1] + row * grid.vertical_step[1]
            normalized = tuple((x + dx, y + dy) for x, y in grid.first_card)
            if any(not 0 <= v <= SCALE for p in normalized for v in p):
                raise LayoutError(f"grid card row={row} column={column}: outside normalized viewport [0, 10000]")
            vertices = tuple((left + x * vw / SCALE, top + y * vh / SCALE) for x, y in normalized)
            cards.append(ResolvedCard(row, column, row * grid.columns + column, vertices))
    return ResolvedLayout(profile.profile_id, (width, height), (left, top, right, bottom), tuple(cards))
