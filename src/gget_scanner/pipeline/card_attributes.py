"""In-memory card classification and single/batch local evaluation CLI."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from time import perf_counter

import cv2

from gget_scanner.recognition.config import RecognitionConfig, load_config, read_json
from gget_scanner.recognition.models import (CardAttributesResult, ClassificationResult,
                                            NormalizationResult, RARITIES, ROLES, RecognitionError)
from gget_scanner.recognition.normalizer import normalize_card
from gget_scanner.recognition.rarity import RarityClassifier
from gget_scanner.recognition.references import ReferenceSet, load_references, local_path, read_image
from gget_scanner.recognition.role import RoleClassifier


class CardClassifier:
    """Load/precompute once, then reuse for successive CropResult.image arrays."""

    def __init__(self, config=None, references=None):
        self.config = config or RecognitionConfig()
        self.references = references or ReferenceSet()
        self.rarity = RarityClassifier(self.config, self.references.rarity)
        self.role = RoleClassifier(self.config, self.references.role)

    def classify(self, image):
        normalized = normalize_card(image, self.config.normalization)
        if normalized.status != "OK":
            skipped = ClassificationResult(reasons=("normalization_failed",))
            return CardAttributesResult(normalized, skipped, skipped)
        if normalized.normalized.ndim != 3:
            unknown = ClassificationResult(reasons=("color_image_required",))
            return CardAttributesResult(normalized, unknown, unknown)
        rarity = self.rarity.classify(normalized.normalized)
        role = self.role.classify(normalized.normalized)
        if self.references.issues or self.role.issues:
            # A broken reference pack cannot safely exclude catalog candidates.
            rarity = replace(rarity, strict_filter_allowed=False,
                             reasons=rarity.reasons + ("reference_pack_has_issues",))
            role = replace(role, strict_filter_allowed=False,
                           reasons=role.reasons + ("reference_pack_has_issues",))
        return CardAttributesResult(normalized, rarity, role)


def classify_card(card_image, config=None, references=None):
    return CardClassifier(config, references).classify(card_image)


def classify_files(paths, classifier, debug_directory=None):
    from gget_scanner.recognition.debug import write_debug

    rows = []
    for index, path in enumerate(paths):
        path = Path(path)
        start = perf_counter()
        error = None
        digest = None
        try:
            image = read_image(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result = classifier.classify(image)
        except (RecognitionError, OSError, cv2.error) as exc:
            error = str(exc)
            unknown = ClassificationResult(reasons=("image_read_or_processing_failed",))
            result = CardAttributesResult(NormalizationResult(None, None, None, "INVALID_IMAGE", reason=error),
                                          unknown, unknown)
        elapsed_ms = (perf_counter() - start) * 1000
        if debug_directory is not None:
            write_debug(result, classifier.config, Path(debug_directory) / f"{index:04d}_{path.stem}")
        rows.append({"file": str(path.resolve()), "sha256": digest, "elapsed_ms": elapsed_ms,
                     "error": error, **result.to_dict()})
    return rows


def load_labels(path):
    data = read_json(path)
    if (not isinstance(data, dict) or set(data) != {"schema_version", "samples"} or
            type(data["schema_version"]) is not int or data["schema_version"] != 1 or
            not isinstance(data["samples"], list)):
        raise RecognitionError("labels: expected schema_version 1 and samples array")
    root = Path(path).resolve().parent
    labels = {}
    for row in data["samples"]:
        if (not isinstance(row, dict) or set(row) != {"image", "rarity", "role", "group", "split"} or
                row["rarity"] not in (*RARITIES, None) or row["role"] not in (*ROLES, None) or
                not isinstance(row["group"], str) or not row["group"] or
                row["split"] not in ("reference", "calibration", "test")):
            raise RecognitionError("label: expected image, rarity, role, group and reference/calibration/test split")
        image_path = str(local_path(root, row["image"]))
        if image_path in labels:
            raise RecognitionError("duplicate labeled image")
        labels[image_path] = row
    return labels


def evaluate(rows, labels, references, split="test"):
    selected = []
    excluded = 0
    for row in rows:
        label = labels.get(row["file"])
        if label is None or label["split"] != split:
            continue
        if label["group"] in references.groups or row["sha256"] in references.image_hashes:
            excluded += 1
            continue
        selected.append((row, label))
    metrics = {"split": split, "evaluated_images": len(selected), "excluded_reference_overlap": excluded}
    for kind, classes in (("rarity", RARITIES), ("role", ROLES)):
        pairs = [(row[kind], label[kind]) for row, label in selected if label[kind] is not None]
        matrix = {actual: {prediction: 0 for prediction in (*classes, "UNKNOWN")} for actual in classes}
        correct = accepted = accepted_correct = unknown = ambiguous = 0
        for prediction, actual in pairs:
            matrix[actual][prediction["value"]] += 1
            is_correct = prediction["value"] == actual
            correct += is_correct
            accepted += prediction["status"] == "ACCEPTED"
            accepted_correct += prediction["status"] == "ACCEPTED" and is_correct
            unknown += prediction["value"] == "UNKNOWN"
            ambiguous += prediction["status"] == "AMBIGUOUS"
        total = len(pairs)
        metrics[kind] = {"labeled_count": total, "accuracy": correct / total if total else None,
                         "accepted_accuracy": accepted_correct / accepted if accepted else None,
                         "accepted_count": accepted, "unknown_ratio": unknown / total if total else None,
                         "ambiguous_ratio": ambiguous / total if total else None, "confusion_matrix": matrix}
    metrics["mean_elapsed_ms"] = (sum(row["elapsed_ms"] for row, _ in selected) / len(selected)
                                   if selected else None)
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description="Classify cropped card UI attributes locally.")
    parser.add_argument("input", type=Path, help="Single image or directory")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--references", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--split", choices=("calibration", "test"), default="test")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        references = load_references(args.references, config) if args.references else ReferenceSet()
        classifier = CardClassifier(config, references)
        labels = load_labels(args.labels) if args.labels else None
        if args.input.is_file():
            paths = [args.input]
        elif args.input.is_dir():
            pattern = "**/card_*" if args.recursive else "card_*"
            paths = sorted(path for path in args.input.glob(pattern) if path.is_file() and
                           path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"))
        else:
            raise RecognitionError(f"Input not found: {args.input}")
        if not paths:
            raise RecognitionError("No card_* images found")
        if args.input.is_dir() and args.output.resolve().is_relative_to(args.input.resolve()):
            raise RecognitionError("output must be outside the input directory to avoid recursive reprocessing")
        args.output.mkdir(parents=True, exist_ok=False)
        rows = classify_files(paths, classifier, args.output / "debug" if args.debug else None)
        errors = sum(row["error"] is not None or row["normalization"]["status"] != "OK" for row in rows)
        report = {"schema_version": 1, "reference_issues": [*references.issues, *classifier.role.issues],
                  "summary": {"total": len(rows), "errors": errors,
                              "mean_elapsed_ms": sum(row["elapsed_ms"] for row in rows) / len(rows)},
                  "results": rows, "metrics": None if labels is None else evaluate(rows, labels, references, args.split)}
        with (args.output / "results.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        for row in rows:
            print(f"{Path(row['file']).name}: normalization={row['normalization']['status']} "
                  f"rarity={row['rarity']['value']}({row['rarity']['status']}) "
                  f"role={row['role']['value']}({row['role']['status']}) {row['elapsed_ms']:.2f} ms")
        print(f"Processed {len(rows)} cards; errors={errors}; report={args.output / 'results.json'}")
        if references.issues or classifier.role.issues:
            print(f"Reference warnings: {len(references.issues) + len(classifier.role.issues)} (see report)")
        return 1 if errors or references.issues or classifier.role.issues else 0
    except (RecognitionError, OSError, cv2.error) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
