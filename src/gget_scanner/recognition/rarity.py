"""Three-band Lab histograms of the thick left frame, never the artwork."""

import cv2
import numpy as np

from .config import RecognitionConfig
from .models import Candidate, ClassificationResult


def border_features(image: np.ndarray, config: RecognitionConfig) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    features = []
    for region in config.rarity.regions:
        x0, y0, x1, y1 = config.scale_box(region)
        histogram = cv2.calcHist([lab[y0:y1, x0:x1]], [0, 1, 2], None,
                                list(config.rarity.bins), [0, 256] * 3).ravel()
        features.append(histogram / histogram.sum())
    return np.asarray(features, dtype=np.float32)


class RarityClassifier:
    def __init__(self, config, references):
        self.config = config
        self.references = references

    def classify(self, image) -> ClassificationResult:
        settings = self.config.rarity
        if not self.references:
            return ClassificationResult(reasons=("missing_rarity_references",))
        features = border_features(image, self.config)
        candidates = []
        counts = {}
        for label in settings.classes:
            distances = []
            for reference in self.references:
                if reference.label != label:
                    continue
                # Hellinger distance between L1-normalized joint histograms.
                bands = np.sqrt(np.maximum(0, 1 - np.sqrt(features * reference.features).sum(axis=1)))
                distances.append((float(bands.mean()), bands, reference.path))
            counts[label] = len(distances)
            if not distances:
                continue
            nearest = sorted(distances, key=lambda row: row[0])[:settings.neighbors]
            segment_distances = np.mean([row[1] for row in nearest], axis=0)
            candidates.append(Candidate(label, float(np.mean([row[0] for row in nearest])),
                              {"segment_distances": segment_distances.tolist(),
                               "neighbors": len(nearest), "available_references": len(distances),
                               "reference_files": [row[2] for row in nearest]}))
        candidates.sort(key=lambda item: (item.raw_score, item.label))
        if not candidates:
            return ClassificationResult(reasons=("missing_active_rarity_references",))
        best = candidates[0]
        reasons = []
        if any(counts[label] < settings.min_references for label in settings.classes):
            reasons.append("insufficient_class_coverage")
        if best.raw_score > settings.max_distance:
            reasons.append("border_distance_too_large")
        if max(best.details["segment_distances"]) > settings.max_segment_distance:
            reasons.append("border_segment_mismatch")
        if len(candidates) > 1 and candidates[1].raw_score - best.raw_score < settings.min_margin:
            reasons.append("rarity_margin_too_small")
        if len(candidates) > 1:
            band_winners = [min(candidates, key=lambda c: c.details["segment_distances"][i]).label
                            for i in range(3)]
            if len(set(band_winners)) > 1:
                reasons.append("border_segments_disagree")
        status = ("ACCEPTED" if not reasons else "UNKNOWN" if
                  "border_distance_too_large" in reasons or "insufficient_class_coverage" in reasons
                  else "AMBIGUOUS")
        return ClassificationResult(best.label if status == "ACCEPTED" else "UNKNOWN", status,
                                    "hellinger_distance", True, tuple(candidates), tuple(reasons),
                                    status == "ACCEPTED" and self.config.strict_filter_enabled)
