"""Compare committed and working-tree detectors over device-organized fixtures."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import types

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "f8cfbe5"
VERSIONS = (f"baseline_{BASELINE}", "geometry_roi")


def _worker(version: str, source: Path, output: Path) -> int:
    if version == VERSIONS[0]:
        # Load the two committed modules in this child process. Git and the
        # working-tree modules remain untouched; dependencies are shared.
        for name, path in (
            ("gget_scanner.image.card_detection", "src/gget_scanner/image/card_detection.py"),
            ("gget_scanner.pipeline.auto_scan", "src/gget_scanner/pipeline/auto_scan.py"),
        ):
            code = subprocess.check_output(["git", "show", f"{BASELINE}:{path}"],
                                           cwd=ROOT, text=True, encoding="utf-8")
            module = types.ModuleType(name)
            module.__package__ = name.rsplit(".", 1)[0]
            sys.modules[name] = module
            exec(compile(code, path, "exec"), module.__dict__)
    from gget_scanner.pipeline.auto_scan import main
    return main([str(source), "--output", str(output)])


def _image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), 1)
    if image is None:
        raise ValueError(f"Cannot decode {path}")
    return image


def _save(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"Cannot encode {path}")
    with path.open("xb") as stream:
        stream.write(encoded.tobytes())


def _check_case(source: Path, output: Path) -> dict:
    from gget_scanner.config.layout_loader import load_layout
    from gget_scanner.image.layout import resolve_layout
    manifest_path = output / "manifest.json"
    if not manifest_path.exists():
        return {"status": "error", "cards": 0, "error": "No manifest; see run.log"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = _image(source)
    size = (image.shape[1], image.shape[0])
    assert tuple(manifest["image_size"]) == size
    layouts = {name: resolve_layout(load_layout(output / name), size)
               for name in manifest["layouts"]}
    cells = []
    for card in manifest["cards"]:
        resolved = layouts[card["layout_file"]].cards[card["layout_index"]]
        assert list(resolved.bounds) == card["bounds"]
        left, top, right, bottom = card["bounds"]
        crop = _image(output / card["file"])
        np.testing.assert_array_equal(crop, image[top:bottom, left:right])
        tile = np.zeros((330, 160, 3), np.uint8)
        tile[25:325, 5:155] = cv2.resize(crop, (150, 300))
        cv2.putText(tile, f"r{card['row']} c{card['column']}", (5, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
        cells.append(tile)
    if cells:
        columns = min(8, len(cells))
        while len(cells) % columns:
            cells.append(np.zeros_like(cells[0]))
        _save(output / "cards_overview.png", np.vstack([
            np.hstack(cells[i:i + columns]) for i in range(0, len(cells), columns)]))
    return {"status": manifest["status"], "cards": len(manifest["cards"]),
            "image_size": size, "rows": sorted({c["row"] for c in manifest["cards"]}),
            "pixel_and_layout_checks": len(manifest["cards"]), "error": manifest["error"]}


def run(fixtures: Path, output: Path) -> list[dict]:
    sources = sorted(p for d in fixtures.iterdir() if d.is_dir()
                     for p in d.glob("*.png"))
    if not sources:
        raise ValueError(f"No device-organized PNG fixtures in {fixtures}")
    targets = [output / p.parent.name / version / p.stem
               for p in sources for version in VERSIONS]
    if any(path.exists() for path in targets):
        raise FileExistsError("Case output already exists; choose a new output root")
    records = []
    for source in sources:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        for version in VERSIONS:
            case = output / source.parent.name / version / source.stem
            started = perf_counter()
            process = subprocess.run(
                [sys.executable, "-m", "scripts.layout_batch", "--worker", version,
                 "--image", str(source), "--case-output", str(case)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            elapsed = perf_counter() - started
            case.mkdir(parents=True, exist_ok=True)
            (case / "run.log").write_text(process.stdout + process.stderr, encoding="utf-8")
            try:
                result = _check_case(source, case)
            except Exception as exc:
                result = {"status": "verification_error", "cards": 0, "error": str(exc)}
            if process.returncode and result["status"] == "ok":
                result["status"] = "error"
            record = {"device": source.parent.name, "version": version, "fixture": source.stem,
                      "source_sha256": digest, "exit_code": process.returncode,
                      "seconds_including_process_and_io": elapsed, **result}
            (case / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            records.append(record)
            print(f"{source.parent.name}/{version}/{source.stem}: "
                  f"{record['status']}, {record['cards']} cards", flush=True)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, source
    (output / "summary.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def report(output: Path, records: list[dict]) -> None:
    index = ["# 裝置與算法比較", "", "卡片數是偵測輸出，不代表人工確認的正確率。",
             "成功輸出已核對原圖像素與重載 Layout；失敗請看對應 run.json／run.log。", ""]
    for device in sorted({r["device"] for r in records}):
        index.append(f"- [{device}]({device}/comparison.md)")
        lines = [f"# {device}", "", "| 測資 | 原版張數 | 幾何版張數 | 狀態 |",
                 "| --- | ---: | ---: | --- |"]
        for name in sorted({r["fixture"] for r in records if r["device"] == device}):
            pair = [next(r for r in records if (r["device"], r["fixture"], r["version"])
                         == (device, name, version)) for version in VERSIONS]
            links = [f"[{r['cards']}]({r['version']}/{name}/"
                     f"{'cards_overview.png' if r['cards'] else 'run.json'})" for r in pair]
            lines.append(f"| {name} | {links[0]} | {links[1]} | "
                         f"{pair[0]['status']} / {pair[1]['status']} |")
        for version in VERSIONS:
            selected = [r for r in records if r["device"] == device and r["version"] == version]
            tiles = []
            for record in selected:
                case = output / device / version / record["fixture"]
                path = case / "overlay.png"
                image = _image(path) if path.exists() else np.zeros((300, 600, 3), np.uint8)
                tile = np.zeros((460, 600, 3), np.uint8)
                height = min(420, round(image.shape[0] * 600 / image.shape[1]))
                tile[35:35 + height] = cv2.resize(image, (600, height))
                cv2.putText(tile, f"{record['fixture']} ({record['cards']})", (6, 24),
                            cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
                tiles.append(tile)
            while len(tiles) % 3:
                tiles.append(np.zeros_like(tiles[0]))
            _save(output / device / version / "overlays.png", np.vstack([
                np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]))
            lines.extend(["", f"[{version} 定位總覽]({version}/overlays.png)"])
        (output / device / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tests/fixtures/private")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--worker", choices=VERSIONS, help=argparse.SUPPRESS)
    parser.add_argument("--image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--case-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return _worker(args.worker, args.image, args.case_output)
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "baseline_commit": subprocess.check_output(
            ["git", "rev-parse", BASELINE], cwd=ROOT, text=True).strip(),
        "working_tree_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "geometry_roi_source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                       for p in ("src/gget_scanner/image/card_detection.py",
                                                 "src/gget_scanner/pipeline/auto_scan.py")},
    }
    records = run(args.fixtures.resolve(), args.output.resolve())
    report(args.output.resolve(), records)
    (args.output / "versions.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return 1 if any(r["status"] in ("error", "verification_error") for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
