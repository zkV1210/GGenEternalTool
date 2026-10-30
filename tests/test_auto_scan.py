import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from gget_scanner.config.layout_loader import load_layout
from gget_scanner.image.layout import resolve_layout
from gget_scanner.pipeline.auto_scan import auto_scan, main
from test_card_detection import make_screen


def test_cli_unicode_export_reload_and_overwrite_protection(tmp_path):
    image, _ = make_screen()
    path = tmp_path / '遊戲截圖.png'
    path.write_bytes(cv2.imencode('.png', image)[1].tobytes())
    output = tmp_path / '自動定位'
    assert main([str(path), '--output', str(output)]) == 0
    manifest = json.loads((output / 'manifest.json').read_text())
    profile = load_layout(output / 'layout.json')
    resolved = resolve_layout(profile, (1200, 800))
    assert len(manifest['cards']) == len(resolved.cards) == 16
    for record, card in zip(manifest['cards'], resolved.cards):
        assert record['bounds'] == list(card.bounds)
        crop = cv2.imdecode(np.frombuffer((output / record['file']).read_bytes(), np.uint8), 1)
        l, t, r, b = card.bounds
        np.testing.assert_array_equal(crop, image[t:b, l:r])
    before = (output / 'manifest.json').read_bytes()
    with pytest.raises(SystemExit):
        main([str(path), '--output', str(output)])
    assert (output / 'manifest.json').read_bytes() == before


def test_no_cards_writes_diagnostics_but_no_layout(tmp_path):
    path = tmp_path / 'blank.png'
    path.write_bytes(cv2.imencode('.png', np.zeros((300, 500, 3), np.uint8))[1].tobytes())
    output = tmp_path / 'diagnostics'
    assert main([str(path), '--output', str(output)]) == 1
    assert sorted(p.name for p in output.iterdir()) == ['manifest.json', 'overlay.png']


def test_cli_split_layouts_preserve_original_columns(tmp_path):
    image, _ = make_screen(rows=1, missing=((0, 3),))
    path = tmp_path / 'gap.png'
    path.write_bytes(cv2.imencode('.png', image)[1].tobytes())
    output = tmp_path / 'split'
    assert main([str(path), '--output', str(output)]) == 0
    manifest = json.loads((output / 'manifest.json').read_text())
    assert len(manifest['layouts']) == 2
    assert [c['column'] for c in manifest['cards']] == [0, 1, 2, 4, 5, 6, 7]
    for name in manifest['layouts']:
        layout = resolve_layout(load_layout(output / name), (1200, 800))
        records = [c for c in manifest['cards'] if c['layout_file'] == name]
        assert len(records) == len(layout.cards)
        for record, card in zip(records, layout.cards):
            assert record['layout_index'] == card.index
            assert record['bounds'] == list(card.bounds)


@pytest.mark.parametrize('scale', [.65, 1., 1.3])
@pytest.mark.parametrize('jpeg', [False, True])
def test_private_screenshot_against_visually_checked_frame_bounds(scale, jpeg):
    path = Path(__file__).parent / 'fixtures/private/Test.png'
    if not path.exists():
        path = path.with_name('Test_UR.png')
    if not path.exists():
        pytest.skip('Optional private screenshot is unavailable')
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), 1)
    if image.shape[:2] != (1668, 2388):
        pytest.skip('Manual frame annotations apply only to the original 2388x1668 screenshot')
    # Outer structural frame, excluding glow; checked against the original image.
    # These annotations are test expectations only, never detector inputs.
    xs = [432, 668, 904, 1140, 1376, 1612, 1848, 2084]
    image = cv2.resize(image, None, fx=scale, fy=scale)
    if jpeg:
        image = cv2.imdecode(cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 70])[1], 1)
    result = auto_scan(image)
    # Compression can weaken a border enough for conservative rejection.
    assert len(result.crops) in ((15, 16) if jpeg else (16,))
    assert len(result.attempts) == 2
    for crop in result.crops:
        row, col = crop.card.row, crop.card.column
        expected = tuple(round(v * scale) for v in
                         (xs[col], (178, 630)[row], xs[col] + 192, (572, 1022)[row]))
        actual = crop.card.bounds
        intersection = max(0, min(actual[2], expected[2]) - max(actual[0], expected[0])) * max(0, min(actual[3], expected[3]) - max(actual[1], expected[1]))
        union = ((actual[2] - actual[0]) * (actual[3] - actual[1])
                 + (expected[2] - expected[0]) * (expected[3] - expected[1]) - intersection)
        assert intersection / union > (.94 if scale == 1. and not jpeg else .90)


# Visually checked structural frames, not glow. Pixel annotations are test-only;
# the detector receives just the source image, never its name or these positions.
PRIVATE_ROW_BOUNDS = {
    'Test_SR': ((178, 572), (630, 1022)),
    'Test_SSR': ((178, 572), (630, 1022)),
    'Test_UR': ((178, 572), (630, 1022)),
    'Test_SR_touch_top': ((152, 544), (602, 994)),
    'Test_SSR_touch_top': ((152, 544), (602, 994)),
    'Test_UR_touch_top': ((152, 544), (602, 994)),
    'Test_SR_cut_top': ((366, 760), (816, 1210)),
    'Test_SSR_cut_top': ((343, 738), (793, 1187)),
    'Test_UR_cut_top': ((380, 774), (830, 1224)),
}


@pytest.mark.parametrize('stem', PRIVATE_ROW_BOUNDS)
def test_nine_private_screenshots_match_annotated_rows(stem):
    path = Path(__file__).parent / 'fixtures/private' / f'{stem}.png'
    if not path.exists():
        pytest.skip(f'Optional private {path.name} is unavailable')
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), 1)
    assert image.shape[:2] == (1668, 2388), 'Annotations require the original screenshot'
    result = auto_scan(image)
    assert len(result.crops) == 16
    start_row = 1 if stem.endswith('_cut_top') else 0
    assert [(c.card.row, c.card.column) for c in result.crops] == [
        (r, c) for r in range(start_row, start_row + 2) for c in range(8)]
    assert len(result.attempts) == start_row + 2
    if start_row:
        assert not result.attempts[0].validation.valid
    for crop in result.crops:
        l, t, r, b = crop.card.bounds
        top, bottom = PRIVATE_ROW_BOUNDS[stem][crop.card.row - start_row]
        left = 432 + 236 * crop.card.column
        right = left + 192
        intersection = max(0, min(r, right) - max(l, left)) * max(0, min(b, bottom) - max(t, top))
        union = (r - l) * (b - t) + (right - left) * (bottom - top) - intersection
        assert intersection / union > .90, (stem, crop.card.row, crop.card.column, crop.card.bounds)
