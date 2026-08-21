import math
from collections import Counter

from . import auto_inference as base


def room_counts_from_files(files):
    """Count repeated room labels using their coordinates when available.

    Architectural plans commonly repeat the same text (e.g. «اتاق خواب») for
    multiple rooms. The v1 text-only dedupe collapsed these into one room. This
    version preserves distinct labels and only removes near-coincident duplicates.
    """
    counts = Counter()
    for f in files or []:
        labels = f.get('text_labels') or []
        if labels:
            accepted = []
            for item in labels:
                text = item.get('text') or ''
                room = base.classify_room(text)
                if not room:
                    continue
                try:
                    p = (float(item.get('x')), float(item.get('y')))
                except (TypeError, ValueError):
                    p = None
                duplicate = False
                if p:
                    for old_room, old_p in accepted:
                        if old_room == room and math.dist(p, old_p) < 80:
                            duplicate = True
                            break
                if not duplicate:
                    counts[room] += 1
                    if p:
                        accepted.append((room, p))
            continue

        # Fallback for older analysis payloads without coordinates: count each
        # recognized label occurrence. This is preferable to collapsing all
        # identical room names into a single room.
        for text in f.get('texts') or []:
            room = base.classify_room(text)
            if room:
                counts[room] += 1
    return dict(counts)


def _plausible_area_from_file(f):
    """Use bounding area only when dimensions look like a real building floor.

    This rejects common CAD title blocks / multi-plan modelspace extents that can
    otherwise inflate thermal and electrical estimates.
    """
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


# Patch v1's global helpers so all existing inference functions use the improved logic.
base.room_counts_from_files = room_counts_from_files
base._plausible_area_from_file = _plausible_area_from_file

INSUNITS_TO_M = base.INSUNITS_TO_M
infer_architecture_facts = base.infer_architecture_facts
canonical_auto_answers = base.canonical_auto_answers
dynamic_questions = base.dynamic_questions
auto_summary = base.auto_summary
classify_room = base.classify_room
