"""Optional local validation; the public suite never requires game assets."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from gget_scanner.config.layout_loader import load_layout
from gget_scanner.image.cropper import CropOptions
from gget_scanner.pipeline.quick_scan import quick_scan


@pytest.mark.parametrize("mode", ["bbox", "perspective"])
def test_private_screenshot(mode):
    root = Path(__file__).resolve().parents[1]
    path = root / "tests/fixtures/private/Test.png"
    if not path.exists():
        path = path.with_name("Test_UR.png")
    if not path.exists():
        pytest.skip("Optional private Test.png is not available")
    source = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(source, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert image is not None and image.shape == (1668, 2388, 3)
    profile = load_layout(root / "data/profiles/test_screenshot.json")
    original = image.copy()
    result = quick_scan(image, profile, CropOptions(mode))
    assert len(result.crops) == 16
    for index, crop in enumerate(result.crops):
        assert crop.status == "ok"
        assert (crop.card.row, crop.card.column, crop.card.index) == (*divmod(index, 8), index)
        assert 0 < crop.image.shape[0] <= 419
        assert 0 < crop.image.shape[1] <= 219
        assert crop.card.bounds[3] <= 1040  # Third row begins below this selected region.
        if mode == "bbox":
            x0, y0, x1, y1 = crop.card.bounds
            np.testing.assert_array_equal(crop.image, image[y0:y1, x0:x1])
    assert result.overlay.shape == image.shape
    np.testing.assert_array_equal(image, original)
    assert path.read_bytes() == source
