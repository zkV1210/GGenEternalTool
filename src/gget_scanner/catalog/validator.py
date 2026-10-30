"""Metadata integrity and optional local reference-image verification."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

import cv2
import numpy as np

from .models import Catalog, CatalogError, UnitImage


@dataclass(frozen=True)
class ValidationIssue:
    unit_id: str
    field: str
    message: str


def local_image_path(root: Path, value: str | None) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise CatalogError("image.local_path: expected a relative POSIX path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise CatalogError("image.local_path: must stay inside the catalog root")
    target = (root / value).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise CatalogError("image.local_path: escapes catalog root")
    return target


def image_info(data: bytes) -> tuple[str, int, int]:
    try:
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    except cv2.error as exc:
        raise CatalogError(f"image: cannot decode: {exc}") from exc
    if decoded is None or decoded.size == 0:
        raise CatalogError("image: cannot decode")
    height, width = decoded.shape[:2]
    return sha256(data).hexdigest(), width, height


def check_image(image: UnitImage, root: Path) -> None:
    path = local_image_path(root, image.local_path)
    try:
        actual = image_info(path.read_bytes())
    except OSError as exc:
        raise CatalogError(f"image: cannot read {path}: {exc}") from exc
    if actual != (image.sha256, image.width, image.height):
        raise CatalogError("image: hash or dimensions do not match the catalog")


def validate_catalog(catalog: Catalog, root: str | Path | None = None) -> tuple[ValidationIssue, ...]:
    """Report all incomplete records; nulls remain null, and nothing is repaired."""
    issues = []
    identities, source_keys = set(), set()
    for unit in catalog.units:
        def issue(field, message):
            issues.append(ValidationIssue(unit.unit_id, field, message))

        if unit.unit_id in identities:
            issue("unit_id", "duplicate unit ID")
        identities.add(unit.unit_id)
        for field in ("name", "rarity"):
            if getattr(unit, field) is None:
                issue(field, "missing value")
        if not unit.sources:
            issue("sources", "missing source identity")
        for source in unit.sources:
            key = (source.source, source.source_id)
            if key in source_keys:
                issue("sources", f"duplicate source identity: {key}")
            source_keys.add(key)
        if not unit.images:
            issue("images", "missing image reference")
        usable = False
        for image in unit.images:
            if image.status != "downloaded":
                issue("images", f"{image.kind}: {image.status}; {image.error or 'no usable local file'}")
                continue
            if root is not None:
                try:
                    check_image(image, Path(root))
                except CatalogError as exc:
                    issue("images", str(exc))
                    continue
            usable = True
        if not usable:
            issue("images", "no verified local reference image")
    return tuple(issues)
