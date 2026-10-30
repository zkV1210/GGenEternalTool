"""Quick Scan geometry pipeline and minimal file-based CLI."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path

import cv2
import numpy as np

from gget_scanner.config.layout_loader import load_layout
from gget_scanner.config.layout_models import Bounds, LayoutError, LayoutProfile, ResolvedLayout
from gget_scanner.image.cropper import CropOptions, CropResult, crop_cards
from gget_scanner.image.debug_overlay import OverlayOptions, draw_overlay
from gget_scanner.image.layout import resolve_layout


@dataclass(frozen=True)
class QuickScanResult:
    layout: ResolvedLayout
    crops: tuple[CropResult, ...]
    overlay: np.ndarray


def quick_scan(
    image: np.ndarray,
    profile: LayoutProfile,
    crop_options: CropOptions | None = None,
    overlay_options: OverlayOptions | None = None,
    viewport: Bounds | None = None,
) -> QuickScanResult:
    if not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
        raise LayoutError("image: expected a grayscale, BGR or BGRA array")
    layout = resolve_layout(profile, (image.shape[1], image.shape[0]), viewport)
    return QuickScanResult(layout, crop_cards(image, layout, crop_options),
                           draw_overlay(image, layout, overlay_options))


def _write_image(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError(f"Cannot encode image {path}")
    # Path I/O supports Unicode paths on Windows, independent of OpenCV's filenames.
    with path.open("xb") as stream:
        stream.write(encoded.tobytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve a layout and crop a single screenshot.")
    parser.add_argument("image", type=Path)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing paths are never overwritten")
    parser.add_argument("--mode", choices=("bbox", "perspective"), default="bbox")
    parser.add_argument("--output-size", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--viewport", nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--hide-vertices", action="store_true")
    parser.add_argument("--hide-indices", action="store_true")
    parser.add_argument("--hide-row-column", action="store_true")
    parser.add_argument("--hide-grid", action="store_true")
    args = parser.parse_args(argv)
    try:
        profile = load_layout(args.layout)
        image = cv2.imdecode(np.frombuffer(args.image.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise LayoutError(f"image: cannot decode {args.image}")
        result = quick_scan(
            image, profile, CropOptions(args.mode, args.output_size),
            OverlayOptions(not args.hide_vertices, not args.hide_indices,
                           not args.hide_row_column, not args.hide_grid),
            args.viewport,
        )
        failures = [crop for crop in result.crops if crop.status != "ok"]
        if failures:
            raise LayoutError("; ".join(crop.error for crop in failures))
        args.output.mkdir(parents=True, exist_ok=False)
        records = []
        for crop in result.crops:
            card = crop.card
            filename = f"card_{card.index:03d}_r{card.row}_c{card.column}.png"
            _write_image(args.output / filename, crop.image)
            records.append({"index": card.index, "row": card.row, "column": card.column,
                            "vertices": card.vertices, "bounds": card.bounds,
                            "status": crop.status, "error": crop.error,
                            "size": [crop.image.shape[1], crop.image.shape[0]], "file": filename})
        _write_image(args.output / "overlay.png", result.overlay)
        manifest = {"profile_id": profile.profile_id, "image_size": result.layout.image_size,
                    "viewport": result.layout.viewport, "mode": args.mode, "cards": records}
        with (args.output / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (LayoutError, OSError, cv2.error) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(f"Cropped {len(result.crops)} cards. Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
