"""Recognition settings; ROI coordinates refer to a 200 x 400 canvas."""

from dataclasses import dataclass, field, fields
import json
from math import isfinite
from pathlib import Path

from .models import RARITIES, ROLES, RecognitionError


def number(value, name, low, high):
    if type(value) not in (int, float) or not isfinite(value) or not low <= value <= high:
        raise RecognitionError(f"{name}: expected a finite number in [{low}, {high}]")


def integers(value, name, count, minimum=0):
    if (not isinstance(value, (list, tuple)) or len(value) != count or
            any(type(v) is not int or v < minimum for v in value)):
        raise RecognitionError(f"{name}: expected {count} integers >= {minimum}")
    return tuple(value)


def box(value, name):
    value = integers(value, name, 4)
    x0, y0, x1, y1 = value
    if not (x0 < x1 <= 200 and y0 < y1 <= 400):
        raise RecognitionError(f"{name}: expected a nonempty box inside 200 x 400")
    return value


@dataclass(frozen=True)
class NormalizationConfig:
    size: tuple[int, int] = (200, 400)
    ratio_tolerance: float = 0.05

    def __post_init__(self):
        object.__setattr__(self, "size", integers(self.size, "normalization.size", 2, 1))
        number(self.ratio_tolerance, "ratio_tolerance", 0, 1)


@dataclass(frozen=True)
class RarityConfig:
    classes: tuple[str, ...] = ("SR", "SSR", "UR")
    regions: tuple = ((4, 60, 14, 120), (4, 125, 14, 185), (4, 190, 14, 250))
    bins: tuple[int, int, int] = (8, 8, 8)
    neighbors: int = 3
    min_references: int = 2
    max_distance: float = 0.40
    min_margin: float = 0.08
    max_segment_distance: float = 0.60

    def __post_init__(self):
        if (not isinstance(self.classes, (list, tuple)) or len(self.classes) < 2 or
                any(not isinstance(c, str) or c not in RARITIES for c in self.classes) or
                len(set(self.classes)) != len(self.classes) or
                len(self.classes) > len(RARITIES)):
            raise RecognitionError("rarity.classes: expected distinct supported rarities")
        object.__setattr__(self, "classes", tuple(self.classes))
        if not isinstance(self.regions, (list, tuple)) or len(self.regions) != 3:
            raise RecognitionError("rarity.regions: expected three border sampling boxes")
        object.__setattr__(self, "regions", tuple(box(v, "rarity.region") for v in self.regions))
        bins = integers(self.bins, "rarity.bins", 3, 2)
        if any(v > 32 for v in bins):
            raise RecognitionError("rarity.bins: maximum 32 bins per channel")
        object.__setattr__(self, "bins", bins)
        for key in ("neighbors", "min_references"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise RecognitionError(f"rarity.{key}: expected a positive integer")
        for key in ("max_distance", "min_margin", "max_segment_distance"):
            number(getattr(self, key), f"rarity.{key}", 0, 1)


def default_hsv():
    # OpenCV uint8 Hue uses [0, 179]; red crosses its wraparound.
    return {"ATTACK": ((0, 12), (168, 179)), "DEFENSE": ((90, 130),),
            "SUPPORT": ((18, 38),)}


@dataclass(frozen=True)
class RoleConfig:
    search_region: tuple = (15, 0, 85, 60)
    hue_ranges: dict = field(default_factory=default_hsv)
    min_saturation: int = 65
    min_value: int = 45
    min_component_area: int = 40
    max_component_area: int = 2000
    scales: tuple = (0.9, 1.0, 1.1)
    min_shape_score: float = 0.70
    min_margin: float = 0.06
    min_color_fraction: float = 0.25

    def __post_init__(self):
        object.__setattr__(self, "search_region", box(self.search_region, "role.search_region"))
        if not isinstance(self.hue_ranges, dict) or set(self.hue_ranges) != set(ROLES):
            raise RecognitionError("role.hue_ranges: expected ATTACK, DEFENSE, SUPPORT")
        ranges = {}
        for label, values in self.hue_ranges.items():
            if not isinstance(values, (list, tuple)) or not values:
                raise RecognitionError("role.hue_ranges: expected nonempty hue intervals")
            ranges[label] = tuple(integers(v, "hue interval", 2) for v in values)
            if any(not 0 <= a <= b <= 179 for a, b in ranges[label]):
                raise RecognitionError("hue interval: expected 0 <= low <= high <= 179")
        object.__setattr__(self, "hue_ranges", ranges)
        for key in ("min_saturation", "min_value"):
            if type(getattr(self, key)) is not int or not 0 <= getattr(self, key) <= 255:
                raise RecognitionError(f"role.{key}: expected an integer in [0, 255]")
        for key in ("min_component_area", "max_component_area"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise RecognitionError(f"role.{key}: expected a positive integer")
        if self.min_component_area > self.max_component_area:
            raise RecognitionError("role: minimum area exceeds maximum")
        if not isinstance(self.scales, (list, tuple)) or not self.scales:
            raise RecognitionError("role.scales: expected nonempty scales")
        for value in self.scales:
            number(value, "role.scale", 0.5, 2)
        object.__setattr__(self, "scales", tuple(self.scales))
        for key in ("min_shape_score", "min_margin", "min_color_fraction"):
            number(getattr(self, key), f"role.{key}", 0, 1)


@dataclass(frozen=True)
class RecognitionConfig:
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    rarity: RarityConfig = field(default_factory=RarityConfig)
    role: RoleConfig = field(default_factory=RoleConfig)
    strict_filter_enabled: bool = False

    def __post_init__(self):
        if type(self.strict_filter_enabled) is not bool:
            raise RecognitionError("strict_filter_enabled: expected a boolean")
        for name, cls in (("normalization", NormalizationConfig), ("rarity", RarityConfig),
                          ("role", RoleConfig)):
            if not isinstance(getattr(self, name), cls):
                raise RecognitionError(f"{name}: invalid settings type")
        for region in (*self.rarity.regions, self.role.search_region):
            self.scale_box(region)

    def scale_box(self, region):
        width, height = self.normalization.size
        x0, y0, x1, y1 = region
        scaled = (round(x0 * width / 200), round(y0 * height / 400),
                  round(x1 * width / 200), round(y1 * height / 400))
        if not (0 <= scaled[0] < scaled[2] <= width and 0 <= scaled[1] < scaled[3] <= height):
            raise RecognitionError("ROI becomes empty or out of bounds at the target size")
        return scaled


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RecognitionError(f"JSON: duplicate key {key}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RecognitionError(f"Cannot load JSON {path}: {exc}") from exc


def config_from_dict(data):
    expected = {"schema_version", "normalization", "rarity", "role", "strict_filter_enabled"}
    if not isinstance(data, dict) or set(data) != expected or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise RecognitionError("recognition config: expected schema_version 1 and all settings sections")
    settings = {}
    for name, cls in (("normalization", NormalizationConfig), ("rarity", RarityConfig), ("role", RoleConfig)):
        value = data[name]
        if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
            raise RecognitionError(f"{name}: expected exactly the documented settings")
        settings[name] = cls(**value)
    return RecognitionConfig(**settings, strict_filter_enabled=data["strict_filter_enabled"])


def load_config(path):
    return config_from_dict(read_json(path))
