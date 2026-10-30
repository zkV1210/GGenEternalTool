"""Known-pixel geometry, including clipped and occluded rows; no game assets."""

import cv2
import numpy as np
import pytest

from gget_scanner.image.card_detection import (
    Candidate, detect_anchor, detect_card, detect_next_row, edge_tolerance,
    expand_grid, prepare_image, validate_card,
)
from gget_scanner.pipeline.auto_scan import auto_scan


def make_screen(first_top=80, rows=2, columns=8, overlay_y=None, missing=()):
    image = np.full((800, 1200, 3), 22, np.uint8)
    boxes = {}
    for row in range(rows):
        for column in range(columns):
            if (row, column) in missing:
                continue
            x, y = 180 + column * 118, first_top + row * 230
            color = ((180, 100, 240), (90, 220, 170), (230, 180, 70))[column % 3]
            cv2.rectangle(image, (x, y), (x + 95, y + 190), color, 2)
            # Complex diagonal artwork and a horizontal internal information bar.
            cv2.line(image, (x + 12, y + 25), (x + 78, y + 145), (190, 210, 240), 3)
            cv2.line(image, (x + 10, y + 145), (x + 85, y + 145), color, 2)
            boxes[row, column] = (x, y, x + 95, y + 190)
    image[:57] = 22  # Scrolling clips the first row at the list viewport.
    cv2.line(image, (150, 55), (1150, 55), (170, 170, 170), 2)
    cv2.line(image, (20, 32), (400, 32), (240, 240, 240), 2)  # Header distractor.
    if overlay_y:
        image[overlay_y:] = 45
        cv2.line(image, (150, overlay_y), (1150, overlay_y), (210, 210, 210), 2)
    return image, boxes


def assert_close(actual, expected, tolerance=5):
    assert max(abs(a - b) for a, b in zip(actual, expected)) <= tolerance


@pytest.mark.parametrize("scale", [.65, 1., 1.5])
@pytest.mark.parametrize("jpeg", [False, True])
def test_anchor_single_frame_and_grid_match_known_pixels(scale, jpeg):
    image, boxes = make_screen()
    image = cv2.resize(image, None, fx=scale, fy=scale)
    if jpeg:
        ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 70])
        assert ok
        image = cv2.imdecode(encoded, 1)
    original = image.copy()
    features = prepare_image(image)
    anchor = detect_anchor(features)
    assert_close(anchor, tuple(round(x * scale) for x in (150, 55, 1150, 55)), 5)
    result = auto_scan(image)
    assert result.error is None
    assert len(result.crops) == 16
    assert len(result.attempts) == 2
    for crop in result.crops:
        expected = tuple(round(x * scale) for x in boxes[crop.card.row, crop.card.column])
        assert_close(crop.card.bounds, expected, max(5, round(scale * 4)))
    np.testing.assert_array_equal(image, original)


def test_clipped_first_row_then_two_complete_rows():
    image, boxes = make_screen(first_top=-40, rows=3)
    result = auto_scan(image)
    assert len(result.attempts) == 3
    assert not result.attempts[0].validation.valid
    assert {c.card.row for c in result.crops} == {1, 2}
    assert len(result.crops) == 16
    for crop in result.crops:
        assert_close(crop.card.bounds, boxes[crop.card.row, crop.card.column])


@pytest.mark.parametrize("first_top,overlay_y,expected", [(80, 460, 8), (-40, 350, 0), (80, 220, 0)])
def test_toolbar_does_not_supply_a_missing_bottom(first_top, overlay_y, expected):
    image, _ = make_screen(first_top=first_top, rows=3, overlay_y=overlay_y)
    result = auto_scan(image)
    assert len(result.crops) == expected
    # With no geometry anywhere below the Anchor, the initial full-region search
    # can terminate immediately; otherwise exactly one next row is examined.
    assert len(result.attempts) == (2 if result.attempts[0].candidate else 1)


def test_bootstrap_card_size_does_not_depend_on_canvas_width():
    source, boxes = make_screen(rows=1)
    wide = np.full((800, 4800, 3), 22, np.uint8)
    wide[:, :1200] = source
    roi = (150, 55, 1150, 800)
    a = detect_card(prepare_image(source), roi)
    b = detect_card(prepare_image(wide), roi)
    assert a is not None and b is not None
    assert a.bounds == b.bounds
    assert_close(b.bounds, boxes[0, 0])


def test_next_row_has_no_assumed_screen_fraction_or_row_gap():
    source, boxes = make_screen(rows=1)
    image = np.full((1200, 1200, 3), 22, np.uint8)
    image[:800] = source
    image[700:891, 180:1106] = source[80:271, 180:1106]
    result = auto_scan(image)
    assert len(result.crops) == 16
    assert len(result.attempts) == 2
    assert result.attempts[0].roi == (*result.anchor[:2], result.anchor[2], 1200)
    assert result.attempts[1].roi[3] == 1200
    for crop in result.crops:
        expected = boxes[0, crop.card.column]
        if crop.card.row == 1:
            expected = (expected[0], 700, expected[2], 890)
        assert_close(crop.card.bounds, expected)


def test_next_row_requires_observed_geometry_and_uses_measured_tolerance():
    image, _ = make_screen(rows=1)
    features = prepare_image(image)
    assert detect_next_row(features, None, (150, 55, 1150, 800)) is None
    c = Candidate(180, 275, 80, 270, 80, 270)
    tolerance = edge_tolerance(features, c)
    assert detect_next_row(features, c, (150, 55, 1150, 800)) == (
        c.left - tolerance, c.bottom + tolerance, c.right + tolerance + 1, 800)


def test_wide_next_row_search_does_not_skip_an_incomplete_second_row():
    image, _ = make_screen(rows=3)
    image[310:350, 150:1150] = 22
    result = auto_scan(image)
    assert len(result.crops) == 8
    assert {c.card.row for c in result.crops} == {0}
    assert len(result.attempts) == 2
    assert not result.attempts[1].validation.valid


def test_expected_height_without_bottom_is_rejected():
    image = np.zeros((400, 500, 3), np.uint8)
    cv2.line(image, (100, 60), (200, 60), (255, 255, 255), 2)
    for x in (100, 200):
        cv2.line(image, (x, 60), (x, 320), (255, 255, 255), 2)
    features = prepare_image(image)
    # An internal horizontal stripe cannot end a card whose sides continue.
    image[259:262, 100:201] = 255
    validation = validate_card(prepare_image(image), Candidate(100, 200, 60, 320, 60, 260))
    assert not validation.valid
    assert not validate_card(features, Candidate(100, 200, 60, 320, 60, 260)).valid


def test_complete_card_can_touch_list_separator():
    image, boxes = make_screen(first_top=57)
    result = auto_scan(image)
    assert len(result.crops) == 16
    assert len(result.attempts) == 2
    for crop in result.crops:
        assert_close(crop.card.bounds, boxes[crop.card.row, crop.card.column])


def test_nearby_separator_is_not_the_observed_card_bottom():
    image, _ = make_screen(rows=1)
    cv2.line(image, (150, 277), (1150, 277), (220, 220, 220), 2)
    c = Candidate(180, 275, 80, 270, 80, 270)
    assert validate_card(prepare_image(image), c).valid


def test_one_background_side_can_continue_after_a_genuine_bottom():
    image = np.zeros((400, 500, 3), np.uint8)
    cv2.rectangle(image, (100, 60), (200, 260), (230, 230, 230), 2)
    cv2.line(image, (200, 260), (200, 320), (230, 230, 230), 2)
    c = Candidate(100, 200, 60, 260, 60, 260)
    assert validate_card(prepare_image(image), c).valid


def test_grid_uses_observed_row_bottom_instead_of_baseline_glow():
    image, _ = make_screen(rows=1)
    # Separate the first card's glow from the other cards' Sobel boundary band.
    cv2.line(image, (180, 278), (275, 278), (200, 200, 200), 2)
    features = prepare_image(image)
    glow = Candidate(180, 275, 80, 270, 80, 278)
    assert validate_card(features, glow).valid
    grid = expand_grid(features, glow)
    assert len(grid.cards) == 8
    # Gaussian/Sobel response plus the validation band permits five pixels here.
    assert all(c.bottom < glow.bottom and abs(c.bottom - 270) <= 5 for _, c, _ in grid.cards)


def test_missing_slot_is_not_filled_or_renumbered():
    image, _ = make_screen(rows=1, missing=((0, 3),))
    result = auto_scan(image)
    assert [c.card.column for c in result.crops] == [0, 1, 2, 4, 5, 6, 7]
    assert len(result.profiles) == 2
    assert [p['grid']['columns'] for p in result.profiles] == [3, 4]


def test_column_count_comes_from_supported_frames():
    image, _ = make_screen(rows=1, columns=5)
    result = auto_scan(image)
    assert len(result.crops) == 5
    assert result.profiles[0]['grid']['columns'] == 5


def test_no_anchor_or_valid_card_has_explicit_result():
    result = auto_scan(np.zeros((500, 800, 3), np.uint8))
    assert result.error.startswith('anchor:')
    assert not result.profiles and not result.crops


@pytest.mark.parametrize('image', [None, np.zeros((10, 10), np.float32), np.zeros((0, 5), np.uint8)])
def test_invalid_input_rejected(image):
    with pytest.raises(ValueError, match='image:'):
        prepare_image(image)
