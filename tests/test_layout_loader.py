from dataclasses import FrozenInstanceError
import json

import pytest

from gget_scanner.config.layout_loader import load_layout, profile_from_dict
from gget_scanner.config.layout_models import LayoutError


def test_load_json(tmp_path, layout_data):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout_data), encoding="utf-8-sig")
    profile = load_layout(path)
    assert profile.profile_id == "synthetic_grid"
    assert profile.reference_size == (1000, 1000)
    assert profile.grid.first_card[0] == (500, 1000)
    with pytest.raises(FrozenInstanceError):
        profile.grid.rows = 3
    layout_data["grid"]["first_card"][0][0] = 999
    assert profile.grid.first_card[0] == (500, 1000)


@pytest.mark.parametrize("content", ['{', '[]', 'null', '{"x":1,"x":2}', '\ufffd'])
def test_invalid_json(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LayoutError):
        load_layout(path)


def test_missing_and_non_utf8_files(tmp_path):
    with pytest.raises(LayoutError, match="Cannot load"):
        load_layout(tmp_path / "missing.json")
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(LayoutError, match="Cannot load"):
        load_layout(path)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("schema_version", True), ("schema_version", 1.0),
    ("profile_id", ""), ("profile_id", 12), ("grid", None), ("screen", []),
])
def test_invalid_root_fields(layout_data, field, value):
    layout_data[field] = value
    with pytest.raises(LayoutError):
        profile_from_dict(layout_data)


def test_missing_and_unknown_fields(layout_data):
    layout_data["grid"]["colums"] = layout_data["grid"].pop("columns")
    with pytest.raises(LayoutError, match="columns.*colums"):
        profile_from_dict(layout_data)


@pytest.mark.parametrize("field,value", [
    ("scale", 1000), ("scale", True), ("scale", 10000.0),
    ("type", "pixels"), ("point_order", ["TL", "BL", "BR", "TR"]),
])
def test_coordinate_contract(layout_data, field, value):
    layout_data["coordinate_system"][field] = value
    with pytest.raises(LayoutError):
        profile_from_dict(layout_data)


@pytest.mark.parametrize("size", [[0, 10], [10, -1], [True, 10], [10.0, 10], [10], "1000"])
def test_bad_reference_size(layout_data, size):
    layout_data["screen"]["reference_size"] = size
    with pytest.raises(LayoutError):
        profile_from_dict(layout_data)


@pytest.mark.parametrize("field,value", [
    ("rows", 0), ("columns", -1), ("rows", True), ("columns", 8.0),
    ("horizontal_step", [0, 0]), ("vertical_step", [0, 0]),
    ("horizontal_step", [1000]), ("vertical_step", [0, 1.5]),
    ("first_card", [[0, 0], [100, 0], [100, 100]]),
    ("first_card", [[-1, 0], [100, 0], [100, 100], [0, 100]]),
    ("first_card", [[0, 0], [10001, 0], [10001, 100], [0, 100]]),
    ("first_card", [[0.5, 0], [100, 0], [100, 100], [0, 100]]),
    ("first_card", [[True, 0], [100, 0], [100, 100], [0, 100]]),
])
def test_grid_schema_errors(layout_data, field, value):
    layout_data["grid"][field] = value
    with pytest.raises(LayoutError):
        profile_from_dict(layout_data)


@pytest.mark.parametrize("vertices", [
    [[0, 0], [100, 0], [100, 0], [0, 100]],  # duplicate
    [[0, 0], [100, 0], [200, 0], [300, 0]],  # zero area
    [[0, 0], [100, 100], [100, 0], [0, 100]],  # crossing
    [[0, 0], [100, 0], [20, 20], [0, 100]],  # concave
    [[100, 0], [100, 100], [0, 100], [0, 0]],  # cyclic shift, same winding
    [[0, 0], [0, 100], [100, 100], [100, 0]],  # reversed
    [[0, 0], [50, 0], [100, 0], [0, 100]],  # three collinear
])
def test_invalid_quads(layout_data, vertices):
    layout_data["grid"]["first_card"] = vertices
    with pytest.raises(LayoutError):
        profile_from_dict(layout_data)


def test_slanted_convex_quad(layout_data):
    vertices = [[100, 100], [900, 150], [800, 900], [150, 850]]
    layout_data["grid"]["first_card"] = vertices
    assert profile_from_dict(layout_data).grid.first_card == tuple(map(tuple, vertices))
