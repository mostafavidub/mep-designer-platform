import math
import re
import statistics
from collections import Counter

from . import auto_inference as base


_PLAN_PREFIXES = (
    ('architecture', ('پلان معماری', 'architectural plan', 'architecture plan')),
    ('furniture', ('پلان مبلمان', 'furniture plan')),
    ('lintel', ('پلان نعل درگاه', 'lintel plan')),
)


def _norm(value):
    return re.sub(r'\s+', ' ', (value or '').replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')).strip()


def _plan_title(text):
    s = _norm(text)
    low = s.lower()
    for kind, prefixes in _PLAN_PREFIXES:
        for prefix in prefixes:
            pos = low.find(prefix.lower())
            if pos >= 0:
                level = _norm(s[:pos] + s[pos + len(prefix):]) or 'unspecified'
                return kind, level
    return None


def _nearest_distances(points):
    values = []
    for i, p in enumerate(points):
        ds = [math.dist(p, q) for j, q in enumerate(points) if j != i]
        if ds:
            values.append(min(ds))
    return values


def _selected_architecture_titles(labels):
    titles = []
    for item in labels:
        parsed = _plan_title(item.get('text') or '')
        if not parsed:
            continue
        try:
            p = (float(item.get('x')), float(item.get('y')))
        except (TypeError, ValueError):
            continue
        titles.append({'type': parsed[0], 'level': parsed[1], 'point': p})
    arch = [x for x in titles if x['type'] == 'architecture']
    if not arch:
        return titles, []
    levels = list(dict.fromkeys(x['level'] for x in arch))
    selected = []
    for level in levels:
        candidates = [x for x in arch if x['level'] == level]
        other_levels = [x for x in levels if x != level]
        def score(candidate):
            if not other_levels:
                return 0.0
            total = 0.0
            for other in other_levels:
                total += min(math.dist(candidate['point'], b['point']) for b in arch if b['level'] == other)
            return total
        selected.append(min(candidates, key=score))
    return titles, selected


def _room_items(labels):
    out = []
    for item in labels:
        room = base.classify_room(item.get('text') or '')
        if not room:
            continue
        try:
            p = (float(item.get('x')), float(item.get('y')))
        except (TypeError, ValueError):
            p = None
        out.append((room, p))
    return out


def _adaptive_spatial_count(items):
    points = [p for _, p in items if p]
    nearest = _nearest_distances(points)
    median_nn = statistics.median(nearest) if nearest else 1.0
    tolerance = max(.015, min(.35, median_nn * .08))
    counts = Counter()
    accepted = []
    for room, p in items:
        if p and any(old_room == room and math.dist(p, old_p) <= tolerance for old_room, old_p in accepted):
            continue
        counts[room] += 1
        if p:
            accepted.append((room, p))
    return counts


def _level_aware_room_count(labels):
    titles, selected = _selected_architecture_titles(labels)
    if not selected or not titles:
        return None
    title_points = [x['point'] for x in titles]
    nearest = _nearest_distances(title_points)
    title_spacing = max(statistics.median(nearest) if nearest else 25.0, 1.0)
    selected_keys = {(x['type'], x['level'], x['point']) for x in selected}
    counts = Counter()
    seen = []
    for room, p in _room_items(labels):
        if not p:
            continue
        title = min(titles, key=lambda x: math.dist(p, x['point']))
        if math.dist(p, title['point']) > title_spacing * 1.65:
            continue
        key = (title['type'], title['level'], title['point'])
        if key not in selected_keys:
            continue
        # Remove only truly near-coincident duplicate room labels within the same plan.
        local_pts = [q for old_room, q, old_key in seen if old_key == key and old_room == room]
        tol = max(.015, min(.35, title_spacing * .015))
        if any(math.dist(p, q) <= tol for q in local_pts):
            continue
        counts[room] += 1
        seen.append((room, p, key))
    return counts if counts else None


def room_counts_from_files(files):
    """Count real architectural rooms by Level when plan titles exist.

    The previous fixed 80-drawing-unit dedupe collapsed distinct rooms in normal
    metre/centimetre CAD files. This implementation first isolates the primary
    architectural plan for each detected Level and excludes repeated furniture /
    lintel presentation copies. If Level titles are unavailable it falls back to
    a unit-agnostic adaptive near-coincident dedupe.
    """
    total = Counter()
    for f in files or []:
        labels = f.get('text_labels') or []
        if labels:
            level_counts = _level_aware_room_count(labels)
            if level_counts:
                total.update(level_counts)
            else:
                total.update(_adaptive_spatial_count(_room_items(labels)))
            continue
        for text in f.get('texts') or []:
            room = base.classify_room(text)
            if room:
                total[room] += 1
    return dict(total)


def _plausible_area_from_file(f):
    """Use bounding area only when dimensions look like one real building floor."""
    try:
        area = float(f.get('geometry_area_m2'))
        w = float(f.get('geometry_width_m'))
        h = float(f.get('geometry_height_m'))
    except (TypeError, ValueError):
        return None
    if not (5 <= w <= 150 and 5 <= h <= 150):
        return None
    if not (15 <= area <= 10000):
        return None
    aspect = max(w, h) / max(min(w, h), 0.001)
    if aspect > 8:
        return None
    return area


# Patch v1 globals so existing inference functions consume the improved logic.
base.room_counts_from_files = room_counts_from_files
base._plausible_area_from_file = _plausible_area_from_file

INSUNITS_TO_M = base.INSUNITS_TO_M
infer_architecture_facts = base.infer_architecture_facts
canonical_auto_answers = base.canonical_auto_answers
dynamic_questions = base.dynamic_questions
auto_summary = base.auto_summary
classify_room = base.classify_room
