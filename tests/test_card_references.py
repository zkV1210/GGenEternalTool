import json

import numpy as np
import pytest

from gget_scanner.recognition.config import RecognitionConfig
from gget_scanner.recognition.models import RecognitionError
from gget_scanner.recognition.references import (extract_template, load_references,
                                               main, read_image, write_image)
from test_card_classifiers import synthetic_card


def test_reference_loading_extraction_and_bad_entries(tmp_path):
    config = RecognitionConfig()
    image = synthetic_card("SSR", "ATTACK")
    write_image(tmp_path / "card.png", image)
    template = extract_template(image, config, "ATTACK", (29, 4, 65, 40))
    assert template.shape == (36, 36, 4)
    assert np.any(template[:, :, 3] == 0) and np.any(template[:, :, 3] == 255)
    write_image(tmp_path / "badge.png", template)
    manifest = {"schema_version": 1,
                "rarity_samples": [{"image": "card.png", "label": "SSR", "group": "one"}],
                "role_templates": [{"image": "badge.png", "label": "ATTACK", "group": "one"},
                                   {"image": "../escape.png", "label": "DEFENSE", "group": "two"}]}
    path = tmp_path / "refs.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    refs = load_references(path, config)
    assert len(refs.rarity) == len(refs.role) == 1
    assert len(refs.issues) == 1 and "escapes" in refs.issues[0]
    assert refs.groups == frozenset({"one"})
    assert len(refs.image_hashes) == 2
    with pytest.raises(FileExistsError):
        write_image(tmp_path / "card.png", image)


def test_bad_images_and_reference_manifest(tmp_path):
    bad = tmp_path / "bad.png"
    for data in (b"", b"not png"):
        bad.write_bytes(data)
        with pytest.raises(RecognitionError):
            read_image(bad)
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RecognitionError):
        load_references(path, RecognitionConfig())


def test_extract_cli_preserves_source_and_never_overwrites(tmp_path):
    source = tmp_path / "來源.png"
    write_image(source, synthetic_card(role="ATTACK"))
    before = source.read_bytes()
    output = tmp_path / "template.png"
    args = [str(source), "--config", "data/profiles/card_attributes.json", "--label", "ATTACK",
            "--box", "29", "4", "65", "40", "--output", str(output)]
    assert main(args) == 0
    assert read_image(output).shape[2] == 4
    with pytest.raises(SystemExit):
        main(args)
    assert source.read_bytes() == before


def test_manual_alpha_mask_excludes_same_hue_background():
    image = synthetic_card(role="SUPPORT")
    mask = np.zeros((40, 40), np.uint8)
    mask[5:35, 5:35] = 255
    template = extract_template(image, RecognitionConfig(), "SUPPORT", (27, 2, 67, 42), mask=mask)
    np.testing.assert_array_equal(template[:, :, 3], mask)
    with pytest.raises(RecognitionError):
        extract_template(image, RecognitionConfig(), "SUPPORT", (27, 2, 67, 42), mask=mask[:10])


def test_conflicting_labels_for_identical_reference_are_rejected(tmp_path):
    write_image(tmp_path / "card.png", synthetic_card())
    path = tmp_path / "refs.json"
    data = {"schema_version": 1, "role_templates": [], "rarity_samples": [
        {"image": "card.png", "label": label, "group": label} for label in ("SR", "SSR")]}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RecognitionError, match="conflicting"):
        load_references(path, RecognitionConfig())
