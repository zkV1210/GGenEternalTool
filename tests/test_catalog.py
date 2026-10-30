from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from gget_scanner.catalog import Catalog, CatalogError, load_catalog
from gget_scanner.catalog.loader import catalog_from_dict, save_catalog
from gget_scanner.catalog.models import Unit, UnitImage, UnitSource, identity_id
from gget_scanner.catalog.validator import image_info, validate_catalog


def unit_record(source_id="100"):
    return Unit(identity_id("test", source_id), "Synthetic unit", "zh-TW", "UR", None, None,
                (UnitSource("test", source_id, f"https://example.com/unit/{source_id}",
                            "2026-10-30T00:00:00+00:00"),),
                (UnitImage("artwork", f"https://example.com/image/{source_id}.png"),))


def raw_record():
    return json.loads(json.dumps(asdict(Catalog((unit_record(),)))))


def test_roundtrip_lookup_nulls_and_stable_identity(tmp_path):
    unit = unit_record()
    path = tmp_path / "units.json"
    save_catalog(path, Catalog((unit,)))
    catalog = load_catalog(path)
    assert catalog.get(unit.unit_id) == unit
    assert catalog.get(unit.unit_id).variant is None
    assert unit.unit_id == identity_id("test", "100")
    assert unit.unit_id != identity_id("test", "101")
    assert unit.unit_id != identity_id("another-source", "100")
    with pytest.raises(KeyError):
        catalog.get("absent")


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema_version=True),
    lambda d: d.update(schema_version=2),
    lambda d: d.update(extra=1),
    lambda d: d.update(units={}),
    lambda d: d["units"].append(d["units"][0]),
    lambda d: d["units"][0].update(unit_id="name-as-id"),
    lambda d: d["units"][0].update(name=123),
    lambda d: d["units"][0].update(rarity="SSP"),
    lambda d: d["units"][0].update(sources=[]),
    lambda d: d["units"][0]["sources"].append(d["units"][0]["sources"][0]),
    lambda d: d["units"][0]["sources"][0].update(source_id=100),
    lambda d: d["units"][0]["sources"][0].update(retrieved_at="2026-10-30"),
    lambda d: d["units"][0]["sources"][0].update(page_url="http://example.com"),
    lambda d: d["units"][0]["sources"][0].update(page_url="https://[invalid"),
    lambda d: d["units"][0]["images"][0].update(status="downloaded"),
    lambda d: d["units"][0]["images"][0].update(status="failed"),
    lambda d: d["units"][0]["images"][0].update(width=True),
    lambda d: d["units"][0]["images"][0].update(sha256="not-a-hash"),
    lambda d: d["units"][0]["images"][0].update(local_path="../outside.png"),
    lambda d: d["units"][0]["images"][0].update(local_path="C:/outside.png"),
    lambda d: d["units"][0]["images"].append(d["units"][0]["images"][0]),
])
def test_strict_schema(mutate):
    data = raw_record()
    mutate(data)
    with pytest.raises(CatalogError):
        catalog_from_dict(data)


def test_json_duplicate_key_and_source_identity_collision(tmp_path):
    path = tmp_path / "units.json"
    path.write_text('{"schema_version":1,"schema_version":1,"units":[]}', encoding="utf-8")
    with pytest.raises(CatalogError, match="duplicate field"):
        load_catalog(path)
    a, b = unit_record(), replace(unit_record(), unit_id=identity_id("test", "other"))
    with pytest.raises(CatalogError, match="source identity"):
        catalog_from_dict(json.loads(json.dumps(asdict(Catalog((a, b))))))


def test_image_decode_hash_missing_changed_and_multiple_purposes(tmp_path):
    encoded = cv2.imencode(".png", np.full((8, 9, 3), 42, np.uint8))[1].tobytes()
    digest, width, height = image_info(encoded)
    assert (digest, width, height) == (sha256(encoded).hexdigest(), 9, 8)
    path = tmp_path / "機體.png"
    path.write_bytes(encoded)
    image = UnitImage("game_list_reference", "https://example.com/list.png", "機體.png",
                      "downloaded", digest, width, height)
    unit = replace(unit_record(), images=(image,))
    catalog = Catalog((unit,))
    assert validate_catalog(catalog, tmp_path) == ()
    assert catalog.reference_paths(unit.unit_id, tmp_path) == (path,)
    assert catalog.reference_paths(unit.unit_id, tmp_path, kind="artwork") == ()
    path.write_bytes(cv2.imencode(".png", np.full((8, 9, 3), 43, np.uint8))[1].tobytes())
    assert any("hash" in i.message for i in validate_catalog(catalog, tmp_path))
    with pytest.raises(CatalogError):
        catalog.reference_paths(unit.unit_id, tmp_path)
    path.write_bytes(b"not an image")
    assert any("decode" in i.message for i in validate_catalog(catalog, tmp_path))
    path.unlink()
    assert any("cannot read" in i.message for i in validate_catalog(catalog, tmp_path))


def test_nulls_are_reported_without_repair_and_empty_images_rejected_as_complete(tmp_path):
    unit = replace(unit_record(), name=None, rarity=None, images=())
    path = tmp_path / "units.json"
    save_catalog(path, Catalog((unit,)))
    loaded = load_catalog(path)
    assert loaded.get(unit.unit_id).name is None
    assert {i.field for i in validate_catalog(loaded, tmp_path)} == {"name", "rarity", "images"}


def test_interrupted_atomic_output_preserves_previous_catalog(tmp_path):
    path = tmp_path / "units.json"
    save_catalog(path, Catalog((unit_record(),)))
    before = path.read_bytes()
    with patch("gget_scanner.catalog.loader.os.replace", side_effect=OSError("disk failure")):
        with pytest.raises(OSError):
            save_catalog(path, Catalog((unit_record("101"),)))
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []
