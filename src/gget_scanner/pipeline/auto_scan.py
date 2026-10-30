"""Single-image automatic layout pipeline and CLI; no recognition or tracking."""

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import cv2
import numpy as np

from gget_scanner.config.layout_loader import profile_from_dict
from gget_scanner.config.layout_models import LayoutError, ResolvedCard, ResolvedLayout, SCALE
from gget_scanner.image.card_detection import (
    Candidate, GridRow, Validation, detect_anchor, detect_card, detect_next_row,
    expand_grid, prepare_image, validate_card,
)
from gget_scanner.image.cropper import CropResult, crop_cards
from gget_scanner.image.debug_overlay import draw_overlay
from gget_scanner.image.layout import resolve_layout
from .quick_scan import _write_image


@dataclass(frozen=True)
class RowAttempt:
    row: int
    roi: tuple[int, int, int, int]
    candidate: Candidate | None
    validation: Validation | None


@dataclass(frozen=True)
class AutoScanResult:
    anchor: tuple[int, int, int, int] | None
    attempts: tuple[RowAttempt, ...]
    rows: tuple[tuple[int, GridRow], ...]
    profiles: tuple[dict, ...]
    layout: ResolvedLayout
    crops: tuple[CropResult, ...]
    overlay: np.ndarray
    error: str | None = None


def _profile(image_size, first, columns, step, second=None):
    width, height = image_size
    def point(x, y):
        return [round(x * SCALE / width), round(y * SCALE / height)]
    x0, y0, x1, y1 = first.bounds
    return {
        "schema_version": 1, "profile_id": "auto_detected",
        "coordinate_system": {"type": "normalized_integer", "scale": SCALE,
                              "point_order": ["TL", "TR", "BR", "BL"]},
        "screen": {"reference_size": [width, height]},
        "grid": {"rows": 2 if second else 1, "columns": columns,
                 "first_card": [point(x0, y0), point(x1, y0), point(x1, y1), point(x0, y1)],
                 "horizontal_step": [round((step or 0) * SCALE / width), 0],
                 "vertical_step": point(second.left - first.left, second.top - first.top)
                 if second else [0, 0]},
    }


def _export_layout(features, rows):
    """Keep v1 rectangular grids; split holes rather than filling rejected slots."""
    height, width = features.gray.shape
    size = (width, height)
    profiles, resolved_cards = [], []

    def resolve(data, sources):
        layout = resolve_layout(profile_from_dict(data), size)
        if len(layout.cards) != len(sources):
            return None
        for card, (_, _, detected, _) in zip(layout.cards, sources):
            bounds = card.bounds
            c = Candidate(bounds[0], bounds[2], bounds[1], bounds[3], bounds[1], bounds[3])
            if (max(abs(a - b) for a, b in zip(bounds, detected.bounds)) > detected.width * .06
                    or not validate_card(features, c, detected).valid):
                return None
        return layout

    def append(data, sources, layout):
        data["profile_id"] = f"auto_detected_{len(profiles):03d}"
        profiles.append(data)
        for card, (row, column, _, _) in zip(layout.cards, sources):
            resolved_cards.append(ResolvedCard(row, column, len(resolved_cards), card.vertices))

    # Try the ordinary two-row grid first, but only if every slot was validated.
    if len(rows) == 2:
        (r0, a), (r1, b) = rows
        ca = [column for column, _, _ in a.cards]
        cb = [column for column, _, _ in b.cards]
        if ca and ca == cb and ca == list(range(ca[0], ca[-1] + 1)):
            sources = [(r, column, c, v) for r, g in rows for column, c, v in g.cards]
            data = _profile(size, a.cards[0][1], len(ca), a.step_x, b.cards[0][1])
            layout = resolve(data, sources)
            if layout:
                append(data, sources, layout)
                return tuple(profiles), tuple(resolved_cards)

    for row, grid in rows:
        groups = []
        for item in grid.cards:
            if not groups or item[0] != groups[-1][-1][0] + 1:
                groups.append([])
            groups[-1].append(item)
        for group in groups:
            sources = [(row, column, c, v) for column, c, v in group]
            data = _profile(size, group[0][1], len(group), grid.step_x)
            layout = resolve(data, sources)
            if layout is None:
                raise LayoutError("layout export: normalized geometry failed edge validation")
            append(data, sources, layout)
    return tuple(profiles), tuple(resolved_cards)


def auto_scan(image: np.ndarray) -> AutoScanResult:
    features = prepare_image(image)
    height, width = features.gray.shape
    attempts, rows = [], []
    anchor, error = None, None
    try:
        anchor = detect_anchor(features)
    except LayoutError as exc:
        error = str(exc)
    if anchor:
        roi = (anchor[0], anchor[1] + max(3, round(height * .006)),
               min(anchor[2], anchor[0] + round(width * .18)),
               min(height, anchor[1] + round(height * .6)))
        reference, grid_reference = None, None
        # Only a rejected initial row allows a third attempt. A rejected second
        # row ends the scan, even when no complete rows have been found.
        for row in range(3):
            candidate = detect_card(features, roi, reference)
            validation = validate_card(features, candidate, reference) if candidate else None
            attempts.append(RowAttempt(row, roi, candidate, validation))
            if validation and validation.valid:
                grid = expand_grid(features, candidate, grid_reference)
                if grid.cards:
                    rows.append((row, grid))
                    reference, grid_reference = candidate, grid
            if len(rows) == 2 or (row >= 1 and not (validation and validation.valid)):
                break
            roi = detect_next_row(features, candidate, roi)
            if roi is None:
                break
    profiles, cards = _export_layout(features, rows)
    layout = ResolvedLayout("auto_detected", (width, height), (0, 0, width, height), cards)
    crops = crop_cards(image, layout)
    overlay = draw_overlay(image, layout)
    if anchor:
        cv2.line(overlay, anchor[:2], anchor[2:], (255, 255, 0), 2)
        cv2.circle(overlay, anchor[:2], 6, (0, 255, 255), -1)
    for attempt in attempts:
        c = attempt.candidate
        valid = attempt.validation and attempt.validation.valid
        if c and not valid:
            bounds = c.bounds or (c.left, c.visible_top, c.right, c.visible_bottom)
            cv2.rectangle(overlay, bounds[:2], bounds[2:], (0, 0, 255), 2)
        if not valid:
            reason = attempt.validation.reason if attempt.validation else "no candidate"
            cv2.putText(overlay, f"r{attempt.row}: {reason}",
                        (attempt.roi[0], min(height - 10, attempt.roi[1] + 18)),
                        cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 255), 1, cv2.LINE_AA)
    if not cards and error is None:
        error = "no complete validated cards"
    return AutoScanResult(anchor, tuple(attempts), tuple(rows), profiles, layout, crops, overlay, error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect up to two complete card rows and export schema-v1 layouts.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New directory; never overwrite existing output")
    args = parser.parse_args(argv)
    try:
        image = cv2.imdecode(np.frombuffer(args.image.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise LayoutError(f"image: cannot decode {args.image}")
        result = auto_scan(image)
        if any(crop.status != "ok" for crop in result.crops):
            raise LayoutError("one or more crops failed")
        args.output.mkdir(parents=True, exist_ok=False)
        profile_files = []
        for i, data in enumerate(result.profiles):
            filename = "layout.json" if len(result.profiles) == 1 else f"layout_{i:03d}.json"
            with (args.output / filename).open("x", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
            profile_files.append(filename)
        records = []
        evidence = {(row, col): (c, v) for row, grid in result.rows for col, c, v in grid.cards}
        offset = 0
        for i, data in enumerate(result.profiles):
            count = data["grid"]["rows"] * data["grid"]["columns"]
            for local_index, crop in enumerate(result.crops[offset:offset + count]):
                card = crop.card
                filename = f"card_{card.index:03d}_r{card.row}_c{card.column}.png"
                _write_image(args.output / filename, crop.image)
                detected, validation = evidence[card.row, card.column]
                records.append({"index": card.index, "row": card.row, "column": card.column,
                                "bounds": card.bounds, "vertices": card.vertices,
                                "detected_bounds": detected.bounds,
                                "edge_support": dict(zip(("left", "top", "right", "bottom"), validation.support)),
                                "layout_file": profile_files[i], "layout_index": local_index,
                                "status": crop.status, "file": filename})
            offset += count
        _write_image(args.output / "overlay.png", result.overlay)
        manifest = {"image_size": result.layout.image_size, "anchor": result.anchor,
                    "status": "ok" if result.crops else "no_valid_cards", "error": result.error,
                    "attempts": [asdict(a) for a in result.attempts],
                    "rows": [{"row": r, "step_x": g.step_x} for r, g in result.rows],
                    "layouts": profile_files, "cards": records}
        with (args.output / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
    except (LayoutError, OSError, cv2.error) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(f"Detected {len(result.crops)} cards. Output: {args.output}")
    return 0 if result.crops else 1


if __name__ == "__main__":
    raise SystemExit(main())
