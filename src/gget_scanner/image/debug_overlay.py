"""Draw resolved geometry on a fresh image, never on the input array."""

from dataclasses import dataclass

import cv2
import numpy as np

from gget_scanner.config.layout_models import ResolvedLayout
from .cropper import validate_card, validate_image


@dataclass(frozen=True)
class OverlayOptions:
    show_vertices: bool = True
    show_indices: bool = True
    show_row_column: bool = True
    show_grid: bool = True


def draw_overlay(
    image: np.ndarray,
    layout: ResolvedLayout,
    options: OverlayOptions | None = None,
) -> np.ndarray:
    validate_image(image, layout)
    options = options or OverlayOptions()
    if image.ndim == 2:
        output = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        output = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    else:
        output = image.copy()
    for card in layout.cards:
        validate_card(card, layout)
        # Drawing is the only stage where subpixel points are rounded to centers.
        points = np.floor(np.asarray(card.vertices) + 0.5).astype(np.int32)
        points[:, 0] = np.clip(points[:, 0], 0, output.shape[1] - 1)
        points[:, 1] = np.clip(points[:, 1], 0, output.shape[0] - 1)
        if options.show_grid:
            cv2.polylines(output, [points], True, (0, 255, 0), 2, cv2.LINE_AA)
        if options.show_vertices:
            for point in points:
                cv2.circle(output, tuple(point), 3, (0, 0, 255), -1)
        parts = []
        if options.show_indices:
            parts.append(f"#{card.index}")
        if options.show_row_column:
            parts.append(f"r{card.row} c{card.column}")
        if parts:
            anchor = (int(points[0, 0]) + 4, min(output.shape[0] - 3, int(points[0, 1]) + 18))
            label = " ".join(parts)
            cv2.putText(output, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(output, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    return output
