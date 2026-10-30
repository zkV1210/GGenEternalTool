"""Anchor-led card geometry. All coordinates remain in source-image pixels."""

from dataclasses import dataclass

import cv2
import numpy as np

from gget_scanner.config.layout_models import Bounds, LayoutError

CARD_ASPECT_RANGE = (.43, .58)


@dataclass(frozen=True)
class ImageFeatures:
    gray: np.ndarray
    vertical: np.ndarray
    horizontal: np.ndarray
    canny: np.ndarray
    edge_radius: int


@dataclass(frozen=True)
class Candidate:
    left: int
    right: int
    visible_top: int
    visible_bottom: int
    top: int | None = None
    bottom: int | None = None

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def bounds(self) -> Bounds | None:
        if self.top is None or self.bottom is None:
            return None
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True)
class Validation:
    valid: bool
    support: tuple[float, float, float, float]  # left, top, right, bottom
    reason: str = ""


@dataclass(frozen=True)
class GridRow:
    cards: tuple[tuple[int, Candidate, Validation], ...]
    step_x: float | None


def prepare_image(image: np.ndarray) -> ImageFeatures:
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.size == 0
            or image.ndim not in (2, 3)
            or (image.ndim == 3 and image.shape[2] not in (3, 4))):
        raise LayoutError("image: expected nonempty uint8 grayscale, BGR or BGRA")
    source = image if image.ndim == 2 else image[:, :, :3]
    gray = source if source.ndim == 2 else cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    # Max channel derivative retains borders whose colors have similar luminance.
    smooth = cv2.GaussianBlur(source, (3, 3), 0)
    gx = np.abs(cv2.Sobel(smooth, cv2.CV_32F, 1, 0))
    gy = np.abs(cv2.Sobel(smooth, cv2.CV_32F, 0, 1))
    if gx.ndim == 3:
        gx, gy = gx.max(axis=2), gy.max(axis=2)
    threshold = max(35., float(np.percentile(np.maximum(gx, gy), 65)) * .7)
    vertical = ((gx > threshold) & (gx > gy * 1.15)).astype(np.uint8)
    horizontal = ((gy > threshold) & (gy > gx * 1.15)).astype(np.uint8)
    transitions = np.diff(np.pad(vertical, ((0, 0), (1, 1))).astype(np.int8), axis=1)
    starts = np.nonzero(transitions == 1)[1]
    ends = np.nonzero(transitions == -1)[1]
    thickness = float(np.median(ends - starts)) if starts.size else 1.
    edge_radius = int(np.ceil(thickness / 2)) + 2  # Gaussian + Sobel footprint.
    return ImageFeatures(gray, vertical, horizontal, cv2.Canny(gray, 60, 160), edge_radius)


def detect_anchor(image: ImageFeatures) -> Bounds:
    """Return the observed list line (x0, y0, x1, y1), or fail explicitly."""
    height, width = image.gray.shape
    lines = cv2.HoughLinesP(image.canny[:max(1, int(height * .35))], 1,
                            np.pi / 180, max(20, width // 12),
                            minLineLength=width * .25, maxLineGap=max(2, width // 100))
    segments = []
    for x0, y0, x1, y1 in (() if lines is None else lines[:, 0]):
        if x0 > x1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        if x1 == x0 or abs(y1 - y0) / (x1 - x0) > .01:
            continue
        y = int(round((int(y0) + int(y1)) / 2))
        if y < height * .025:
            continue
        band = image.gray[max(0, y - 2):y + 3, x0:x1 + 1]
        # The separator is translucent white: local contrast matters more than
        # an absolute near-white threshold, which rejects dark backgrounds.
        surround = image.gray[max(0, y - 6):y + 7, x0:x1 + 1]
        peak = band.max(axis=0).astype(float)
        if np.mean((peak >= 110) & (peak - surround.min(axis=0) >= 30)) >= .65:
            segments.append((int(x0), y, int(x1), y))
    # Merge duplicate Canny edges and nearby fragments, without bridging large UI gaps.
    merged = []
    for x0, y, x1, _ in sorted(segments, key=lambda s: s[0]):
        for i, (a, b, c, _) in enumerate(merged):
            if abs(y - b) <= max(3, height * .004) and x0 <= c + width * .025:
                merged[i] = (min(a, x0), min(b, y), max(c, x1), min(b, y))
                break
        else:
            merged.append((x0, y, x1, y))
    if not merged:
        raise LayoutError("anchor: no supported horizontal list line")
    # The list separator spans substantially more of the screen than header buttons.
    line = max(merged, key=lambda s: s[2] - s[0])
    if line[2] - line[0] < width * .4:
        raise LayoutError("anchor: horizontal line is too short or ambiguous")
    radius = max(3, round(height * .004))
    start = max(0, line[1] - radius)
    brightness = image.gray[start:line[1] + radius + 1, line[0]:line[2]].mean(axis=1)
    y = start + int(np.median(np.flatnonzero(brightness >= brightness.max() * .98)))
    return line[0], y, line[2], y


def _peaks(values: np.ndarray, minimum: float, distance: int) -> list[int]:
    """Group thick edges, then suppress nearby duplicate frame/glow responses."""
    indices = np.flatnonzero(values >= minimum)
    if not indices.size:
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    peaks = [int(g[np.argmax(values[g])]) for g in groups]
    selected = []
    for p in sorted(peaks, key=lambda p: -values[p]):
        if all(abs(p - q) > distance for q in selected):
            selected.append(p)
    return sorted(selected)


def _vertical_edges(image: ImageFeatures, roi: Bounds) -> list[int]:
    left, top, right, bottom = roi
    mask = image.vertical[top:bottom, left:right]
    if mask.size == 0:
        return []
    h = image.gray.shape[0]
    connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                  np.ones((max(3, round(h * .006)), 1), np.uint8))
    sustained = cv2.morphologyEx(connected, cv2.MORPH_OPEN,
                                  np.ones((max(5, round(h * .055)), 1), np.uint8))
    projection = sustained.sum(axis=0).astype(float)
    return [left + p for p in _peaks(projection, max(5, h * .055), max(2, round(h * .003)))]


def _horizontal_edges(image: ImageFeatures, left: int, right: int,
                      top: int, bottom: int) -> list[int]:
    h, w = image.gray.shape
    left, right, top, bottom = max(0, left), min(w, right), max(0, top), min(h, bottom)
    if top >= bottom or left >= right:
        return []
    # Keep nearby horizontal responses distinct; tolerance belongs in validation.
    projection = image.horizontal[top:bottom, left:right].mean(axis=1)
    return [top + p for p in _peaks(projection, .45, max(2, round((right - left) * .025)))]


def _support(image: ImageFeatures, candidate: Candidate) -> tuple[float, float, float, float]:
    if candidate.bounds is None:
        return (0., 0., 0., 0.)
    left, top, right, bottom = candidate.bounds
    h, w = image.gray.shape
    if not 0 <= left < right < w or not 0 <= top < bottom < h:
        return (0., 0., 0., 0.)
    radius = max(2, round(candidate.width * .025))
    # Ignore short bevelled corners for side coverage, but check their joins below.
    inset = max(1, round(candidate.width * .12))
    v = image.vertical
    horizontal = image.horizontal
    def side(x):
        return float(v[top + inset:bottom - inset, max(0, x - radius):x + radius + 1].max(axis=1).mean())
    def end(y):
        return float(horizontal[max(0, y - radius):y + radius + 1, left:right].max(axis=0).mean())
    return side(left), end(top), side(right), end(bottom)


def _spanning_line(image: ImageFeatures, y: int) -> bool:
    """Aligned card bottoms have gaps; a toolbar has one long connected run."""
    width = image.gray.shape[1]
    line = image.horizontal[max(0, y - 2):y + 3].max(axis=0).reshape(1, -1)
    line = cv2.morphologyEx(line, cv2.MORPH_CLOSE,
                            np.ones((1, max(3, round(width * .003))), np.uint8))[0]
    runs = np.flatnonzero(np.diff(np.r_[0, line, 0].astype(int)))
    return any(b - a > width * .6 for a, b in zip(runs[::2], runs[1::2]))


def _gap_support(image: ImageFeatures, left: int, right: int, y: int) -> list[float]:
    width = right - left
    radius = max(2, round(width * .025))
    # A nearby floor/toolbar line is not the card's bottom. Unlike frame
    # coverage, continuation through a gap must be at the same Y coordinate.
    y_radius = max(1, round(width * .005))
    gaps = []
    for a, b in ((left - round(width * .3), left - radius),
                 (right + radius, right + round(width * .3))):
        if 0 <= a < b <= image.gray.shape[1]:
            gaps.append(float(image.horizontal[max(0, y - y_radius):y + y_radius + 1, a:b].max(axis=0).mean()))
    return gaps


def edge_tolerance(image: ImageFeatures, candidate: Candidate) -> int:
    """Pixel uncertainty from observed side thickness and robust center scatter."""
    top = candidate.top if candidate.top is not None else candidate.visible_top
    bottom = candidate.bottom if candidate.bottom is not None else candidate.visible_bottom
    inset = round(candidate.width * .12)  # Exclude the existing bevel neighborhoods.
    top, bottom = top + inset, bottom - inset
    offsets, half_widths = [], []
    for x in (candidate.left, candidate.right):
        radius = max(3, inset)
        left, right = max(0, x - radius), min(image.gray.shape[1], x + radius + 1)
        for line in image.vertical[top:bottom, left:right]:
            runs = np.flatnonzero(np.diff(np.r_[0, line, 0].astype(int)))
            pairs = list(zip(runs[::2], runs[1::2]))
            if pairs:
                a, b = min(pairs, key=lambda ab: abs(left + (ab[0] + ab[1] - 1) / 2 - x))
                offsets.append(left + (a + b - 1) / 2 - x)
                half_widths.append((b - a) / 2)
    if not offsets:
        return 2  # One-pixel Gaussian radius plus one-pixel Sobel radius.
    center = float(np.median(offsets))
    scatter = float(np.median(np.abs(np.asarray(offsets) - center)))
    return max(2, int(np.ceil(abs(center) + np.median(half_widths) + 3 * scatter + 2)))


def detect_card(image: ImageFeatures, search_roi: Bounds,
                reference: Candidate | None = None) -> Candidate | None:
    """Propose the earliest frame in a bounded strip; missing ends stay unknown."""
    left, top, right, bottom = search_roi
    height, width = image.gray.shape
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        raise LayoutError("detection search ROI is outside the image")
    edges = _vertical_edges(image, search_roi)
    tolerance = edge_tolerance(image, reference) if reference else None
    candidates = []
    partials = []
    for i, x0 in enumerate(edges):
        for x1 in edges[i + 1:]:
            cw = x1 - x0
            # Only geometric fit and the filter's resolving power bound width;
            # no percentage of the full screenshot determines a card's size.
            if not 2 * image.edge_radius + 1 <= cw <= min(right - left, (bottom - top) * CARD_ASPECT_RANGE[1]):
                continue
            if reference and (abs(cw - reference.width) > 2 * tolerance
                              or abs(x0 - reference.left) > tolerance):
                continue
            # Both sides must persist over overlapping Y positions.
            radius = image.edge_radius
            a = image.vertical[top:bottom, max(0, x0 - radius):x0 + radius + 1].max(axis=1)
            b = image.vertical[top:bottom, max(0, x1 - radius):x1 + radius + 1].max(axis=1)
            shared = (a & b).astype(np.uint8).reshape(-1, 1)
            shared = cv2.morphologyEx(shared, cv2.MORPH_CLOSE,
                                       np.ones((2 * radius + 1, 1), np.uint8))[:, 0]
            runs = np.flatnonzero(np.diff(np.r_[0, shared, 0].astype(int)))
            for start, stop in zip(runs[::2], runs[1::2]):
                if stop - start < cw * .6:
                    continue
                vtop, vbottom = top + int(start), top + int(stop)
                tops = _horizontal_edges(image, x0, x1,
                                           max(top, vtop - round(cw * .35)),
                                           min(bottom, vtop + round(cw * .15)))
                partials.append(Candidate(x0, x1, vtop, vbottom,
                                          tops[0] if tops else None))
                for y0 in tops:
                    if reference and reference.bounds:
                        expected_height = reference.bottom - reference.top
                        height_error = 2 * tolerance
                        low, high = expected_height - height_error, expected_height + height_error
                    else:
                        low, high = cw / CARD_ASPECT_RANGE[1], cw / CARD_ASPECT_RANGE[0]
                    ends = _horizontal_edges(image, x0, x1, y0 + int(np.floor(low)),
                                               min(bottom, y0 + int(np.ceil(high)) + 1))
                    for y1 in ends:
                        if y1 < vbottom - cw * .06 or y1 > vbottom + cw * .22:
                            continue
                        c = Candidate(x0, x1, vtop, vbottom, y0, y1)
                        support = _support(image, c)
                        if min(support) < .45:
                            continue
                        score = (sum(support) - 2 * abs(cw / (y1 - y0) - .5)
                                 - (abs(y1 - vbottom) + abs(y0 - vtop)) / cw
                                 - (1 if _spanning_line(image, y1) else 0))
                        if reference and reference.bounds:
                            score -= (abs(cw / reference.width - 1)
                                      + abs((y1 - y0) / (reference.bottom - reference.top) - 1))
                        gaps = _gap_support(image, x0, x1, y1)
                        if len(gaps) == 2 and min(gaps) > .85:
                            score -= 1
                        candidates.append((c, score))
    if candidates:
        # Establish the first column from strong frames before choosing a row.
        # Otherwise artwork in a clipped row's second column can win by appearing
        # earlier, even though the next row provides a reliable first-column frame.
        best = max(s for _, s in candidates)
        strong = [(c, s) for c, s in candidates if s >= best - .25]
        first_left = min(c.left for c, _ in strong)
        column = [(c, s) for c, s in strong if c.left <= first_left + c.width * .12]
        first_top = min(c.visible_top for c, _ in column)
        row = [(c, s) for c, s in column if c.visible_top <= first_top + c.width * .25]
        chosen = max(row, key=lambda cs: cs[1])[0]
        earlier = [p for p in partials if abs(p.left - chosen.left) < chosen.width * .1
                   and abs(p.width / chosen.width - 1) < .12
                   and p.visible_top < chosen.top - chosen.width * .5
                   and p.visible_bottom < chosen.top]
        return min(earlier, key=lambda p: p.visible_top) if earlier else chosen
    if partials:
        return min(partials, key=lambda c: (c.visible_top, c.left, -c.width))
    return None


def validate_card(image: ImageFeatures, candidate: Candidate,
                  reference: Candidate | None = None) -> Validation:
    support = _support(image, candidate)
    def reject(reason):
        return Validation(False, support, reason)
    if candidate.bounds is None:
        return reject("missing observed top or bottom")
    left, top, right, bottom = candidate.bounds
    h, w = image.gray.shape
    if not (0 < left < right < w - 1 and 0 < top < bottom < h - 1):
        return reject("frame touches image cutoff")
    cw, ch = candidate.width, bottom - top
    if not CARD_ASPECT_RANGE[0] <= cw / ch <= CARD_ASPECT_RANGE[1]:
        return reject("incompatible card aspect ratio")
    if reference and reference.bounds:
        rh = reference.bottom - reference.top
        if abs(cw / reference.width - 1) > .12 or abs(ch / rh - 1) > .12:
            return reject("inconsistent card size")
    if support[0] < .65 or support[2] < .65 or support[1] < .55 or support[3] < .6:
        return reject("insufficient frame edge coverage")
    if _spanning_line(image, bottom):
        return reject("bottom is a screen-spanning UI separator")
    radius = max(2, round(cw * .025))
    extensions = []
    for x in (left, right):
        extension = image.vertical[bottom + radius:min(h, bottom + round(cw * .2)),
                                   max(0, x - radius):x + radius + 1]
        extensions.append(float(extension.max(axis=1).mean()) if extension.size else 0.)
    # Background edges may align with one side after a genuine corner ends.
    # A false internal horizontal boundary leaves both frame sides continuing.
    if min(extensions) > .75:
        return reject("both sides continue past the proposed bottom")
    # Card corners can be bevelled; a join must exist in each corner neighborhood.
    radius = max(3, round(cw * .15))
    for x in (left, right):
        for y in (top, bottom):
            region = np.s_[max(0, y - radius):min(h, y + radius + 1),
                           max(0, x - radius):min(w, x + radius + 1)]
            if image.vertical[region].sum() < radius or image.horizontal[region].sum() < radius:
                return reject("unsupported corner join")
    # A toolbar separator continues through gaps. Require local side termination
    # before accepting such a line as the bottom of a card.
    r = max(2, round(cw * .025))
    gaps = _gap_support(image, left, right, bottom)
    beyond = image.vertical[bottom + r:min(h, bottom + round(cw * .2)),
                            max(0, left - r):left + r + 1]
    if gaps and min(gaps) > .65 and beyond.size and beyond.max(axis=1).mean() > .45:
        return reject("bottom is a spanning UI edge, sides continue below")
    # A separator can also occlude both side endings; gaps alone then make its
    # putative bottom ambiguous. Keep this conservative rather than invent an end.
    if len(gaps) == 2 and min(gaps) > .85:
        return reject("bottom continues across both card gaps")
    return Validation(True, support)


def detect_next_row(image: ImageFeatures, previous_candidate: Candidate | None,
                    previous_roi: Bounds) -> Bounds | None:
    """Return exactly one next-row search strip; never recurse or scan to the bottom."""
    h, w = image.gray.shape
    if previous_candidate is None:
        # Initial detection already examined the Anchor-bounded image remainder.
        # Without a side pair there is no next-row origin to infer.
        return None
    c = previous_candidate
    margin = edge_tolerance(image, c)
    left, right = max(0, c.left - margin), min(w, c.right + margin + 1)
    # No assumed row gap: find the next observed top in this narrow strip, then
    # detect_card limits its bottom search using measured height (or aspect).
    top = (c.bottom if c.bottom is not None else c.visible_bottom) + margin
    return (left, top, right, h) if top < h else None


def expand_grid(image: ImageFeatures, validated_card: Candidate,
                optional_grid_reference: GridRow | None = None) -> GridRow:
    """Estimate a multi-edge period, then verify each predicted frame (at most 8)."""
    c = validated_card
    if c.bounds is None or not validate_card(image, c).valid:
        raise LayoutError("grid: baseline must be a validated complete card")
    h, w = image.gray.shape
    edges = _vertical_edges(image, (c.left, c.top, w, c.bottom))
    # Autocorrelation uses evidence from the entire row rather than differences
    # between adjacent peaks, which can belong to artwork inside the same card.
    projection = image.vertical[c.top:c.bottom, c.left:].mean(axis=0)
    projection = cv2.GaussianBlur(projection.reshape(1, -1), (0, 0),
                                  max(1., c.width * .01))[0]
    projection -= projection.mean()
    correlation = np.correlate(projection, projection, 'full')[len(projection) - 1:]
    low, high = round(c.width * 1.05), min(len(correlation), round(c.width * 1.55))
    step = None
    if high > low:
        lag = low + int(np.argmax(correlation[low:high]))
        if correlation[lag] > correlation[0] * .18:
            step = float(lag)
    if optional_grid_reference and optional_grid_reference.step_x:
        prior = optional_grid_reference.step_x
        if step is None or abs(step / prior - 1) <= .08:
            step = prior if step is None else (step + prior) / 2
    if step is None:
        return GridRow(((0, c, validate_card(image, c)),), None)
    # Median slope from several observed boundaries reduces cumulative drift.
    slopes = []
    for column in range(1, 8):
        predicted = c.left + column * step
        nearby = [x for x in edges if abs(x - predicted) < c.width * .12]
        if nearby:
            x = min(nearby, key=lambda x: abs(x - predicted))
            slopes.append((x - c.left) / column)
    if slopes:
        refined = float(np.median(slopes))
        radius = max(1, round(c.width * .01))
        def alignment(period):
            score = 0.
            for column in range(8):
                for side in (0, c.width):
                    x = round(column * period) + side
                    if x < len(projection):
                        score += float(projection[max(0, x - radius):x + radius + 1].max())
            return score
        # A nearby artwork peak must not make the whole-row alignment worse.
        if alignment(refined) >= alignment(step):
            step = refined
    positions = []
    for column in range(8):
        x = round(c.left + column * step)
        if x + c.width >= w:
            break
        positions.append((column, x))
    # Glow can make the baseline choose a nearby horizontal response. Compare
    # observed ends in a narrow neighborhood using evidence from the whole row;
    # never derive a bottom from top + expected height.
    radius = max(2, round(c.width * .06))
    bottoms = {c.bottom}
    for _, x in positions:
        bottoms.update(_horizontal_edges(image, x, x + c.width,
                                         c.bottom - radius, c.bottom + radius + 1))
    best_cards, best_score = (), (-1, -float('inf'))
    for bottom in sorted(bottoms):
        cards = []
        for column, x in positions:
            candidate = Candidate(x, x + c.width, c.top, bottom, c.top, bottom)
            result = validate_card(image, candidate, c)
            if result.valid:
                cards.append((column, candidate, result))
        # Keep column zero as the measured row baseline; avoid a correction that
        # gains other cards by discarding the reference card itself.
        if not cards or cards[0][0] != 0:
            continue
        score = (len(cards), sum(v.support[3] for _, _, v in cards)
                 - abs(bottom - c.bottom) / c.width)
        if score > best_score:
            best_cards, best_score = tuple(cards), score
    return GridRow(best_cards, step)
