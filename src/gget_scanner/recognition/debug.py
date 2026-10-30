"""Optional filesystem diagnostics, kept out of classifier decisions."""

import json
from pathlib import Path

import cv2

from .rarity import border_features
from .references import write_image


def write_debug(result, config, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    diagnostics = result.to_dict()
    image = result.normalization.normalized
    if image is not None:
        write_image(directory / "normalized.png", image)
        overlay = image.copy()
        for index, region in enumerate(config.rarity.regions):
            x0, y0, x1, y1 = config.scale_box(region)
            write_image(directory / f"border_{index}.png", image[y0:y1, x0:x1])
            cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), (0, 255, 0), 1)
        x0, y0, x1, y1 = config.scale_box(config.role.search_region)
        write_image(directory / "role_search.png", image[y0:y1, x0:x1])
        cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), (255, 180, 0), 1)
        if result.role.bbox is not None:
            x0, y0, x1, y1 = result.role.bbox
            write_image(directory / "badge_candidate.png", image[y0:y1, x0:x1])
            cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), (0, 0, 255), 1)
        write_image(directory / "regions.png", overlay)
        if image.ndim == 3:
            diagnostics["border_histograms"] = border_features(image, config).tolist()
    with (directory / "scores.json").open("x", encoding="utf-8") as stream:
        json.dump(diagnostics, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
