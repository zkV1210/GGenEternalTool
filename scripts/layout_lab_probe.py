"""Inspect Lab Chroma gradients alongside RGB and a/b without changing detection."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def gradients(image):
    rgb = cv2.GaussianBlur(image, (3, 3), 0)
    lab = cv2.cvtColor(image.astype(np.float32) / 255., cv2.COLOR_BGR2Lab)
    # Differentiate Chroma itself, not the length of the a/b gradient vector.
    chroma = cv2.GaussianBlur(np.hypot(lab[:, :, 1], lab[:, :, 2]), (3, 3), 0)
    lab = cv2.GaussianBlur(lab, (3, 3), 0)
    maps = {}
    for direction, dx, dy in [('horizontal', 0, 1), ('vertical', 1, 0)]:
        rgb_gradient = np.abs(cv2.Sobel(rgb, cv2.CV_32F, dx, dy)).max(axis=2)
        ab = cv2.Sobel(lab[:, :, 1:], cv2.CV_32F, dx, dy)
        maps[direction] = {
            'rgb': rgb_gradient,
            'a': np.abs(ab[:, :, 0]),
            'b': np.abs(ab[:, :, 1]),
            'ab': np.sqrt(np.square(ab).sum(axis=2)),
            'chroma': np.abs(cv2.Sobel(chroma, cv2.CV_32F, dx, dy)),
        }
    # Keep the previous direction gate identical for every representation.
    return {direction: {name: np.where(values > maps[other][name] * 1.15, values, 0.)
                        for name, values in maps[direction].items()}
            for direction, other in [('horizontal', 'vertical'), ('vertical', 'horizontal')]}


def probe(source, manifest, output):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    image = cv2.imdecode(np.frombuffer(source.read_bytes(), np.uint8), 1)
    if image is None:
        raise ValueError(f'Cannot decode {source}')
    maps = gradients(image)
    candidates = [a['candidate'] for a in manifest['attempts'] if a['candidate']]
    first = candidates[0]
    left, right = first['left'], first['right']
    width, top = right - left, manifest['anchor'][1]
    bottom = min(image.shape[0], top + 5 * width)
    x0, x1 = max(0, left - width // 3), min(image.shape[1], right + width)
    radius = max(2, round(width * .025))
    roi = np.s_[top:bottom, x0:x1]
    output.mkdir(parents=True, exist_ok=False)
    scales = {}
    for name in ('rgb', 'a', 'b', 'ab', 'chroma'):
        values = np.concatenate([maps[d][name][roi].ravel() for d in maps])
        positive = values[values > 0]
        scales[name] = float(np.percentile(positive, 99)) if positive.size else 1.
    profiles = {}
    for direction, axes in maps.items():
        panels = [image[roi].copy()]
        for name, values in axes.items():
            display = np.uint8(np.clip(values[roi] / scales[name], 0, 1) * 255)
            panels.append(cv2.applyColorMap(display, cv2.COLORMAP_INFERNO))
        tiles = []
        for title, panel in zip(['Original', 'RGB', 'Lab a*', 'Lab b*', 'Lab a*b* norm', 'Chroma C*'], panels):
            # Ticks stay outside the measured frame, leaving its pixels visible.
            for x in (left, right):
                cv2.line(panel, (x - x0, 0), (x - x0, 8), (0, 255, 0), 1)
            if source.parent.name == 'iPhone13pro' and source.stem == 'Test_SR_cut_top':
                for y in (320, 335, 362, 369):
                    cv2.line(panel, (0, y - top), (left - x0 - 3, y - top), (0, 0, 255), 1)
                    cv2.putText(panel, str(y), (2, y - top - 3),
                                cv2.FONT_HERSHEY_SIMPLEX, .35, (255, 255, 255), 1)
            tile = cv2.copyMakeBorder(panel, 30, 0, 0, 0, cv2.BORDER_CONSTANT)
            cv2.putText(tile, f'{title}: {direction}', (4, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, .4, (255, 255, 255), 1)
            tiles.append(tile)
        ok, encoded = cv2.imencode('.png', np.hstack(tiles))
        if not ok:
            raise ValueError('Cannot encode comparison')
        (output / f'{direction}.png').write_bytes(encoded.tobytes())
        records = []
        positions = range(top, bottom) if direction == 'horizontal' else range(x0, x1)
        for position in positions:
            row = {'position': position}
            for name, values in axes.items():
                if direction == 'horizontal':
                    line = values[position, left:right]
                    band = values[max(0, position - radius):position + radius + 1, left:right]
                    support = band.max(axis=0)
                else:
                    line = values[top:bottom, position]
                    band = values[top:bottom, max(0, position - radius):position + radius + 1]
                    support = band.max(axis=1)
                row[name + '_line'] = float(line.mean())
                row[name + '_band'] = float(support.mean())
            records.append(row)
        profiles[direction] = records
        with (output / f'{direction}.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    result = {'source_sha256': digest, 'x_range': [left, right], 'y_range': [top, bottom],
              'display_p99': scales, 'band_radius': radius,
              'coordinate_note': 'First candidate X range is a diagnostic reference, not newly detected sides.'}
    if source.parent.name == 'iPhone13pro' and source.stem == 'Test_SR_cut_top':
        result['historical_top_candidates'] = [r for r in profiles['horizontal']
                                               if r['position'] in (320, 335, 362, 369)]
        result['historical_side_candidates'] = [r for r in profiles['vertical']
                                                if r['position'] in (635, 796, 832)]
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
    if any((args.output / p.parent.name / 'lab_chroma' / p.stem).exists() for p in sources):
        raise FileExistsError('Lab output exists; choose another output root')
    lines = ['# Lab Chroma edge preprocessing', '',
             'Diagnostic only: no detection, ranking or crop changes. Float BGR is normalized '
             'to 0..1 before conversion. Sobel uses Lab a* and b* separately; joint strength is '
             'sqrt(da^2 + db^2). Chroma is C*=sqrt(a*^2+b*^2), computed BEFORE smoothing '
             'and differentiation; it discards hue direction. The same 3x3 Gaussian '
             'and 1.15 direction gate apply. '
             'Each representation has its own ROI P99 display scale shared between horizontal '
             'and vertical views; apparent brightness is NOT comparable across color spaces. '
             'CSVs contain raw gradients, not display-scaled numbers. '
             'Coordinates are historical detector candidates, not manual ground truth.', '',
             '| Device | Fixture | Horizontal | Vertical |', '|---|---|---|---|']
    disputed = None
    for source in sources:
        device, stem = source.parent.name, source.stem
        manifest = json.loads((ROOT / 'outputs' / device / 'v2' / stem / 'manifest.json').read_text(encoding='utf-8'))
        output = args.output / device / 'lab_chroma' / stem
        result = probe(source, manifest, output)
        if device == 'iPhone13pro' and stem == 'Test_SR_cut_top':
            disputed = result
        relative = output.relative_to(args.output).as_posix()
        lines.append(f'| {device} | {stem} | [image]({relative}/horizontal.png) | [image]({relative}/vertical.png) |')
        print(f'{device}/{stem}', flush=True)
    if disputed:
        lines += ['', '## iPhone SR cut-top observations', '',
                  'Use within-representation ratios: RGB and Lab raw units differ.', '',
                  '| Historical Y | RGB line | Lab ab line | Chroma line | RGB band | Lab ab band | Chroma band |',
                  '|---:|---:|---:|---:|---:|---:|---:|']
        for row in disputed['historical_top_candidates']:
            lines.append(f"| {row['position']} | {row['rgb_line']:.2f} | {row['ab_line']:.2f} | "
                         f"{row['chroma_line']:.2f} | {row['rgb_band']:.2f} | "
                         f"{row['ab_band']:.2f} | {row['chroma_band']:.2f} |")
        lines += ['', 'These are feature comparisons, not redetected card boundaries. '
                  'Chroma discards changes in hue at equal chroma and neutral brightness edges; '
                  'some genuine frame edges may therefore also disappear. '
                  'No detection-accuracy gain is claimed.']
    (args.output / 'lab_chroma_comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
