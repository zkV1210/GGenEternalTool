from dataclasses import replace
from html import escape
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from gget_scanner.catalog import CatalogError, load_catalog
from gget_scanner.catalog.loader import save_catalog
from gget_scanner.catalog.models import identity_id
from gget_scanner.catalog.validator import validate_catalog
from scripts.catalog_import.importer import import_manifest
from scripts.catalog_import.soshage import parse_unit


def source_page(index=0, *, name=None, rarity_alt="UR", rarity_code="5", role_code="2"):
    """Synthetic, reduced HTML modeled on observed Soshage identity markup."""
    source_id = str(1001000150 + index)
    icon = f"g0010u{150 + index:05d}"
    name = name or ("測試機體 (EX)" if index % 2 else "測試機體")
    image_url = f"https://img.kusoge.xyz/ggenet/profile/ub_{icon}.webp"
    html = (f'<h1>{escape(name)}</h1><main><img alt="{rarity_alt}" '
            f'src="https://img.kusoge.xyz/ggenet/icon/UI_Common_RarityIcon_{rarity_code}.webp">'
            f'<h2>{escape(name)}</h2><img src="{image_url}" alt="{escape(name)}"></main>'
            f'<script>data:{{unit:{{id:{source_id},rarity:{rarity_code},icon:{json.dumps(icon)},'
            f'name:{json.dumps(name)},role:{role_code},stats:{{hp:999}}}}}}</script>')
    return html, f"https://soshage.com/gget/zh-TW/unit/{source_id}", image_url


def manifest_files(tmp_path, count=15):
    inputs = tmp_path / "輸入"
    inputs.mkdir()
    entries = []
    for index in range(count):
        html, page_url, image_url = source_page(index)
        (inputs / f"{index}.html").write_text(html, encoding="utf-8")
        data = cv2.imencode(".webp", np.full((12, 10, 3), index * 10, np.uint8))[1].tobytes()
        (inputs / f"{index}.webp").write_bytes(data)
        entries.append({"page_url": page_url, "html_path": f"{index}.html",
                        "local_images": {image_url: f"{index}.webp"}})
    path = inputs / "manifest.json"
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return path


def test_parse_actual_markup_shape_and_preserve_source_codes():
    html, url, image_url = source_page(name='測試 "A" & B (EX)', rarity_alt="Rarity")
    unit = parse_unit(html, url, retrieved_at="2026-10-30T00:00:00Z")
    assert unit.unit_id == identity_id("soshage", "1001000150")
    assert unit.name == '測試 "A" & B (EX)'
    assert unit.variant == "EX"
    assert unit.rarity == "UR"
    assert unit.role == "耐久"
    assert unit.sources[0].rarity_code == "5"
    assert unit.sources[0].role_code == "2"
    assert unit.images[0].source_url == image_url
    assert unit.images[0].status == "not_downloaded"


@pytest.mark.parametrize("code,rarity", [("1", "N"), ("2", "R"), ("3", "SR"), ("4", "SSR"), ("5", "UR"), ("9", None)])
def test_user_confirmed_rarity_mapping(code, rarity):
    html, url, _ = source_page(rarity_code=code, rarity_alt="Rarity")
    unit = parse_unit(html, url)
    assert unit.rarity == rarity
    assert unit.sources[0].rarity_code == code


@pytest.mark.parametrize("code,role", [("1", "攻擊"), ("2", "耐久"), ("3", "支援"), ("9", None)])
def test_user_confirmed_role_mapping(code, role):
    html, url, _ = source_page(role_code=code)
    unit = parse_unit(html, url)
    assert unit.role == role
    assert unit.sources[0].role_code == code


def test_identity_description_does_not_end_primary_prefix_or_add_fields():
    html, url, _ = source_page()
    html = html.replace('role:2,stats:', 'desc:"contains stats:{ and ,role:1, as text",role:2,stats:')
    unit = parse_unit(html, url)
    assert unit.role == "耐久"


def test_rarity_text_cannot_disagree_with_confirmed_numeric_code():
    html, url, _ = source_page(rarity_alt="SSR")
    with pytest.raises(CatalogError):
        parse_unit(html, url)


def test_enriching_unknown_mapping_is_logged_and_preserves_identity_and_images(tmp_path):
    manifest = manifest_files(tmp_path, 1)
    import_manifest(manifest, root=tmp_path)
    path = tmp_path / "data/catalog/units.json"
    catalog = load_catalog(path)
    original = catalog.units[0]
    save_catalog(path, replace(catalog, units=(replace(original, rarity=None, role=None),)))
    result = import_manifest(manifest, root=tmp_path)
    assert result["updated"] == 1
    assert result["conflicts"] == 0
    enriched = load_catalog(path).units[0]
    assert (enriched.rarity, enriched.role) == ("UR", "耐久")
    assert enriched.unit_id == original.unit_id
    assert enriched.images == original.images
    event = json.loads((tmp_path / "data/local_assets/cache/import_events.jsonl").read_text(encoding="utf-8"))
    assert event["type"] == "metadata_enrichment"
    assert event["previous"]["rarity"] is None
    assert event["incoming"]["rarity"] == "UR"


def test_related_weapon_unit_fields_do_not_become_primary_identity():
    html, url, _ = source_page()
    html += '<script>weapons:[{unit:{unit_id:0,weapon:null}}],related:{stats:{hp:1}}</script>'
    unit = parse_unit(html, url)
    assert unit.sources[0].source_id == "1001000150"


@pytest.mark.parametrize("alter", [
    lambda html, url: (html, url.replace("1001000150", "1001000151")),
    lambda html, url: (html.replace("ub_g0010u00150", "ub_g9999u99999"), url),
    lambda html, url: (html.replace("<h1>", "<h3>"), url),
    lambda html, url: (html.replace("unit:{", "character:{"), url),
    lambda html, url: (html, url + "?id=other"),
    lambda html, url: (html.replace("img.kusoge.xyz/ggenet/profile", "other.example/ggenet/profile"), url),
])
def test_parser_rejects_ambiguous_identity(alter):
    html, url, _ = source_page()
    html, url = alter(html, url)
    with pytest.raises(CatalogError):
        parse_unit(html, url)


def test_fifteen_units_repeat_import_no_duplicate_or_image_rewrite(tmp_path):
    manifest = manifest_files(tmp_path)
    assert import_manifest(manifest, root=tmp_path)["added"] == 15
    catalog_path = tmp_path / "data/catalog/units.json"
    catalog = load_catalog(catalog_path)
    assert len(catalog.units) == 15
    assert len({u.unit_id for u in catalog.units}) == 15
    assert len({u.name for u in catalog.units}) == 2  # Names are deliberately nonunique.
    assert validate_catalog(catalog, tmp_path) == ()
    for index, unit in enumerate(catalog.units):
        assert unit.sources[0].source_id == str(1001000150 + index)
        expected = (manifest.parent / f"{index}.webp").read_bytes()
        assert unit.images[0].sha256 == sha256(expected).hexdigest()
        assert (tmp_path / unit.images[0].local_path).read_bytes() == expected
    before = catalog_path.read_bytes()
    image_times = {p: p.stat().st_mtime_ns for p in (tmp_path / "data/local_assets/images").iterdir()}
    with patch("scripts.catalog_import.importer._copy_image", side_effect=AssertionError("redundant copy")):
        result = import_manifest(manifest, root=tmp_path)
    assert result["unchanged"] == 15
    assert catalog_path.read_bytes() == before
    assert image_times == {p: p.stat().st_mtime_ns for p in image_times}


def test_incremental_limit_and_missing_image_recovery(tmp_path):
    manifest = manifest_files(tmp_path, 3)
    assert import_manifest(manifest, root=tmp_path, limit=2)["added"] == 2
    assert import_manifest(manifest, root=tmp_path, limit=3)["added"] == 1
    path = tmp_path / "data/catalog/units.json"
    catalog = load_catalog(path)
    image = catalog.units[0].images[0]
    (tmp_path / image.local_path).unlink()
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    backup = entries[0].pop("local_images")
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    assert import_manifest(manifest, root=tmp_path)["updated"] == 1
    assert load_catalog(path).units[0].images[0].status == "missing"
    entries[0]["local_images"] = backup
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    assert import_manifest(manifest, root=tmp_path)["updated"] == 1
    assert validate_catalog(load_catalog(path), tmp_path) == ()


def test_corrupt_image_is_preserved_and_repaired_from_supplied_local_file(tmp_path):
    manifest = manifest_files(tmp_path, 1)
    import_manifest(manifest, root=tmp_path)
    catalog_path = tmp_path / "data/catalog/units.json"
    image_path = tmp_path / load_catalog(catalog_path).units[0].images[0].local_path
    image_path.write_bytes(b"corrupted original")
    result = import_manifest(manifest, root=tmp_path)
    assert result["errors"] == 0
    assert validate_catalog(load_catalog(catalog_path), tmp_path) == ()
    backups = list((tmp_path / "data/local_assets/cache/quarantine").iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"corrupted original"


def test_conflict_keeps_previous_records_and_logs_both_values(tmp_path):
    manifest = manifest_files(tmp_path, 1)
    import_manifest(manifest, root=tmp_path)
    path = tmp_path / "data/catalog/units.json"
    before = path.read_bytes()
    html_path = manifest.parent / "0.html"
    html, _, _ = source_page(name="Different variant")
    html_path.write_text(html, encoding="utf-8")
    result = import_manifest(manifest, root=tmp_path)
    assert result["conflicts"] == 1
    assert path.read_bytes() == before
    event = json.loads((tmp_path / "data/local_assets/cache/import_events.jsonl").read_text(encoding="utf-8"))
    assert event["previous"]["name"] == "測試機體"
    assert event["incoming"]["name"] == "Different variant"


def test_existing_source_mapping_preserves_project_id(tmp_path):
    manifest = manifest_files(tmp_path, 1)
    import_manifest(manifest, root=tmp_path)
    path = tmp_path / "data/catalog/units.json"
    catalog = load_catalog(path)
    custom_id = identity_id("project", "curated")
    save_catalog(path, replace(catalog, units=(replace(catalog.units[0], unit_id=custom_id),)))
    import_manifest(manifest, root=tmp_path)
    assert load_catalog(path).units[0].unit_id == custom_id


def test_bad_image_and_parse_error_are_logged_and_valid_entries_continue(tmp_path):
    manifest = manifest_files(tmp_path, 3)
    (manifest.parent / "0.webp").write_bytes(b"HTML error instead of an image")
    (manifest.parent / "1.html").write_text("blocked", encoding="utf-8")
    result = import_manifest(manifest, root=tmp_path)
    assert result["errors"] == 1
    assert result["added"] == 2
    catalog = load_catalog(tmp_path / "data/catalog/units.json")
    assert catalog.units[0].images[0].status == "failed"
    assert catalog.units[0].images[0].local_path is None
    assert catalog.units[1].images[0].status == "downloaded"


def test_manifest_cannot_assign_image_from_another_unit_or_escape_paths(tmp_path):
    manifest = manifest_files(tmp_path, 1)
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    entries[0]["local_images"] = {"https://example.com/wrong.png": "0.webp"}
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    assert import_manifest(manifest, root=tmp_path)["errors"] == 1
    entries[0]["local_images"] = {}
    entries[0]["html_path"] = "../outside.html"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    assert import_manifest(manifest, root=tmp_path)["errors"] == 1
    assert not (tmp_path / "data/catalog/units.json").exists()


def test_cli_import_and_validate_unicode_paths_and_nonzero_on_missing_images(tmp_path):
    manifest = manifest_files(tmp_path, 2)
    command = [sys.executable, "-m", "scripts.catalog_import"]
    completed = subprocess.run(command + ["import", str(manifest), "--root", str(tmp_path), "--limit", "2"],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["added"] == 2
    completed = subprocess.run(command + ["validate", "--root", str(tmp_path)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    catalog = load_catalog(tmp_path / "data/catalog/units.json")
    (tmp_path / catalog.units[0].images[0].local_path).unlink()
    completed = subprocess.run(command + ["validate", "--root", str(tmp_path)], capture_output=True, text=True)
    assert completed.returncode == 1
