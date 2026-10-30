from dataclasses import replace

import pytest

from gget_scanner.config.layout_models import LayoutError
from gget_scanner.image.layout import resolve_layout


def test_grid_expansion(profile):
    layout = resolve_layout(profile, (1000, 1000))
    assert len(layout.cards) == 16
    assert sum(len(card.vertices) for card in layout.cards) == 64
    assert layout.cards[0].vertices == ((50, 100), (130, 100), (130, 300), (50, 300))
    assert layout.cards[-1].vertices == ((890, 400), (970, 400), (970, 600), (890, 600))
    assert [(c.row, c.column, c.index) for c in layout.cards] == [
        (r, c, r * 8 + c) for r in range(2) for c in range(8)
    ]


@pytest.mark.parametrize("size,vertices,bounds", [
    ((2000, 2000), ((100, 200), (260, 200), (260, 600), (100, 600)), (100, 200, 260, 600)),
    ((333, 333), ((16.65, 33.3), (43.29, 33.3), (43.29, 99.9), (16.65, 99.9)), (16, 33, 44, 100)),
])
def test_resolution_and_outward_rounding(profile, size, vertices, bounds):
    card = resolve_layout(profile, size).cards[0]
    for actual, expected in zip(card.vertices, vertices):
        assert actual == pytest.approx(expected)
    assert card.bounds == bounds


def test_aspect_ratio_error(profile):
    with pytest.raises(LayoutError, match="aspect ratio"):
        resolve_layout(profile, (1920, 1080))


def test_viewport_offset(profile):
    layout = resolve_layout(profile, (1200, 1400), (100, 200, 1100, 1200))
    assert layout.cards[0].vertices == ((150, 300), (230, 300), (230, 500), (150, 500))
    assert layout.viewport == (100, 200, 1100, 1200)


@pytest.mark.parametrize("viewport", [(0, 0, 1001, 1000), (-1, 0, 500, 500),
                                      (0, 0, 0, 10), (0, 0, 500, 400), (0, 0, 1.5, 10), (0, 0)])
def test_invalid_viewport(profile, viewport):
    with pytest.raises(LayoutError):
        resolve_layout(profile, (1000, 1000), viewport)


def test_skewed_steps(profile):
    grid = replace(profile.grid, horizontal_step=(1200, 100), vertical_step=(100, 3000))
    card = resolve_layout(replace(profile, grid=grid), (1000, 1000)).cards[-1]
    assert card.vertices[0] == (900, 470)


def test_negative_steps_are_supported(profile):
    grid = replace(profile.grid, columns=2, rows=1, horizontal_step=(-100, 0))
    assert resolve_layout(replace(profile, grid=grid), (1000, 1000)).cards[1].vertices[0] == (40, 100)


@pytest.mark.parametrize("step", [(2000, 0), (-1200, 0)])
def test_expanded_card_outside_viewport(profile, step):
    grid = replace(profile.grid, horizontal_step=step)
    with pytest.raises(LayoutError, match="outside normalized viewport"):
        resolve_layout(replace(profile, grid=grid), (1000, 1000))


def test_row_count_is_configured(profile):
    grid = replace(profile.grid, rows=3)
    assert len(resolve_layout(replace(profile, grid=grid), (1000, 1000)).cards) == 24


def test_layout_is_unchanged_and_resolution_is_stateless(profile):
    snapshot = repr(profile)
    first = resolve_layout(profile, (1000, 1000))
    resolve_layout(profile, (2000, 2000))
    assert resolve_layout(profile, (1000, 1000)) == first
    assert repr(profile) == snapshot
