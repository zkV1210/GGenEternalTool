import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np
import pytest

from gget_scanner.config.layout_loader import load_layout
from gget_scanner.pipeline.quick_scan import main, quick_scan


def test_image_and_json_to_16_cards(tmp_path, layout_data, synthetic_image):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout_data), encoding="utf-8")
    profile = load_layout(path)
    before = synthetic_image.copy()
    snapshot = repr(profile)
    first = quick_scan(synthetic_image, profile)
    second = quick_scan(synthetic_image, profile)
    assert len(first.crops) == 16
    assert first.layout == second.layout
    for index, (a, b) in enumerate(zip(first.crops, second.crops)):
        row, column = divmod(index, 8)
        x, y = 50 + column * 120, 100 + row * 300
        assert a.status == "ok"
        np.testing.assert_array_equal(a.image, before[y:y + 200, x:x + 80])
        np.testing.assert_array_equal(a.image, b.image)
    np.testing.assert_array_equal(first.overlay, second.overlay)
    np.testing.assert_array_equal(synthetic_image, before)
    assert repr(profile) == snapshot


def test_cli_unicode_paths_and_overwrite_protection(tmp_path, layout_data, synthetic_image):
    image_path = tmp_path / "測試圖片.png"
    ok, encoded = cv2.imencode(".png", synthetic_image)
    assert ok
    image_path.write_bytes(encoded.tobytes())
    profile_path = tmp_path / "設定.json"
    profile_path.write_text(json.dumps(layout_data), encoding="utf-8")
    output = tmp_path / "裁切結果"
    args = [str(image_path), str(profile_path), "--output", str(output)]
    # Exercise module entry as well as the in-process CLI's error path.
    completed = subprocess.run([sys.executable, "-m", "gget_scanner.pipeline.quick_scan", *args],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    manifest_bytes = (output / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert len(list(output.glob("card_*.png"))) == 16
    assert [card["index"] for card in manifest["cards"]] == list(range(16))
    assert manifest["cards"][15]["size"] == [80, 200]
    assert (output / "overlay.png").exists()
    crop = cv2.imdecode(np.frombuffer((output / manifest["cards"][15]["file"]).read_bytes(), np.uint8), 1)
    np.testing.assert_array_equal(crop, synthetic_image[400:600, 890:970])
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 1
    assert (output / "manifest.json").read_bytes() == manifest_bytes


def test_cli_invalid_image_writes_nothing(tmp_path, layout_data):
    image_path = tmp_path / "bad.png"
    image_path.write_bytes(b"not an image")
    profile_path = tmp_path / "layout.json"
    profile_path.write_text(json.dumps(layout_data), encoding="utf-8")
    output = tmp_path / "not_created"
    with pytest.raises(SystemExit) as exc:
        main([str(image_path), str(profile_path), "--output", str(output)])
    assert exc.value.code == 1
    assert not output.exists()


def test_repository_sample_profile():
    path = Path(__file__).resolve().parents[1] / "data/profiles/sample_grid.json"
    result = quick_scan(np.zeros((1080, 1920, 3), dtype=np.uint8), load_layout(path))
    assert len(result.crops) == 16
    assert all(crop.status == "ok" for crop in result.crops)
