"""Resize valid card crops without changing the caller's original array."""

from math import isclose

import cv2
import numpy as np

from .config import NormalizationConfig
from .models import NormalizationResult


def normalize_card(image, config: NormalizationConfig | None = None) -> NormalizationResult:
    config = config or NormalizationConfig()
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.size == 0 or
            image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[2] not in (3, 4))):
        return NormalizationResult(image if isinstance(image, np.ndarray) else None,
                                   None, None, "INVALID_IMAGE", reason="expected nonempty uint8 grayscale, BGR or BGRA")
    height, width = image.shape[:2]
    target_width, target_height = config.size
    error = abs((width / height) / (target_width / target_height) - 1)
    if error > config.ratio_tolerance and not isclose(error, config.ratio_tolerance, rel_tol=0, abs_tol=1e-12):
        return NormalizationResult(image, None, (width, height), "ASPECT_RATIO_MISMATCH", error,
                                   "card aspect ratio exceeds tolerance; classification skipped")
    if image.ndim == 3 and image.shape[2] == 4 and np.any(image[:, :, 3] != 255):
        return NormalizationResult(image, None, (width, height), "UNSUPPORTED_TRANSPARENCY", error,
                                   "transparent card pixels have no defined UI color")
    source = image[:, :, :3] if image.ndim == 3 and image.shape[2] == 4 else image
    interpolation = (cv2.INTER_AREA if target_width <= width and target_height <= height
                     else cv2.INTER_LINEAR)
    normalized = cv2.resize(source, config.size, interpolation=interpolation)
    return NormalizationResult(image, normalized, (width, height), "OK", error)
