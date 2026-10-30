from dataclasses import replace

import cv2
import numpy as np
import pytest

from gget_scanner.pipeline.card_attributes import CardClassifier
from gget_scanner.recognition.config import RecognitionConfig
from gget_scanner.recognition.models import ROLES
from gget_scanner.recognition.rarity import border_features
from gget_scanner.recognition.references import RarityReference, ReferenceSet, RoleTemplate
from gget_scanner.recognition.role import RoleClassifier


COLORS = {"SR": (180, 70, 20), "SSR": (20, 150, 220), "UR": (190, 50, 180)}
ROLE_COLORS = {"ATTACK": (20, 20, 200), "DEFENSE": (200, 90, 20), "SUPPORT": (20, 190, 220)}


def synthetic_badge(label):
    image = np.zeros((34, 34, 3), np.uint8)
    mask = np.zeros((34, 34), np.uint8)
    polygon = np.array([[9, 1], [24, 1], [32, 9], [32, 24], [24, 32], [9, 32], [1, 24], [1, 9]], np.int32)
    cv2.fillConvexPoly(mask, polygon, 255)
    image[mask > 0] = ROLE_COLORS[label]
    if label == "ATTACK":
        cv2.line(image, (8, 25), (25, 8), (255, 255, 255), 4)
        cv2.line(image, (8, 17), (17, 26), (255, 255, 255), 3)
    elif label == "DEFENSE":
        cv2.polylines(image, [np.array([[9, 8], [25, 8], [25, 21], [17, 27], [9, 21]])], True,
                      (255, 255, 255), 3)
    else:
        cv2.rectangle(image, (12, 6), (21, 27), (255, 255, 255), -1)
        cv2.line(image, (10, 23), (23, 23), (20, 20, 20), 2)
    return image, mask


def synthetic_card(rarity="SSR", role="DEFENSE", position=(30, 5), scale=1.0):
    image = np.full((400, 200, 3), 25, np.uint8)
    image[50:270, 3:16] = COLORS[rarity]
    badge, mask = synthetic_badge(role)
    if scale != 1:
        size = round(34 * scale)
        badge = cv2.resize(badge, (size, size))
        mask = cv2.resize(mask, (size, size), interpolation=cv2.INTER_NEAREST)
    x, y = position
    patch = image[y:y + badge.shape[0], x:x + badge.shape[1]]
    patch[mask > 0] = badge[mask > 0]
    return image


@pytest.fixture
def reference_set():
    config = RecognitionConfig()
    rarity = tuple(RarityReference(label, f"{label}_{i}.png", border_features(synthetic_card(label), config))
                   for label in config.rarity.classes for i in range(3))
    role = tuple(RoleTemplate(label, label, *synthetic_badge(label)) for label in ROLES)
    return ReferenceSet(rarity, role)


@pytest.mark.parametrize("rarity", ["SR", "SSR", "UR"])
@pytest.mark.parametrize("role", ROLES)
def test_known_attributes_and_raw_scores(rarity, role, reference_set):
    image = synthetic_card(rarity, role)
    result = CardClassifier(references=reference_set).classify(image)
    assert result.rarity.value == rarity
    assert result.role.value == role
    assert result.rarity.candidates[0].raw_score == pytest.approx(0, abs=0.001)
    assert result.role.candidates[0].raw_score > 0.95
    assert result.rarity.strict_filter_allowed is False
    assert result.role.strict_filter_allowed is False


@pytest.mark.parametrize("label", ROLES)
@pytest.mark.parametrize("scale,position", [(0.9, (40, 10)), (1.1, (23, 2))])
def test_badge_shift_and_scale(label, scale, position, reference_set):
    result = CardClassifier(references=reference_set).classify(synthetic_card(role=label, position=position, scale=scale))
    assert result.role.value == label
    assert result.role.bbox is not None


def test_blank_missing_and_grayscale_are_unknown(reference_set):
    classifier = CardClassifier(references=reference_set)
    result = classifier.classify(np.zeros((400, 200, 3), np.uint8))
    assert result.rarity.value == result.role.value == "UNKNOWN"
    assert result.role.status == "UNKNOWN"
    result = CardClassifier().classify(synthetic_card())
    assert result.rarity.value == result.role.value == "UNKNOWN"
    result = classifier.classify(np.zeros((400, 200), np.uint8))
    assert result.role.reasons == ("color_image_required",)


def test_artwork_colors_cannot_change_rarity(reference_set):
    image = synthetic_card("SR")
    first = CardClassifier(references=reference_set).classify(image)
    image[70:250, 30:] = COLORS["UR"]
    second = CardClassifier(references=reference_set).classify(image)
    assert first.rarity == second.rarity


def test_inconsistent_border_and_identical_classes_abstain(reference_set):
    image = synthetic_card("SR")
    image[125:185, 4:14] = COLORS["SSR"]
    result = CardClassifier(references=reference_set).classify(image)
    assert result.rarity.value == "UNKNOWN"
    assert "border_segments_disagree" in result.rarity.reasons
    duplicates = tuple(replace(ref, features=reference_set.rarity[0].features) for ref in reference_set.rarity)
    result = CardClassifier(references=replace(reference_set, rarity=duplicates)).classify(synthetic_card("SR"))
    assert result.rarity.status == "AMBIGUOUS"
    assert "rarity_margin_too_small" in result.rarity.reasons


def test_incomplete_class_coverage_and_invalid_template(reference_set):
    refs = replace(reference_set, rarity=reference_set.rarity[:3], role=reference_set.role[:1])
    result = CardClassifier(references=refs).classify(synthetic_card("SR", "ATTACK"))
    assert result.rarity.status == result.role.status == "UNKNOWN"
    assert not result.role.strict_filter_allowed
    invalid = RoleTemplate("ATTACK", "blank", np.zeros((30, 30, 3), np.uint8), np.full((30, 30), 255, np.uint8))
    classifier = RoleClassifier(RecognitionConfig(), [invalid])
    assert classifier.classify(synthetic_card()).status == "UNKNOWN"


def test_role_requires_color_and_shape_agreement(reference_set):
    image = synthetic_card(role="DEFENSE")
    patch = image[5:39, 30:64]
    image[5:39, 30:64][np.all(patch == ROLE_COLORS["DEFENSE"], axis=2)] = ROLE_COLORS["ATTACK"]
    result = CardClassifier(references=reference_set).classify(image)
    assert result.role.value == "UNKNOWN"
    assert any(reason in result.role.reasons for reason in ("color_shape_disagree", "role_margin_too_small"))


def test_target_size_changes_keep_templates_and_roi_consistent(reference_set):
    config = RecognitionConfig()
    config = replace(config, normalization=replace(config.normalization, size=(100, 200)))
    # Recompute frame features at the configured canvas, as the real loader does.
    from gget_scanner.recognition.normalizer import normalize_card
    refs = tuple(RarityReference(label, f"{label}{i}", border_features(
        normalize_card(synthetic_card(label), config.normalization).normalized, config))
        for label in config.rarity.classes for i in range(3))
    classifier = CardClassifier(config, replace(reference_set, rarity=refs))
    result = classifier.classify(synthetic_card())
    assert result.normalization.normalized.shape == (200, 100, 3)
    assert result.rarity.value == "SSR"
    assert result.role.value == "DEFENSE"


@pytest.mark.parametrize("label", ROLES)
def test_badge_color_connected_to_same_color_background(label, reference_set):
    image = synthetic_card(role=label)
    badge = image[5:39, 30:64].copy()
    image[:60, 15:85] = ROLE_COLORS[label]
    _, mask = synthetic_badge(label)
    image[5:39, 30:64][mask > 0] = badge[mask > 0]
    result = CardClassifier(references=reference_set).classify(image)
    assert result.role.value == label, result.role.to_dict()


def test_strict_filter_is_explicit_and_requires_a_usable_reference_pack(reference_set):
    config = replace(RecognitionConfig(), strict_filter_enabled=True)
    result = CardClassifier(config, reference_set).classify(synthetic_card())
    assert result.rarity.strict_filter_allowed and result.role.strict_filter_allowed
    result = CardClassifier(config, replace(reference_set, issues=("broken sample",))).classify(synthetic_card())
    assert not result.rarity.strict_filter_allowed and not result.role.strict_filter_allowed


def test_five_rarities_can_be_added_without_core_changes():
    config = RecognitionConfig()
    config = replace(config, rarity=replace(config.rarity, classes=("N", "R", "SR", "SSR", "UR")))
    colors = {"N": (50, 50, 50), "R": (40, 120, 30), **COLORS}
    refs = []
    for label, color in colors.items():
        image = synthetic_card()
        image[50:270, 3:16] = color
        for index in range(2):
            refs.append(RarityReference(label, f"{label}{index}", border_features(image, config)))
    image = synthetic_card()
    image[50:270, 3:16] = colors["N"]
    result = CardClassifier(config, ReferenceSet(rarity=tuple(refs))).classify(image)
    assert result.rarity.value == "N"
    assert result.role.value == "UNKNOWN"
