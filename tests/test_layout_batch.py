import json

import cv2
import pytest

from scripts.layout_batch import VERSIONS, report, run
from test_card_detection import make_screen


def test_both_versions_use_device_directories_and_preserve_inputs(tmp_path):
    fixtures = tmp_path / 'private'
    device = fixtures / 'synthetic_device'
    device.mkdir(parents=True)
    source = device / 'Test_grid.png'
    original = cv2.imencode('.png', make_screen()[0])[1].tobytes()
    source.write_bytes(original)
    output = tmp_path / 'outputs'
    records = run(fixtures, output)
    report(output, records)
    assert source.read_bytes() == original
    assert len(records) == 2
    for version in VERSIONS:
        case = output / device.name / version / source.stem
        result = json.loads((case / 'run.json').read_text())
        assert result['cards'] == result['pixel_and_layout_checks'] == 16
        assert result['exit_code'] == 0
        assert (case / 'cards_overview.png').exists()
        assert (case.parent / 'overlays.png').exists()
    assert (output / device.name / 'comparison.md').exists()
    with pytest.raises(FileExistsError):
        run(fixtures, output)
