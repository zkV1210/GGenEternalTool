import json

import cv2
import pytest

from scripts.layout_batch import VERSIONS, report, run
from test_card_detection import make_screen


def test_report_marks_unrun_versions_for_new_fixtures(monkeypatch):
    from pathlib import Path
    from scripts import layout_batch

    written = {}
    monkeypatch.setattr(Path, 'write_text', lambda path, text, **kwargs: written.setdefault(path.name, text))
    monkeypatch.setattr(layout_batch, '_save', lambda *_: None)
    records = [
        {'device': 'test_device', 'fixture': 'old', 'version': 'baseline', 'cards': 8, 'status': 'ok'},
        {'device': 'test_device', 'fixture': 'old', 'version': 'v2', 'cards': 8, 'status': 'ok'},
        {'device': 'test_device', 'fixture': 'new', 'version': 'v2', 'cards': 8, 'status': 'ok'},
    ]
    report(Path('unused-report-probe'), records)
    assert '| new | not run | [8](v2/new/cards_overview.png)' in written['comparison.md']
    assert '[8](baseline/old/cards_overview.png)' in written['comparison.md']


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
    assert len(records) == 3
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
