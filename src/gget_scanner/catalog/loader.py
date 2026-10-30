"""Strict JSON loading and atomic writing, with no network or source HTML."""

from dataclasses import asdict, fields
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import UUID

from .models import Catalog, CatalogError, Unit, UnitImage, UnitSource
from .validator import local_image_path


def _object(value, model):
    if not isinstance(value, dict) or set(value) != {f.name for f in fields(model)}:
        raise CatalogError(f"{model.__name__}: expected exactly the schema fields")
    return value


def _text(value, field, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{field}: expected a nonempty string")


def _url(value, field, *, nullable=False):
    from urllib.parse import urlsplit

    if nullable and value is None:
        return
    _text(value, field)
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise CatalogError(f"{field}: malformed URL") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CatalogError(f"{field}: expected an HTTPS URL without credentials")


def catalog_from_dict(value: object) -> Catalog:
    root = _object(value, Catalog)
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise CatalogError("schema_version: only integer 1 is supported")
    if not isinstance(root["units"], list):
        raise CatalogError("units: expected an array")
    units, ids, source_keys = [], set(), set()
    for raw in root["units"]:
        row = _object(raw, Unit)
        _text(row["unit_id"], "unit_id")
        try:
            if str(UUID(row["unit_id"])) != row["unit_id"]:
                raise ValueError("noncanonical UUID")
        except ValueError as exc:
            raise CatalogError("unit_id: expected a canonical UUID") from exc
        if row["unit_id"] in ids:
            raise CatalogError("duplicate unit_id")
        ids.add(row["unit_id"])
        for name in ("name", "language", "rarity", "variant", "role"):
            _text(row[name], name, nullable=True)
        if row["rarity"] not in (None, "N", "R", "SR", "SSR", "UR"):
            raise CatalogError("rarity: expected base rarity, never SP/SSP")
        if not isinstance(row["sources"], list) or not row["sources"]:
            raise CatalogError("sources: expected a nonempty array")
        sources = []
        for raw_source in row["sources"]:
            source = _object(raw_source, UnitSource)
            for name in ("source", "source_id", "retrieved_at"):
                _text(source[name], name)
            for name in ("rarity_code", "role_code"):
                _text(source[name], name, nullable=True)
            _url(source["page_url"], "page_url")
            try:
                if datetime.fromisoformat(source["retrieved_at"]).utcoffset() is None:
                    raise ValueError("missing timezone")
            except ValueError as exc:
                raise CatalogError("retrieved_at: expected ISO timestamp with timezone") from exc
            key = (source["source"], source["source_id"])
            if key in source_keys:
                raise CatalogError("duplicate source identity")
            source_keys.add(key)
            sources.append(UnitSource(**source))
        if not isinstance(row["images"], list):
            raise CatalogError("images: expected an array")
        images, image_keys = [], set()
        for raw_image in row["images"]:
            image = _object(raw_image, UnitImage)
            if image["kind"] not in ("artwork", "thumbnail", "game_list_reference"):
                raise CatalogError("image.kind: unsupported purpose")
            if image["status"] not in ("not_downloaded", "downloaded", "failed", "missing", "invalid"):
                raise CatalogError("image.status: unsupported status")
            _url(image["source_url"], "source_url", nullable=True)
            _text(image["error"], "image.error", nullable=True)
            if image["local_path"] is not None:
                local_image_path(Path.cwd(), image["local_path"])
            if image["sha256"] is not None and (not isinstance(image["sha256"], str) or
                    re.fullmatch(r"[0-9a-f]{64}", image["sha256"]) is None):
                raise CatalogError("image.sha256: expected lowercase SHA-256")
            for name in ("width", "height"):
                if image[name] is not None and (type(image[name]) is not int or image[name] < 1):
                    raise CatalogError(f"image.{name}: expected a positive integer or null")
            if image["status"] == "downloaded" and (image["error"] is not None or
                    any(image[k] is None for k in ("local_path", "sha256", "width", "height"))):
                raise CatalogError("downloaded image: requires path, hash, dimensions and no error")
            if image["status"] in ("failed", "missing", "invalid") and image["error"] is None:
                raise CatalogError("failed image: requires an error")
            key = (image["kind"], image["source_url"], image["local_path"])
            if key in image_keys:
                raise CatalogError("duplicate image reference")
            image_keys.add(key)
            images.append(UnitImage(**image))
        units.append(Unit(**{**row, "sources": tuple(sources), "images": tuple(images)}))
    return Catalog(tuple(units))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"JSON: duplicate field {key}")
        result[key] = value
    return result


def load_catalog(path: str | Path) -> Catalog:
    try:
        return catalog_from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Cannot load catalog {path}: {exc}") from exc


def atomic_json(path: Path, value: object) -> None:
    """Same-directory replacement; failed writes leave the previous file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_catalog(path: str | Path, catalog: Catalog) -> None:
    value = json.loads(json.dumps(asdict(catalog)))
    catalog_from_dict(value)
    atomic_json(Path(path), value)
