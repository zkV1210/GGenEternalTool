from dataclasses import replace

import cv2
import numpy as np
import pytest

from gget_scanner.config.layout_models import LayoutError, ResolvedCard, ResolvedLayout
from gget_scanner.image.cropper import CropOptions, crop_cards
from gget_scanner.image.layout import resolve_layout


@pytest.mark.parametrize("mode", ["bbox", "perspective"])
def test_exact_card_content_and_independent_memory(profile, synthetic_image, mode):
    original = synthetic_image.copy()
    layout = resolve_layout(profile, (1000, 1000))
    snapshot = repr(layout)
    crops = crop_cards(synthetic_image, layout, CropOptions(mode))
    for index, crop in enumerate(crops):
        row, column = divmod(index, 8)
        x, y = 50 + column * 120, 100 + row * 300
        assert crop.status == "ok" and crop.error is None
        assert crop.image.shape == (200, 80, 3)
        np.testing.assert_array_equal(crop.image, original[y:y + 200, x:x + 80])
        assert not np.shares_memory(crop.image, synthetic_image)
    crops[0].image[:] = 0
    np.testing.assert_array_equal(synthetic_image, original)
    assert repr(layout) == snapshot


def test_whole_image_identity_and_last_pixel():
    image = np.arange(12 * 16 * 3, dtype=np.uint8).reshape(12, 16, 3)
    card = ResolvedCard(0, 0, 0, ((0, 0), (16, 0), (16, 12), (0, 12)))
    layout = ResolvedLayout("whole", (16, 12), (0, 0, 16, 12), (card,))
    for mode in ("bbox", "perspective"):
        np.testing.assert_array_equal(crop_cards(image, layout, CropOptions(mode))[0].image, image)


def test_perspective_skew_and_corner_order():
    image = np.zeros((300, 300, 3), dtype=np.uint8)
    vertices = ((60, 40), (240, 60), (220, 260), (40, 240))
    cv2.fillConvexPoly(image, np.array(vertices, dtype=np.int32), (80, 160, 200))
    colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
    for (x, y), color in zip(vertices, colors):
        cv2.circle(image, (int(x), int(y)), 10, color, -1)
    card = ResolvedCard(0, 0, 0, vertices)
    layout = ResolvedLayout("skew", (300, 300), (0, 0, 300, 300), (card,))
    crop = crop_cards(image, layout, CropOptions("perspective", (100, 200)))[0]
    assert crop.status == "ok"
    assert crop.image.shape == (200, 100, 3)
    for sample, color in zip((crop.image[2, 2], crop.image[2, -3],
                              crop.image[-3, -3], crop.image[-3, 2]), colors):
        np.testing.assert_array_equal(sample, color)
    automatic = crop_cards(image, layout, CropOptions("perspective"))[0]
    assert automatic.image.shape == (201, 182, 3)


def test_per_card_errors_preserve_valid_results(profile, synthetic_image):
    layout = resolve_layout(profile, (1000, 1000))
    bad_card = replace(layout.cards[0], vertices=((-1, 100), (130, 100), (130, 300), (-1, 300)))
    results = crop_cards(synthetic_image, replace(layout, cards=(bad_card, layout.cards[1])))
    assert results[0].status == "error" and results[0].image is None
    assert "outside" in results[0].error
    assert results[1].status == "ok"


@pytest.mark.parametrize("image", [None, np.zeros((10, 10), dtype=np.float32),
                                   np.zeros((0, 10, 3), dtype=np.uint8),
                                   np.zeros((1000, 1000, 2), dtype=np.uint8),
                                   np.zeros((50, 50, 3), dtype=np.uint8)])
def test_invalid_image(profile, image):
    with pytest.raises(LayoutError):
        crop_cards(image, resolve_layout(profile, (1000, 1000)))


@pytest.mark.parametrize("mode,size", [("bad", None), ("bbox", (10, 10)),
                                      ("perspective", (0, 10)), ("perspective", (True, 10))])
def test_invalid_options(mode, size):
    with pytest.raises(LayoutError):
        CropOptions(mode, size)


@pytest.mark.parametrize("channels", [None, 4])
def test_grayscale_and_alpha(profile, channels):
    shape = (1000, 1000) if channels is None else (1000, 1000, channels)
    image = np.full(shape, 128, dtype=np.uint8)
    layout = resolve_layout(profile, (1000, 1000))
    result = crop_cards(image, layout, CropOptions("perspective"))[0]
    expected_shape = (200, 80) if channels is None else (200, 80, channels)
    assert result.image.shape == expected_shape
    assert np.all(result.image == 128)
