"""Image-bearing Python results and explicitly non-probabilistic JSON results."""

from dataclasses import dataclass, field

import numpy as np


class RecognitionError(ValueError):
    """Invalid recognition configuration, reference data or image file."""


RARITIES = ("N", "R", "SR", "SSR", "UR")
ROLES = ("ATTACK", "DEFENSE", "SUPPORT")


@dataclass(frozen=True)
class NormalizationResult:
    original: np.ndarray | None
    normalized: np.ndarray | None
    original_size: tuple[int, int] | None
    status: str
    relative_ratio_error: float | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"original_size": self.original_size,
                "normalized_size": None if self.normalized is None else
                (self.normalized.shape[1], self.normalized.shape[0]),
                "status": self.status, "relative_ratio_error": self.relative_ratio_error,
                "reason": self.reason}


@dataclass(frozen=True)
class Candidate:
    label: str
    raw_score: float
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"value": self.label, "raw_score": self.raw_score, **self.details}


@dataclass(frozen=True)
class ClassificationResult:
    value: str = "UNKNOWN"
    status: str = "UNKNOWN"
    score_type: str | None = None
    lower_is_better: bool | None = None
    candidates: tuple[Candidate, ...] = ()
    reasons: tuple[str, ...] = ()
    strict_filter_allowed: bool = False
    bbox: tuple[int, int, int, int] | None = None

    def to_dict(self) -> dict:
        best = self.candidates[0] if self.candidates else None
        return {"value": self.value, "status": self.status,
                "best_candidate": None if best is None else best.label,
                "raw_score": None if best is None else best.raw_score,
                "score_type": self.score_type, "lower_is_better": self.lower_is_better,
                "best_details": None if best is None else best.details,
                "alternatives": [c.to_dict() for c in self.candidates[1:]],
                "reasons": self.reasons, "strict_filter_allowed": self.strict_filter_allowed,
                "bbox": self.bbox}


@dataclass(frozen=True)
class CardAttributesResult:
    normalization: NormalizationResult
    rarity: ClassificationResult
    role: ClassificationResult

    def to_dict(self) -> dict:
        return {"normalization": self.normalization.to_dict(),
                "rarity": self.rarity.to_dict(), "role": self.role.to_dict()}
