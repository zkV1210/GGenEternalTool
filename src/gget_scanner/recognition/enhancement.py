"""Reference-based top-right badge proof of concept, separate from rarity."""

from dataclasses import dataclass, fields
from pathlib import Path

import cv2
import numpy as np

from .config import NormalizationConfig, box, number, read_json
from .models import Candidate, ClassificationResult, RecognitionError
from .normalizer import normalize_card
from .references import local_path, read_image


@dataclass(frozen=True)
class EnhancementConfig:
    size: tuple = (200, 400)
    ratio_tolerance: float = 0.05
    classes: tuple = ("SP", "NONE")
    search_region: tuple = (140, 0, 200, 65)
    reference_region: tuple = (150, 2, 200, 55)
    scales: tuple = (0.95, 1.0, 1.05)
    max_distance: float = 0.15
    none_max_distance: float = 0.10
    min_margin: float = 0.04
    min_references: int = 2

    def __post_init__(self):
        normal = NormalizationConfig(self.size, self.ratio_tolerance)
        object.__setattr__(self, "size", normal.size)
        if (not isinstance(self.classes, (list, tuple)) or len(self.classes) < 2 or
                any(c not in ("SP", "SSP", "NONE") for c in self.classes) or
                len(set(self.classes)) != len(self.classes) or "NONE" not in self.classes):
            raise RecognitionError("enhancement.classes: expected distinct SP/SSP/NONE classes including NONE")
        object.__setattr__(self, "classes", tuple(self.classes))
        for key in ("search_region", "reference_region"):
            object.__setattr__(self, key, box(getattr(self, key), key))
            self.scale_box(getattr(self, key))
        sx,sy,ex,ey = self.search_region
        x0,y0,x1,y1 = self.reference_region
        if not (sx <= x0 < x1 <= ex and sy <= y0 < y1 <= ey):
            raise RecognitionError("reference_region must be inside search_region")
        if not isinstance(self.scales, (list, tuple)) or not self.scales:
            raise RecognitionError("scales: expected a nonempty list")
        for value in self.scales:
            number(value, "scale", 0.5, 2)
        object.__setattr__(self, "scales", tuple(self.scales))
        for key in ("max_distance", "none_max_distance", "min_margin"):
            number(getattr(self, key), key, 0, 1)
        if type(self.min_references) is not int or self.min_references < 1:
            raise RecognitionError("min_references must be a positive integer")

    @property
    def normalization(self):
        return NormalizationConfig(self.size, self.ratio_tolerance)

    def scale_box(self, region):
        result = tuple(round(value * self.size[i % 2] / (200 if i % 2 == 0 else 400))
                       for i,value in enumerate(region))
        if result[0] >= result[2] or result[1] >= result[3]:
            raise RecognitionError("enhancement ROI becomes empty at target size")
        return result


def load_enhancement_config(path):
    data = read_json(path)
    if (not isinstance(data, dict) or set(data) != {"schema_version", *[f.name for f in fields(EnhancementConfig)]}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise RecognitionError("enhancement config: expected schema 1 and documented settings")
    return EnhancementConfig(**{key:value for key,value in data.items() if key != "schema_version"})


@dataclass(frozen=True)
class EnhancementReference:
    label: str
    path: str
    group: str
    patch: np.ndarray


def load_enhancement_references(path, config):
    data = read_json(path)
    if (not isinstance(data, dict) or set(data) != {"schema_version", "samples"} or
            type(data["schema_version"]) is not int or data["schema_version"] != 1 or
            not isinstance(data["samples"], list)):
        raise RecognitionError("enhancement references: expected schema 1 and samples array")
    root = Path(path).resolve().parent
    references, seen = [], {}
    for row in data["samples"]:
        if (not isinstance(row, dict) or set(row) != {"image", "label", "group"} or
                row["label"] not in config.classes or not isinstance(row["group"], str) or not row["group"]):
            raise RecognitionError("enhancement sample: expected image, configured label and group")
        image_path = local_path(root, row["image"])
        normal = normalize_card(read_image(image_path), config.normalization)
        if normal.status != "OK" or normal.normalized.ndim != 3:
            raise RecognitionError(f"unusable enhancement reference {row['image']}: {normal.status}")
        previous = seen.get(image_path)
        if previous is not None:
            raise RecognitionError("duplicate or conflicting enhancement reference")
        seen[image_path] = row["label"]
        x0,y0,x1,y1 = config.scale_box(config.reference_region)
        references.append(EnhancementReference(row["label"], row["image"], row["group"],
                                               normal.normalized[y0:y1,x0:x1].copy()))
    return tuple(references)


class EnhancementClassifier:
    def __init__(self, config=None, references=()):
        self.config = config or EnhancementConfig()
        self.references = references
        self.templates = []
        for reference in references:
            for scale in self.config.scales:
                height,width = reference.patch.shape[:2]
                size = (max(1,round(width*scale)),max(1,round(height*scale)))
                patch = cv2.resize(reference.patch, size, interpolation=cv2.INTER_AREA if scale <= 1 else cv2.INTER_LINEAR)
                self.templates.append((reference,scale,patch))

    def classify_card(self, image):
        normal = normalize_card(image, self.config.normalization)
        if normal.status != "OK":
            return normal, ClassificationResult(reasons=("normalization_failed",))
        if normal.normalized.ndim != 3:
            return normal, ClassificationResult(reasons=("color_image_required",))
        return normal, self.classify(normal.normalized)

    def classify(self, normalized):
        x0,y0,x1,y1 = self.config.scale_box(self.config.search_region)
        search = normalized[y0:y1,x0:x1]
        matches = {}
        for reference,scale,patch in self.templates:
            height,width = patch.shape[:2]
            if height > search.shape[0] or width > search.shape[1] or not np.any(patch):
                continue
            scores = cv2.matchTemplate(search, patch, cv2.TM_SQDIFF_NORMED)
            scores[~np.isfinite(scores)] = np.inf
            score,_,position,_ = cv2.minMaxLoc(scores)
            if not np.isfinite(score):
                continue
            x,y = position
            candidate = Candidate(reference.label,float(score),{"reference_file":reference.path,"scale":scale,
                                  "bbox":[x0+x,y0+y,x0+x+width,y0+y+height]})
            if reference.label not in matches or score < matches[reference.label].raw_score:
                matches[reference.label] = candidate
        candidates = tuple(sorted(matches.values(),key=lambda c:(c.raw_score,c.label)))
        if not candidates:
            return ClassificationResult(reasons=("missing_valid_enhancement_references",))
        best = candidates[0]
        reasons = []
        counts = {label:sum(r.label == label for r in self.references) for label in self.config.classes}
        if any(count < self.config.min_references for count in counts.values()) or set(matches) != set(self.config.classes):
            reasons.append("insufficient_enhancement_coverage")
        limit = self.config.none_max_distance if best.label == "NONE" else self.config.max_distance
        if best.raw_score > limit:
            reasons.append("enhancement_distance_too_large")
        if len(candidates) > 1 and candidates[1].raw_score-best.raw_score < self.config.min_margin:
            reasons.append("enhancement_margin_too_small")
        status = "ACCEPTED" if not reasons else "UNKNOWN" if any(r in reasons for r in
                 ("insufficient_enhancement_coverage","enhancement_distance_too_large")) else "AMBIGUOUS"
        return ClassificationResult(best.label if status == "ACCEPTED" else "UNKNOWN",status,
                                    "color_sqdiff_normed",True,candidates,tuple(reasons),False,
                                    tuple(best.details["bbox"]))
