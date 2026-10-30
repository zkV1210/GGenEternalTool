from dataclasses import asdict, replace
import json

import numpy as np
import pytest

from gget_scanner.recognition.config import (NormalizationConfig, RecognitionConfig,
                                            config_from_dict, load_config)
from gget_scanner.recognition.models import RecognitionError
from gget_scanner.recognition.normalizer import normalize_card


@pytest.mark.parametrize("size", [(194, 391), (204, 397), (195, 395), (192, 397), (400, 800), (100, 200)])
def test_normal_sizes_and_original_unchanged(size):
    width, height = size
    image = np.random.default_rng(11).integers(0, 256, (height, width, 3), dtype=np.uint8)
    before = image.copy()
    result = normalize_card(image)
    assert result.status == "OK"
    assert result.original is image
    assert result.original_size == size
    assert result.normalized.shape == (400, 200, 3)
    assert not np.shares_memory(image, result.normalized)
    np.testing.assert_array_equal(image, before)


def test_bad_ratio_is_not_stretched_and_tolerance_is_relative():
    image = np.zeros((400, 220, 3), np.uint8)
    result = normalize_card(image)
    assert result.status == "ASPECT_RATIO_MISMATCH"
    assert result.normalized is None
    assert result.relative_ratio_error == pytest.approx(0.1)
    assert normalize_card(image, NormalizationConfig(ratio_tolerance=0.11)).status == "OK"


@pytest.mark.parametrize("width", [190, 210])
def test_ratio_tolerance_includes_the_exact_boundary(width):
    assert normalize_card(np.zeros((400, width, 3), np.uint8)).status == "OK"


@pytest.mark.parametrize("image", [None, [], np.empty((0, 20, 3), np.uint8),
                                  np.zeros((400, 200, 2), np.uint8), np.zeros((400, 200, 3), np.float32)])
def test_invalid_images(image):
    result = normalize_card(image)
    assert result.status == "INVALID_IMAGE" and result.normalized is None


def test_grayscale_and_opaque_alpha_and_transparency():
    assert normalize_card(np.zeros((400, 200), np.uint8)).status == "OK"
    image = np.full((400, 200, 4), 255, np.uint8)
    assert normalize_card(image).normalized.shape == (400, 200, 3)
    image[20, 20, 3] = 0
    assert normalize_card(image).status == "UNSUPPORTED_TRANSPARENCY"


def test_configurable_size_scales_rois():
    config = RecognitionConfig(normalization=NormalizationConfig((100, 200)))
    assert config.scale_box((4, 60, 14, 120)) == (2, 30, 7, 60)
    assert normalize_card(np.zeros((400, 200, 3), np.uint8), config.normalization).normalized.shape == (200, 100, 3)


def test_repository_settings_and_strict_validation(tmp_path):
    config = load_config("data/profiles/card_attributes.json")
    assert config == RecognitionConfig()
    data = {"schema_version": 1, **asdict(config)}
    assert config_from_dict(json.loads(json.dumps(data))) == config
    for mutate in (lambda d: d.update(schema_version=True), lambda d: d.update(extra=1),
                   lambda d: d["rarity"].update(max_distance=float("nan")),
                   lambda d: d["role"].update(search_region=[-1, 0, 50, 50]),
                   lambda d: d["rarity"].update(classes=["SP", "UR"]),
                   lambda d: d["rarity"].update(classes=[["SR"], "UR"]),
                   lambda d: d["normalization"].update(size=[True, 400])):
        bad = json.loads(json.dumps(data))
        mutate(bad)
        with pytest.raises(RecognitionError):
            config_from_dict(bad)
    path = tmp_path / "bad.json"
    path.write_text('{"x":1,"x":2}', encoding="utf-8")
    with pytest.raises(RecognitionError, match="duplicate"):
        load_config(path)
    with pytest.raises(RecognitionError):
        replace(config, normalization=NormalizationConfig((1, 2)))
