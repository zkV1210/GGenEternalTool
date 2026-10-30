import cv2
import numpy as np

from scripts.layout_edge_probe import edge_maps
from gget_scanner.image.card_detection import prepare_image


def test_strength_preserves_contrast_lost_in_current_binary_edges():
    image = np.zeros((100, 80, 3), np.uint8)
    image[20:35] = 50
    image[60:75] = 200
    binary, strength = edge_maps(image)
    np.testing.assert_array_equal(binary, prepare_image(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)).horizontal)
    assert binary[18:22].sum() == binary[58:62].sum() > 0
    assert strength[58:62].max() > 3 * strength[18:22].max() > 0
    assert np.isfinite(strength).all()


def test_strength_keeps_horizontal_orientation_filter():
    image = np.zeros((100, 80, 3), np.uint8)
    cv2.line(image, (40, 10), (40, 90), (255, 255, 255), 2)
    binary, strength = edge_maps(image)
    np.testing.assert_array_equal(binary, prepare_image(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)).horizontal)
    assert not binary[20:80].any()
    assert not strength[20:80].any()
