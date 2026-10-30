"""HSV badge proposals and masked gradient template verification."""

from dataclasses import dataclass

import cv2
import numpy as np

from .models import Candidate, ClassificationResult, ROLES


def color_masks(image, settings):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    colored = (hsv[:, :, 1] >= settings.min_saturation) & (hsv[:, :, 2] >= settings.min_value)
    return {label: (colored & np.logical_or.reduce([(hsv[:, :, 0] >= low) &
                    (hsv[:, :, 0] <= high) for low, high in ranges])).astype(np.uint8)
            for label, ranges in settings.hue_ranges.items()}


def gradient(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    return cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3),
                         cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))


def badge_components(masks, config):
    area_scale = config.normalization.size[0] * config.normalization.size[1] / (200 * 400)
    proposals = []
    for label, mask in masks.items():
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for x, y, width, height, area in stats[1:]:
            if (config.role.min_component_area * area_scale <= area <= config.role.max_component_area * area_scale
                    and 0.4 <= width / height <= 2.0):
                proposals.append((label, int(x), int(y), int(x + width), int(y + height)))
    return proposals


@dataclass(frozen=True)
class PreparedTemplate:
    label: str
    path: str
    scale: float
    shape: np.ndarray
    mask: np.ndarray


class RoleClassifier:
    def __init__(self, config, templates):
        self.config = config
        self.templates = []
        self.issues = []
        target_width, target_height = config.normalization.size
        sx, sy = target_width / 200, target_height / 400
        for template in templates:
            for scale in config.role.scales:
                width = max(1, round(template.image.shape[1] * sx * scale))
                height = max(1, round(template.image.shape[0] * sy * scale))
                interpolation = cv2.INTER_AREA if sx * scale <= 1 and sy * scale <= 1 else cv2.INTER_LINEAR
                image = cv2.resize(template.image, (width, height), interpolation=interpolation)
                mask = cv2.resize(template.mask, (width, height), interpolation=cv2.INTER_NEAREST)
                # Keep gradient computation at crop edges out of the comparison.
                mask = cv2.erode((mask > 0).astype(np.uint8), np.ones((3, 3), np.uint8),
                                 borderType=cv2.BORDER_CONSTANT, borderValue=0)
                shape = gradient(image)
                if not np.any(mask) or float(np.sum(shape * shape * mask)) < 1e-6:
                    self.issues.append(f"invalid_template_energy:{template.path}")
                    continue
                self.templates.append(PreparedTemplate(template.label, template.path, scale, shape, mask))

    def classify(self, image):
        if not self.templates:
            return ClassificationResult(reasons=("missing_valid_role_templates", *self.issues))
        x0, y0, x1, y1 = self.config.scale_box(self.config.role.search_region)
        search = image[y0:y1, x0:x1]
        shape = gradient(search)
        masks = color_masks(search, self.config.role)
        proposals = badge_components(masks, self.config)
        matches = {}
        for template in self.templates:
            height, width = template.shape.shape
            if height > shape.shape[0] or width > shape.shape[1]:
                continue
            scores = cv2.matchTemplate(shape, template.shape, cv2.TM_CCORR_NORMED, mask=template.mask)
            scores[~np.isfinite(scores)] = -1
            _, score, _, position = cv2.minMaxLoc(scores)
            if score < 0:
                continue
            x, y = position
            active = template.mask > 0
            fractions = {label: float(mask[y:y + height, x:x + width][active].mean())
                         for label, mask in masks.items()}
            proposed = any(label == template.label and x <= (px0 + px1) / 2 < x + width and
                            y <= (py0 + py1) / 2 < y + height
                            for label, px0, py0, px1, py1 in proposals)
            # Background of the same hue can merge with a genuine badge. After
            # template localization, verify the component inside its mask again.
            local_mask = masks[template.label][y:y + height, x:x + width] * active.astype(np.uint8)
            supported = bool(badge_components({template.label: local_mask}, self.config))
            candidate = Candidate(template.label, float(np.clip(score, 0, 1)),
                                  {"color_fractions": fractions, "color_proposal": supported,
                                   "global_color_proposal": proposed,
                                   "template_file": template.path, "scale": template.scale,
                                   "bbox": [x0 + x, y0 + y, x0 + x + width, y0 + y + height]})
            previous = matches.get(template.label)
            if previous is None or candidate.raw_score > previous.raw_score:
                matches[template.label] = candidate
        candidates = tuple(sorted(matches.values(), key=lambda c: (-c.raw_score, c.label)))
        if not candidates:
            return ClassificationResult(reasons=("no_usable_template_match",))
        best = candidates[0]
        reasons = []
        if set(matches) != set(ROLES):
            reasons.append("insufficient_role_coverage")
        if best.raw_score < self.config.role.min_shape_score:
            reasons.append("shape_score_too_low")
        if len(candidates) > 1 and best.raw_score - candidates[1].raw_score < self.config.role.min_margin:
            reasons.append("role_margin_too_small")
        fractions = best.details["color_fractions"]
        if fractions[best.label] < self.config.role.min_color_fraction:
            reasons.append("insufficient_badge_color")
        if max(fractions, key=fractions.get) != best.label:
            reasons.append("color_shape_disagree")
        if not best.details["color_proposal"]:
            reasons.append("no_matching_color_component")
        status = ("ACCEPTED" if not reasons else "UNKNOWN" if any(reason in reasons for reason in
                  ("shape_score_too_low", "insufficient_badge_color", "insufficient_role_coverage"))
                  else "AMBIGUOUS")
        return ClassificationResult(best.label if status == "ACCEPTED" else "UNKNOWN", status,
                                    "masked_gradient_ccorr_normed", False, candidates, tuple(reasons),
                                    status == "ACCEPTED" and self.config.strict_filter_enabled,
                                    tuple(best.details["bbox"]))
