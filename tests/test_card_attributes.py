import json
from pathlib import Path

import numpy as np
import pytest

from gget_scanner.pipeline.card_attributes import (CardClassifier, classify_files, evaluate,
                                                  load_labels, main)
from gget_scanner.recognition.models import RecognitionError
from gget_scanner.recognition.references import ReferenceSet, write_image
from test_card_classifiers import synthetic_card


def test_batch_corruption_isolated_and_debug_optional(tmp_path):
    good, bad = tmp_path / "card_好.png", tmp_path / "card_bad.png"
    write_image(good, synthetic_card())
    bad.write_bytes(b"not png")
    rows = classify_files([bad, good], CardClassifier())
    assert rows[0]["error"]
    assert rows[1]["normalization"]["status"] == "OK"
    assert not (tmp_path / "debug").exists()
    debug = tmp_path / "debug"
    rows = classify_files([good], CardClassifier(), debug)
    folder = next(debug.iterdir())
    assert (folder / "normalized.png").exists()
    assert (folder / "regions.png").exists()
    assert len(list(folder.glob("border_*.png"))) == 3
    json.loads((folder / "scores.json").read_text(encoding="utf-8"))


def test_metrics_abstentions_and_group_leakage_are_explicit(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"card_{index}.png"
        write_image(path, synthetic_card())
        paths.append(path)
    rows = classify_files(paths, CardClassifier())
    labels = {str(path.resolve()): {"rarity": "SSR", "role": "DEFENSE", "group": str(index), "split": "test"}
              for index, path in enumerate(paths)}
    metrics = evaluate(rows, labels, ReferenceSet(groups=frozenset({"0"})))
    assert metrics["excluded_reference_overlap"] == 1
    assert metrics["evaluated_images"] == 2
    assert metrics["rarity"]["accuracy"] == 0
    assert metrics["rarity"]["unknown_ratio"] == 1
    assert metrics["rarity"]["accepted_accuracy"] is None
    assert metrics["role"]["confusion_matrix"]["DEFENSE"]["UNKNOWN"] == 2
    assert evaluate([], {}, ReferenceSet())["rarity"]["accuracy"] is None


def test_cli_single_and_batch_reports_and_overwrite_protection(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_image(inputs / "card_1.png", synthetic_card())
    write_image(inputs / "overlay.png", synthetic_card())
    (inputs / "card_2.png").write_bytes(b"bad")
    out = tmp_path / "report"
    args = [str(inputs), "--config", "data/profiles/card_attributes.json", "--output", str(out)]
    assert main(args) == 1
    before = (out / "results.json").read_bytes()
    report = json.loads(before)
    assert report["summary"]["total"] == 2
    assert report["summary"]["errors"] == 1
    assert report["metrics"] is None
    assert not (out / "debug").exists()
    with pytest.raises(SystemExit):
        main(args)
    assert (out / "results.json").read_bytes() == before
    single = tmp_path / "single"
    assert main([str(inputs / "card_1.png"), "--config", "data/profiles/card_attributes.json",
                 "--output", str(single), "--debug"]) == 0
    with pytest.raises(SystemExit):
        main([str(inputs), "--config", "data/profiles/card_attributes.json", "--output", str(inputs / "nested")])


def test_label_manifest_validates_paths_and_duplicates(tmp_path):
    path = tmp_path / "labels.json"
    row = {"image": "card.png", "rarity": "SR", "role": None, "group": "same-card", "split": "test"}
    path.write_text(json.dumps({"schema_version": 1, "samples": [row]}), encoding="utf-8")
    labels = load_labels(path)
    assert str((tmp_path / "card.png").resolve()) in labels
    path.write_text(json.dumps({"schema_version": 1, "samples": [row, row]}), encoding="utf-8")
    with pytest.raises(RecognitionError, match="duplicate"):
        load_labels(path)


def test_single_file_can_write_to_a_sibling_subdirectory(tmp_path):
    image = tmp_path / "card.png"
    write_image(image, synthetic_card())
    assert main([str(image), "--config", "data/profiles/card_attributes.json", "--output", str(tmp_path / "out")]) == 0
