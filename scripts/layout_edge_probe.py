"""Compare binary and continuous horizontal gradients without changing detection."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def edge_maps(image):
    smooth = cv2.GaussianBlur(image, (3, 3), 0)
    gx = np.abs(cv2.Sobel(smooth, cv2.CV_32F, 1, 0)).max(axis=2)
    gy = np.abs(cv2.Sobel(smooth, cv2.CV_32F, 0, 1)).max(axis=2)
    threshold = max(35., float(np.percentile(np.maximum(gx, gy), 65)) * .7)
    direction = gy > gx * 1.15
    return ((gy > threshold) & direction).astype(np.uint8), np.where(direction, gy, 0.)


def probe(source, manifest, output):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    image = cv2.imdecode(np.frombuffer(source.read_bytes(), np.uint8), 1)
    if image is None:
        raise ValueError(f"Cannot decode {source}")
    binary, strength = edge_maps(image)
    attempts = [a['candidate'] for a in manifest['attempts'] if a['candidate']]
    if not attempts:
        raise ValueError(f"No candidate geometry in manifest for {source}")
    first = attempts[0]
    left, right = first['left'], first['right']
    width = right - left
    radius = max(2, round(width * .025))
    top = manifest['anchor'][1]
    bottom = min(image.shape[0], top + 5 * width)
    x0, x1 = max(0, left - width // 3), min(image.shape[1], right + width)
    records = []
    for y in range(top, bottom):
        a, b = max(0, y - radius), min(image.shape[0], y + radius + 1)
        records.append({
            'y': y,
            'binary_line': float(binary[y, left:right].mean()),
            'strength_line': float(strength[y, left:right].mean()),
            'binary_band': float(binary[a:b, left:right].max(axis=0).mean()),
            'strength_band': float(strength[a:b, left:right].max(axis=0).mean()),
        })
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'profiles.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    roi = np.s_[top:bottom, x0:x1]
    raw = strength[roi]
    nonzero = raw[raw > 0]
    display_scale = float(np.percentile(nonzero, 99)) if nonzero.size else 1.
    heat = cv2.applyColorMap(np.uint8(np.clip(raw / display_scale, 0, 1) * 255), cv2.COLORMAP_INFERNO)
    panels = [image[roi].copy(), cv2.cvtColor(binary[roi] * 255, cv2.COLOR_GRAY2BGR), heat]
    markers = {c['top']: 'v2 candidate' for c in attempts if c['top'] is not None}
    if source.parent.name == 'iPhone13pro' and source.stem == 'Test_SR_cut_top':
        # Diagnostic comparisons only; these are not manual ground-truth labels.
        markers.update({320: 'priority trial', 335: 'old wrong candidate',
                        362: 'alternative edge', 369: 'continuous trial'})
    for panel in panels:
        for x in (left, right):
            cv2.line(panel, (x - x0, 0), (x - x0, bottom - top - 1), (0, 255, 0), 1)
        for y, label in sorted(markers.items()):
            if top <= y < bottom:
                # Keep the measured frame unobscured by diagnostic markers.
                cv2.line(panel, (0, y - top), (left - x0 - 3, y - top), (0, 0, 255), 1)
                cv2.putText(panel, str(y), (3, y - top - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, .38, (255, 255, 255), 1)
    titles = ['Original (green = measured X range)', 'Current binary horizontal edges',
              'Continuous gradient (P99 display only)']
    tiles = []
    for title, panel in zip(titles, panels):
        tile = cv2.copyMakeBorder(panel, 30, 0, 0, 0, cv2.BORDER_CONSTANT)
        cv2.putText(tile, title, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, .42, (255, 255, 255), 1)
        tiles.append(tile)
    ok, encoded = cv2.imencode('.png', np.hstack(tiles))
    if not ok:
        raise ValueError('Cannot encode comparison')
    (output / 'comparison.png').write_bytes(encoded.tobytes())
    selected = [dict(label=label, **records[y - top]) for y, label in sorted(markers.items())
                if top <= y < bottom]
    result = {'source_sha256': digest, 'x_range': [left, right],
              'y_range': [top, bottom], 'band_radius': radius,
              'display_p99': display_scale, 'selected_positions': selected}
    (output / 'metrics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, default=ROOT / 'tests/fixtures/private')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs')
    args = parser.parse_args(argv)
    sources = sorted(args.fixtures.glob('*/*.png'))
    if not sources:
        raise ValueError('No device-organized PNG fixtures')
    targets = [(p, args.output / p.parent.name / 'edge_strength' / p.stem) for p in sources]
    if any(target.exists() for _, target in targets):
        raise FileExistsError('Probe output exists; choose another output root')
    lines = ['# Horizontal edge strength experiment', '',
             'Detection is unchanged. Green lines bound the measured first-column strip; '
             'red markers are detector candidates, not ground truth. '
             'CSV values use original pixels and unnormalized Sobel units. '
             'Only the heatmap is clipped at the ROI P99 for display. '
             'Band metrics reproduce the current per-column maximum; '
             'line metrics use a single Y. Candidate generation/ranking is not rerun.', '',
             'For iPhone SR cut-top, 320 is the priority-only trial, 335 is the old wrong candidate, '
             '362 is an alternative edge and 369 is the continuous-top trial. '
             'These labels are historical candidates, not manual ground truth.', '',
             '| Device | Fixture | Comparison |', '|---|---|---|']
    disputed = []
    for source, target in targets:
        existing = ROOT / 'outputs' / source.parent.name / 'v2' / source.stem / 'manifest.json'
        manifest = json.loads(existing.read_text(encoding='utf-8'))
        result = probe(source, manifest, target)
        if source.parent.name == 'iPhone13pro' and source.stem == 'Test_SR_cut_top':
            disputed = result['selected_positions']
        relative = target.relative_to(args.output).as_posix()
        lines.append(f'| {source.parent.name} | {source.stem} | [image]({relative}/comparison.png) |')
        print(f'{source.parent.name}/{source.stem}', flush=True)
    if disputed:
        lines += ['', '## Disputed iPhone SR cut-top positions', '',
                  'All positions below use the SAME X strip (635..796); '
                  'this isolates the change of feature rather than rectangle width.', '',
                  '| Y | Historical candidate | Binary band coverage | Raw band strength | Raw single-line strength |',
                  '|---:|---|---:|---:|---:|']
        for row in disputed:
            if row['y'] == 124:
                continue
            lines.append(f"| {row['y']} | {row['label']} | {row['binary_band']:.3f} | "
                         f"{row['strength_band']:.2f} | {row['strength_line']:.2f} |")
        lines += ['', 'The 369 trial has higher raw gradient strength than the old 335 candidate, '
                  'although its binary band coverage is lower. However 320 is even stronger, '
                  'so retaining strength alone does not identify the frame. '
                  'No detection-accuracy improvement has been established; production detection remains unchanged.']
    (args.output / 'edge_strength_comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
