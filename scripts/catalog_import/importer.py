"""Offline acquisition, source parsing, conflict checks, and atomic catalog output."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from gget_scanner.catalog.loader import load_catalog, save_catalog
from gget_scanner.catalog.models import Catalog, CatalogError
from gget_scanner.catalog.validator import check_image, image_info, local_image_path, validate_catalog

from .soshage import parse_unit


def _event(path: Path, **record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **record}, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _identity(unit):
    return (unit.name, unit.language, unit.rarity, unit.variant, unit.role,
            tuple((s.source, s.source_id, s.page_url, s.rarity_code, s.role_code) for s in unit.sources),
            tuple((i.kind, i.source_url) for i in unit.images))


def _copy_image(path: Path, image, root: Path):
    temporary = None
    try:
        data = path.read_bytes()
        digest, width, height = image_info(data)
        # Content addressing preserves old image versions and makes repeat imports cheap.
        extension = (".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else
                     ".webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else
                     ".jpg" if data.startswith(b"\xff\xd8\xff") else ".img")
        relative = f"data/local_assets/images/{digest}{extension}"
        target = local_image_path(root, relative)
        result = replace(image, local_path=relative, status="downloaded", sha256=digest,
                         width=width, height=height, error=None)
        if target.exists():
            try:
                check_image(result, root)
                return result
            except CatalogError:
                # Preserve unexpected contents before replacing a damaged cache entry.
                damaged = target.read_bytes()
                backup = root / "data/local_assets/cache/quarantine" / f"{digest}.{sha256(damaged).hexdigest()}.invalid"
                backup.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    if backup.read_bytes() != damaged:
                        raise CatalogError("image: quarantine conflict; refusing replacement")
                else:
                    with backup.open("xb") as stream:
                        stream.write(damaged)
                        stream.flush()
                        os.fsync(stream.fileno())
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        return result
    except (OSError, CatalogError) as exc:
        return replace(image, local_path=None, status="failed", sha256=None,
                       width=None, height=None, error=str(exc))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def import_manifest(manifest_path: str | Path, *, root: str | Path = ".", limit: int = 15) -> dict:
    """Manifest paths are relative to its directory; root is the destination project."""
    if type(limit) is not int or limit < 1:
        raise CatalogError("limit: expected a positive integer")
    root = Path(root).resolve()
    manifest_path = Path(manifest_path).resolve()
    source_root = manifest_path.parent
    output = root / "data/catalog/units.json"
    log = root / "data/local_assets/cache/import_events.jsonl"
    catalog = load_catalog(output) if output.exists() else Catalog(())
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Cannot load manifest: {exc}") from exc
    if not isinstance(manifest, list):
        raise CatalogError("manifest: expected an array")
    units = {u.unit_id: u for u in catalog.units}
    source_ids = {(s.source, s.source_id): u.unit_id for u in catalog.units for s in u.sources}
    counts = dict(processed=0, added=0, updated=0, unchanged=0, conflicts=0, errors=0)
    for entry in manifest[:limit]:
        counts["processed"] += 1
        try:
            if (not isinstance(entry, dict) or not {"page_url", "html_path"} <= entry.keys()
                    or entry.keys() - {"page_url", "html_path", "local_images"}):
                raise CatalogError("manifest entry: requires page_url/html_path and optional local_images")
            supplied = entry.get("local_images", {})
            if not isinstance(supplied, dict) or any(not isinstance(k, str) for k in supplied):
                raise CatalogError("local_images: expected source URL to relative file path mapping")
            html_path = local_image_path(source_root, entry["html_path"])
            candidate = parse_unit(html_path.read_text(encoding="utf-8-sig"), entry["page_url"])
            known_urls = {i.source_url for i in candidate.images}
            if supplied.keys() - known_urls:
                raise CatalogError("local_images: URL does not belong to this unit's parsed images")
            for value in supplied.values():
                local_image_path(source_root, value)
            primary = candidate.sources[0]
            existing_id = source_ids.get((primary.source, primary.source_id), candidate.unit_id)
            candidate = replace(candidate, unit_id=existing_id)
            previous = units.get(existing_id)
            metadata_changed = previous is not None and _identity(previous) != _identity(candidate)
            if metadata_changed:
                enriched = replace(previous, rarity=candidate.rarity if previous.rarity is None else previous.rarity,
                                   role=candidate.role if previous.role is None else previous.role)
                if _identity(enriched) != _identity(candidate):
                    _event(log, type="conflict", unit_id=existing_id,
                           previous=asdict(previous), incoming=asdict(candidate))
                    counts["conflicts"] += 1
                    continue
                _event(log, type="metadata_enrichment", unit_id=existing_id,
                       previous=asdict(previous), incoming=asdict(candidate))
            images = []
            for index, image in enumerate(candidate.images):
                old = previous.images[index] if previous is not None else None
                if old is not None and old.status == "downloaded":
                    try:
                        check_image(old, root)
                        images.append(old)
                        continue
                    except CatalogError as exc:
                        image = replace(old, status="missing" if not local_image_path(root, old.local_path).is_file()
                                        else "invalid", error=str(exc))
                if image.source_url in supplied:
                    image = _copy_image(local_image_path(source_root, supplied[image.source_url]), image, root)
                elif old is not None and image.status == "not_downloaded":
                    image = old
                if image.status in ("failed", "missing", "invalid"):
                    _event(log, type="image_error", unit_id=existing_id, image=asdict(image))
                images.append(image)
            candidate = replace(candidate, images=tuple(images))
            if previous is None:
                counts["added"] += 1
            elif candidate.images == previous.images and not metadata_changed:
                counts["unchanged"] += 1
                continue
            else:
                counts["updated"] += 1
            units[existing_id] = candidate
            source_ids[(primary.source, primary.source_id)] = existing_id
        except (CatalogError, OSError, UnicodeError, ValueError) as exc:
            _event(log, type="parse_error", entry=entry, error=str(exc))
            counts["errors"] += 1
    result = Catalog(tuple(units.values()))
    if counts["added"] or counts["updated"]:
        save_catalog(output, result)
    counts["validation_issues"] = len(validate_catalog(result, root))
    return counts
