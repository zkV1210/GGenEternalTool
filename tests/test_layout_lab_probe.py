import cv2
import numpy as np

from scripts.layout_lab_probe import gradients


def test_chroma_gradients_suppress_a_neutral_brightness_edge():
    image = np.zeros((100, 80, 3), np.uint8)
    image[50:] = 200
    maps = gradients(image)
    assert maps['horizontal']['rgb'].max() > 100
    assert maps['horizontal']['ab'].max() < .1
    assert maps['horizontal']['chroma'].max() < .1
    assert not maps['vertical']['ab'].any()


def test_chroma_gradient_detects_colored_edges_in_both_directions():
    image = np.zeros((100, 100, 3), np.uint8)
    image[25:75, 25:75] = (40, 80, 200)
    maps = gradients(image)
    for direction in maps.values():
        assert direction['ab'].max() > 20
        assert direction['chroma'].max() > 20
        assert np.isfinite(direction['ab']).all()
        assert (direction['ab'] >= 0).all()


def test_constant_color_does_not_create_chroma_edges():
    maps = gradients(np.full((80, 80, 3), (40, 80, 200), np.uint8))
    for direction in maps.values():
        for values in direction.values():
            assert not values.any()


def test_chroma_discards_hue_changes_at_equal_chroma():
    lab = np.zeros((100, 80, 3), np.float32)
    lab[:, :, 0] = 60
    lab[:50, :, 1] = 20
    lab[50:, :, 1] = -20
    image = np.uint8(np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2BGR), 0, 1) * 255)
    horizontal = gradients(image)['horizontal']
    assert horizontal['ab'].max() > 40
    assert horizontal['chroma'].max() < horizontal['ab'].max() * .1
