"""In-memory card crops; no layout inference, disk writes or cross-image state."""

from dataclasses import dataclass
from math import ceil, dist
from typing import Literal

import cv2
import numpy as np

from gget_scanner.config.layout_models import LayoutError, ResolvedCard, ResolvedLayout, pair, validate_quad


@dataclass(frozen=True)
class CropOptions:
    mode: Literal["bbox", "perspective"] = "bbox"
    output_size: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("bbox", "perspective"):
            raise LayoutError("crop.mode: expected bbox or perspective")
        if self.output_size is not None:
            if self.mode != "perspective":
                raise LayoutError("crop.output_size: only supported in perspective mode")
            object.__setattr__(self, "output_size", pair(self.output_size, "crop.output_size", minimum=1))


@dataclass(frozen=True)
class CropResult:
    card: ResolvedCard
    status: Literal["ok", "error"]
    image: np.ndarray | None
    error: str | None = None


def validate_image(image: np.ndarray, layout: ResolvedLayout) -> None:
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or
            image.ndim not in (2, 3) or image.size == 0 or
            (image.ndim == 3 and image.shape[2] not in (3, 4))):
        raise LayoutError("image: expected a nonempty uint8 grayscale, BGR or BGRA array")
    if (image.shape[1], image.shape[0]) != layout.image_size:
        raise LayoutError("image: dimensions do not match ResolvedLayout.image_size")


def validate_card(card: ResolvedCard, layout: ResolvedLayout) -> None:
    validate_quad(card.vertices, f"card {card.index}")
    left, top, right, bottom = layout.viewport
    width, height = layout.image_size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise LayoutError("resolved viewport is outside image bounds")
    if any(not (left <= x <= right and top <= y <= bottom) for x, y in card.vertices):
        raise LayoutError(f"card {card.index}: outside resolved viewport")
    x0, y0, x1, y1 = card.bounds
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise LayoutError(f"card {card.index}: invalid crop bounds")


def _perspective(image: np.ndarray, card: ResolvedCard, options: CropOptions) -> np.ndarray:
    tl, tr, br, bl = card.vertices
    size = options.output_size or (
        max(1, ceil(max(dist(tl, tr), dist(bl, br)))),
        max(1, ceil(max(dist(tl, bl), dist(tr, br)))),
    )
    width, height = size
    # Our points describe pixel edges. OpenCV uses pixel centers at integer coordinates.
    # Mapping edge -0.5 to edge width-0.5 preserves an identity rectangle exactly.
    source = np.asarray(card.vertices, dtype=np.float32) - 0.5
    destination = np.asarray(((-0.5, -0.5), (width - 0.5, -0.5),
                              (width - 0.5, height - 0.5), (-0.5, height - 0.5)), dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(image, matrix, size, flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)


def crop_cards(
    image: np.ndarray,
    layout: ResolvedLayout,
    options: CropOptions | None = None,
) -> tuple[CropResult, ...]:
    validate_image(image, layout)
    options = options or CropOptions()
    results = []
    for card in layout.cards:
        try:
            validate_card(card, layout)
            if options.mode == "perspective":
                crop = _perspective(image, card, options)
            else:
                left, top, right, bottom = card.bounds
                crop = image[top:bottom, left:right].copy()
            results.append(CropResult(card, "ok", crop))
        except (LayoutError, cv2.error) as exc:
            results.append(CropResult(card, "error", None, str(exc)))
    return tuple(results)
