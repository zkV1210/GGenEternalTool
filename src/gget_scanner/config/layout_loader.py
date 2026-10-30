"""Strict schema-v1 JSON loader; no image I/O or coordinate resolution."""

import json
from pathlib import Path

from .layout_models import GridSpec, LayoutError, LayoutProfile, POINT_ORDER, SCALE, integer


def _object(value: object, keys: set[str], field: str) -> dict:
    if not isinstance(value, dict):
        raise LayoutError(f"{field}: expected an object")
    missing, extra = keys - value.keys(), value.keys() - keys
    if missing or extra:
        raise LayoutError(f"{field}: missing fields {sorted(missing)}; unknown fields {sorted(extra)}")
    return value


def profile_from_dict(data: object) -> LayoutProfile:
    root = _object(data, {"schema_version", "profile_id", "coordinate_system", "screen", "grid"}, "layout")
    coords = _object(root["coordinate_system"], {"type", "scale", "point_order"}, "coordinate_system")
    if (coords["type"] != "normalized_integer" or
            integer(coords["scale"], "coordinate_system.scale") != SCALE or
            coords["point_order"] != list(POINT_ORDER)):
        raise LayoutError("coordinate_system: expected normalized_integer, scale 10000, "
                          "point_order [TL, TR, BR, BL]")
    screen = _object(root["screen"], {"reference_size"}, "screen")
    grid = _object(root["grid"], {"rows", "columns", "first_card", "horizontal_step", "vertical_step"}, "grid")
    return LayoutProfile(root["profile_id"], screen["reference_size"], GridSpec(**grid), root["schema_version"])


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise LayoutError(f"JSON: duplicate field {key!r}")
        result[key] = value
    return result


def load_layout(path: str | Path) -> LayoutProfile:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        data = json.loads(text, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LayoutError(f"Cannot load layout {path}: {exc}") from exc
    return profile_from_dict(data)
