"""Local labeled images and genuine badge templates; no model training."""

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path

import cv2
import numpy as np

from .config import load_config, read_json
from .models import RARITIES, ROLES, RecognitionError
from .normalizer import normalize_card


@dataclass(frozen=True)
class RarityReference:
    label: str
    path: str
    features: np.ndarray


@dataclass(frozen=True)
class RoleTemplate:
    label: str
    path: str
    image: np.ndarray
    mask: np.ndarray


@dataclass(frozen=True)
class ReferenceSet:
    rarity: tuple[RarityReference, ...] = ()
    role: tuple[RoleTemplate, ...] = ()
    issues: tuple[str, ...] = ()
    groups: frozenset[str] = frozenset()
    image_hashes: frozenset[str] = frozenset()


def read_image(path):
    try:
        data = Path(path).read_bytes()
        if not data:
            raise RecognitionError(f"Empty image: {path}")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RecognitionError(f"Cannot decode image: {path}")
        return image
    except (OSError, cv2.error) as exc:
        raise RecognitionError(f"Cannot read image {path}: {exc}") from exc


def write_image(path, image):
    path = Path(path)
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise RecognitionError(f"Cannot encode {path}")
    with path.open("xb") as stream:
        stream.write(encoded.tobytes())


def local_path(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise RecognitionError("image path must be relative to its manifest")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise RecognitionError("image path escapes its manifest directory")
    return path


def load_references(path, config):
    from .rarity import border_features

    data = read_json(path)
    if (not isinstance(data, dict) or set(data) != {"schema_version", "rarity_samples", "role_templates"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise RecognitionError("references: expected schema_version 1, rarity_samples and role_templates")
    root = Path(path).resolve().parent
    rarity, role, issues, groups, hashes = [], [], [], set(), set()
    conflicting_labels = False
    for kind, labels in (("rarity_samples", RARITIES), ("role_templates", ROLES)):
        if not isinstance(data[kind], list):
            raise RecognitionError(f"{kind}: expected an array")
        seen = {}
        for index, row in enumerate(data[kind]):
            try:
                if (not isinstance(row, dict) or set(row) != {"image", "label", "group"} or
                        row["label"] not in labels or not isinstance(row["group"], str) or not row["group"]):
                    raise RecognitionError("expected image, supported label and nonempty group")
                image_path = local_path(root, row["image"])
                image = read_image(image_path)
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                if digest in seen:
                    if seen[digest] != row["label"]:
                        conflicting_labels = True
                        raise RecognitionError("identical image has conflicting labels")
                    raise RecognitionError("duplicate reference image")
                seen[digest] = row["label"]
                if kind == "rarity_samples":
                    if row["label"] not in config.rarity.classes:
                        continue
                    normalized = normalize_card(image, config.normalization)
                    if normalized.status != "OK" or normalized.normalized.ndim != 3:
                        raise RecognitionError(f"expected a usable color rarity image; normalization={normalized.status}")
                    rarity.append(RarityReference(row["label"], row["image"],
                                                  border_features(normalized.normalized, config)))
                else:
                    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4):
                        raise RecognitionError("template must be uint8 BGR or BGRA")
                    mask = image[:, :, 3] if image.shape[2] == 4 else np.full(image.shape[:2], 255, np.uint8)
                    if not np.any(mask):
                        raise RecognitionError("template has an empty alpha mask")
                    role.append(RoleTemplate(row["label"], row["image"], image[:, :, :3].copy(), mask.copy()))
                groups.add(row["group"])
                hashes.add(digest)
            except RecognitionError as exc:
                issues.append(f"{kind}[{index}]: {exc}")
    if conflicting_labels:
        raise RecognitionError("reference pack contains identical images with conflicting labels")
    return ReferenceSet(tuple(rarity), tuple(role), tuple(issues), frozenset(groups), frozenset(hashes))


def extract_template(image, config, label, region, *, mask=None):
    """Extract a real colored badge, filling its glyph holes in the alpha mask."""
    from .role import color_masks

    if label not in ROLES:
        raise RecognitionError("template label must be ATTACK, DEFENSE or SUPPORT")
    # Templates always use the reference canvas, independently of inference size.
    from .config import NormalizationConfig
    normalized = normalize_card(image, NormalizationConfig((200, 400), config.normalization.ratio_tolerance))
    if normalized.status != "OK" or normalized.normalized.ndim != 3:
        raise RecognitionError(f"Cannot extract a color template; normalization={normalized.status}")
    from .config import box
    x0, y0, x1, y1 = box(region, "template.box")
    patch = normalized.normalized[y0:y1, x0:x1].copy()
    if mask is not None:
        if (not isinstance(mask, np.ndarray) or mask.dtype != np.uint8 or
                mask.shape != patch.shape[:2] or not np.any(mask)):
            raise RecognitionError("manual alpha mask must be a nonempty uint8 grayscale patch of the same size")
        return np.dstack((patch, mask.copy()))
    colors = color_masks(patch, config.role)[label]
    contours, _ = cv2.findContours(colors, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise RecognitionError("no badge color inside template box")
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < config.role.min_component_area:
        raise RecognitionError("badge color component too small")
    alpha = np.zeros(colors.shape, np.uint8)
    cv2.fillConvexPoly(alpha, cv2.convexHull(contour), 255)
    alpha = cv2.dilate(alpha, np.ones((3, 3), np.uint8))
    return np.dstack((patch, alpha))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract a genuine role badge from a normalized card.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--label", choices=ROLES, required=True)
    parser.add_argument("--box", nargs=4, type=int, required=True, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--output", type=Path, required=True, help="New PNG path; never overwritten")
    parser.add_argument("--mask", type=Path, help="Optional reviewed grayscale alpha mask, matching the extracted patch")
    args = parser.parse_args(argv)
    try:
        if args.output.suffix.lower() != ".png":
            raise RecognitionError("template output must be PNG to preserve its alpha mask")
        template = extract_template(read_image(args.image), load_config(args.config), args.label, args.box,
                                    mask=None if args.mask is None else read_image(args.mask))
        write_image(args.output, template)
    except (RecognitionError, OSError, cv2.error) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Template saved: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
