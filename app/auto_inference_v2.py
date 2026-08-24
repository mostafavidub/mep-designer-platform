import math
import re
import statistics
from collections import Counter, defaultdict

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
    # Common authority-drawing titles that do not literally say
    # "architectural plan" still define real levels.
    if 'roof plan' in low or 'پلان شیب' in s or 'پلان شيب' in s:
        return 'architecture', 'بام'
    generic = re.search(r'\b(ground|first|second|third|fourth|fifth)\s+floor\s+plan\b', low)
    if generic:
        names = {'ground': 'طبقه همکف', 'first': 'طبقه اول', 'second': 'طبقه دوم',
                 'third': 'طبقه سوم', 'fourth': 'طبقه چهارم', 'fifth': 'طبقه پنجم'}
        return 'architecture', names[generic.group(1)]
    for kind, prefixes in _PLAN_PREFIXES:
        for prefix in prefixes:
            pos = low.find(prefix.lower())
            if pos >= 0:
                level = _norm(s[:pos] + s[pos + len(prefix):]) or 'unspecified'
                return kind, level
    return None


def _expand_combined_levels(level):
    """Expand a shared title such as 'طبقه اول و دوم' into real levels."""
    value = _norm(level)
    match = re.fullmatch(r'(?:طبقه\s*)?([^\s]+)\s*و\s*(?:طبقه\s*)?([^\s]+)', value)
    if not match:
        return [value]
    first, second = match.groups()
    ordinals = ('اول', 'دوم', 'سوم', 'چهارم', 'پنجم', 'ششم')
    if first in ordinals and second in ordinals:
        return [f'طبقه {first}', f'طبقه {second}']
    return [value]


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
        titles.append({
            'type': parsed[0], 'level': parsed[1], 'point': p,
            'source_type': item.get('source_type'),
            'source_name': item.get('source_name'),
        })
    arch = [x for x in titles if x['type'] == 'architecture']
    # A generic combined title ("طبقه اول و دوم") is often retained in a
    # title block next to more specific architectural panels. Keep it only
    # when it contributes at least one otherwise-unrepresented floor; this
    # prevents a duplex's named first/second plans from acquiring a phantom
    # fourth effective plan.
    specific_levels = {
        x['level'] for x in arch
        if len(_expand_combined_levels(x['level'])) == 1
    }
    arch = [
        x for x in arch
        if len(_expand_combined_levels(x['level'])) == 1
        or any(member not in specific_levels for member in _expand_combined_levels(x['level']))
    ]
    if not arch:
        return titles, []
    # Assign rooms only against architectural titles; nearby furniture or lintel plans must not steal them.
    titles = arch
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


def _room_items_with_source(labels):
    out = []
    for item in labels:
        room = base.classify_room(item.get('text') or '')
        if not room:
            continue
        try:
            point = (float(item.get('x')), float(item.get('y')))
        except (TypeError, ValueError):
            continue
        out.append((room, point, item.get('source_type'), item.get('source_name')))
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
    for room, p, source_type, source_name in _room_items_with_source(labels):
        same_source = [
            x for x in titles
            if x.get('source_type') == source_type and x.get('source_name') == source_name
        ]
        title = min(same_source or titles, key=lambda x: math.dist(p, x['point']))
        if math.dist(p, title['point']) > title_spacing * 1.65:
            continue
        key = (title['type'], title['level'], title['point'])
        if key not in selected_keys:
            continue
        local_pts = [q for old_room, q, old_key in seen if old_key == key and old_room == room]
        tol = max(.015, min(.35, title_spacing * .015))
        if any(math.dist(p, q) <= tol for q in local_pts):
            continue
        counts[room] += 1
        seen.append((room, p, key))
    return counts if counts else None


def room_counts_from_files(files):
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


def _level_profiles_from_file(f):
    """Build translation-invariant, conservative per-level architecture profiles."""
    labels = f.get('text_labels') or []
    titles, selected = _selected_architecture_titles(labels)
    if not selected or not titles:
        return []
    title_points = [x['point'] for x in titles]
    nearest = _nearest_distances(title_points)
    spacing = max(statistics.median(nearest) if nearest else 25.0, 1.0)
    selected_keys = {(x['type'], x['level'], x['point']) for x in selected}
    assigned = defaultdict(list)
    for room, p, source_type, source_name in _room_items_with_source(labels):
        if not p:
            continue
        same_source = [
            x for x in titles
            if x.get('source_type') == source_type and x.get('source_name') == source_name
        ]
        # A room label may only define the level of a title from the same CAD
        # container.  Cross-assigning a modelspace room to an orphan library
        # block is the root cause of phantom levels and repeated project
        # geometry.
        title = min(same_source or titles, key=lambda x: math.dist(p, x['point']))
        key = (title['type'], title['level'], title['point'])
        if key not in selected_keys or math.dist(p, title['point']) > spacing * 1.65:
            continue
        assigned[key].append((room, p))

    profiles = []
    for title in selected:
        key = (title['type'], title['level'], title['point'])
        raw = assigned.get(key, [])
        # Near-coincident duplicate labels are removed, but repeated rooms remain.
        tol = max(.015, min(.35, spacing * .015))
        accepted = []
        for room, point in raw:
            if any(room == old_room and math.dist(point, old_point) <= tol for old_room, old_point in accepted):
                continue
            accepted.append((room, point))
        counts = Counter(room for room, _ in accepted)
        wet = sum(counts[x] for x in ('kitchen', 'bath', 'toilet'))
        conditioned = sum(counts[x] for x in ('bedroom', 'living', 'office', 'shop'))
        ventilation = sum(counts[x] for x in ('kitchen', 'bath', 'toilet', 'parking'))
        gas_candidate = counts.get('kitchen', 0) > 0
        is_roof = 'بام' in title['level'] or 'roof' in title['level'].lower() or counts.get('roof', 0) > 0

        # Typical signature: room-type multiset plus relative arrangement. The
        # geometry is normalized to its own room-label envelope, making the
        # signature independent of where each plan is drawn in modelspace.
        signature = None
        confidence = 'insufficient'
        if len(accepted) >= 3:
            xs = [p[0] for _, p in accepted]; ys = [p[1] for _, p in accepted]
            minx, maxx = min(xs), max(xs); miny, maxy = min(ys), max(ys)
            width = max(maxx - minx, tol); height = max(maxy - miny, tol)
            normalized = sorted(
                (room, round((p[0] - minx) / width, 2), round((p[1] - miny) / height, 2))
                for room, p in accepted
            )
            signature = (
                tuple(sorted(counts.items())),
                tuple(normalized),
                bool(counts.get('shaft')),
            )
            confidence = 'high'
        profile = {
            'name': title['level'],
            'title_point': [float(title['point'][0]), float(title['point'][1])],
            'source_type': title.get('source_type'),
            'source_name': title.get('source_name'),
            'room_counts': dict(counts),
            'recognized_room_labels': len(accepted),
            'wet_fixture_candidate': wet > 0,
            'sanitary_candidate': wet > 0,
            'conditioned_candidate': conditioned > 0 and not is_roof,
            'ventilation_candidate': ventilation > 0,
            'gas_candidate': gas_candidate and not is_roof,
            'roof': is_roof,
            'typical_signature': signature,
            'typical_confidence': confidence,
        }
        for expanded_name in _expand_combined_levels(title['level']):
            expanded = dict(profile)
            expanded['name'] = expanded_name
            profiles.append(expanded)
    # A title alone is not a level. Exported CAD templates frequently retain
    # orphan sample floor titles far from every architectural room. Once the
    # file provides spatial room evidence for any level, discard zero-evidence
    # non-roof titles instead of multiplying the proposal by phantom floors.
    if any(p.get('recognized_room_labels', 0) > 0 for p in profiles):
        profiles = [
            p for p in profiles
            if p.get('recognized_room_labels', 0) > 0 or p.get('roof')
        ]
    return profiles


def level_profiles_from_files(files):
    profiles = []
    seen = set()
    for f in files or []:
        for profile in _level_profiles_from_file(f):
            if profile['name'] in seen:
                continue
            seen.add(profile['name'])
            profiles.append(profile)
    return profiles


def explicit_typical_groups_from_files(files):
    """Honor one architectural plan title explicitly shared by multiple floors."""
    groups = []
    seen = set()
    for file_info in files or []:
        for item in file_info.get('text_labels') or []:
            parsed = _plan_title(item.get('text') or '')
            if not parsed or parsed[0] != 'architecture':
                continue
            members = _expand_combined_levels(parsed[1])
            if len(members) < 2:
                continue
            key = tuple(members)
            if key in seen:
                continue
            seen.add(key)
            groups.append({
                'name': 'Typical: ' + ' / '.join(members),
                'levels': members,
                'confidence': 'high',
                'basis': 'explicit shared architectural plan title',
            })
    return groups


def typical_groups_from_profiles(profiles):
    """Group only high-confidence identical architectural floor patterns."""
    buckets = defaultdict(list)
    for profile in profiles or []:
        signature = profile.get('typical_signature')
        if signature is not None and profile.get('typical_confidence') == 'high' and not profile.get('roof'):
            buckets[repr(signature)].append(profile['name'])
    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        groups.append({
            'name': 'Typical: ' + ' / '.join(members),
            'levels': members,
            'confidence': 'high',
            'basis': 'room-type counts + translation-invariant room/shaft arrangement',
        })
    return groups


def _plausible_area_from_file(f):
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


base.room_counts_from_files = room_counts_from_files
base._plausible_area_from_file = _plausible_area_from_file

INSUNITS_TO_M = base.INSUNITS_TO_M
canonical_auto_answers = base.canonical_auto_answers
dynamic_questions = base.dynamic_questions
auto_summary = base.auto_summary
classify_room = base.classify_room


def infer_architecture_facts(analysis, discipline):
    auto = base.infer_architecture_facts(analysis, discipline)
    profiles = level_profiles_from_files((analysis or {}).get('files') or [])
    if profiles:
        auto['levels'] = [{'name': p['name']} for p in profiles]
        auto['level_profiles'] = profiles
        inferred_groups = typical_groups_from_profiles(profiles)
        explicit_groups = explicit_typical_groups_from_files((analysis or {}).get('files') or [])
        explicit_members = {tuple(group['levels']) for group in explicit_groups}
        auto['typical_groups'] = explicit_groups + [
            group for group in inferred_groups if tuple(group['levels']) not in explicit_members
        ]
        auto['effective_level_inference'] = 'per-level-room-pattern-v3'
    else:
        auto['level_profiles'] = []
        auto['typical_groups'] = []
        auto['effective_level_inference'] = 'fallback-no-level-profile'
    files = (analysis or {}).get('files') or []
    fixture_counts = Counter()
    for file_info in files:
        fixture_counts.update(file_info.get('fixture_counts') or {})
    auto['fixture_counts'] = dict(fixture_counts)
    auto['fixture_blocks_detected'] = sum(fixture_counts.values())
    auto['roof_drain_count'] = sum(int(x.get('roof_drain_count') or 0) for x in files)
    auto['roof_area_m2'] = auto.get('geometry_area_m2') if any(p.get('roof') for p in profiles) else None
    roof_profiles = [p for p in profiles if p.get('roof')]
    occupied_keys = ('kitchen', 'bedroom', 'living', 'office', 'shop')
    dedicated_roof_profile = any(
        not any(int((p.get('room_counts') or {}).get(key) or 0) for key in occupied_keys)
        for p in roof_profiles
    )
    # A title containing "roof" is not sufficient evidence for a dedicated
    # roof deliverable. Consultant DXFs often reuse one named block for all
    # titles; in that case rooms from an occupied floor can be assigned to the
    # roof title and incorrectly add two sheets. A real roof drain marker or a
    # roof-only profile is required before the planner creates roof scope.
    auto['roof_scope_reliable'] = bool(roof_profiles) and bool(
        auto['roof_drain_count'] or dedicated_roof_profile
    )
    if roof_profiles and not auto['roof_scope_reliable']:
        auto['roof_area_m2'] = None
        auto.setdefault('assumptions', []).append(
            'Roof title was rejected as a dedicated mechanical level because it reused occupied-floor content and had no roof-drain evidence.'
        )
    return auto
