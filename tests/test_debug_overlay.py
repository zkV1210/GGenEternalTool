import numpy as np
import pytest

from gget_scanner.image.debug_overlay import OverlayOptions, draw_overlay
from gget_scanner.image.layout import resolve_layout


def test_every_card_boundary_and_vertices(profile):
    image = np.zeros((1000, 1000, 3), dtype=np.uint8)
    layout = resolve_layout(profile, (1000, 1000))
    overlay = draw_overlay(image, layout)
    for row in range(2):
        for column in range(8):
            x, y = 50 + column * 120, 100 + row * 300
            np.testing.assert_array_equal(overlay[y + 100, x], (0, 255, 0))
            for px, py in ((x, y), (x + 80, y), (x + 80, y + 200), (x, y + 200)):
                np.testing.assert_array_equal(overlay[py, px], (0, 0, 255))
    assert not image.any()
    assert not np.shares_memory(image, overlay)


def test_options_can_disable_all_marks(profile, synthetic_image):
    overlay = draw_overlay(synthetic_image, resolve_layout(profile, (1000, 1000)),
                           OverlayOptions(False, False, False, False))
    np.testing.assert_array_equal(overlay, synthetic_image)
    assert not np.shares_memory(overlay, synthetic_image)


@pytest.mark.parametrize("options", [OverlayOptions(False, True, False, False),
                                    OverlayOptions(False, False, True, False)])
def test_labels_present_on_every_card(profile, options):
    image = np.zeros((1000, 1000, 3), dtype=np.uint8)
    overlay = draw_overlay(image, resolve_layout(profile, (1000, 1000)), options)
    for row in range(2):
        for column in range(8):
            x, y = 50 + column * 120, 100 + row * 300
            assert overlay[y + 1:y + 25, x + 1:x + 80].any()


@pytest.mark.parametrize("shape", [(1000, 1000), (1000, 1000, 4)])
def test_overlay_converts_grayscale_and_alpha_to_bgr(profile, shape):
    image = np.zeros(shape, dtype=np.uint8)
    overlay = draw_overlay(image, resolve_layout(profile, (1000, 1000)))
    assert overlay.shape == (1000, 1000, 3)
    assert not image.any()
