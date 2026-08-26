"""Analyzer-to-CAD level geometry bridge for mechanical v11.

The architecture analyzer can preserve a real level (for example a mezzanine)
from strong title/source evidence even when the legacy CAD level builder cannot
classify that title.  The approved manifest is produced from analyzer evidence,
so CAD must consume the same active level set instead of failing on a name that
was already approved.

This module augments, never replaces, legacy CAD levels.  Only analyzer-approved
level_profiles with a valid title point are materialized.  No orphan/candidate
title is promoted here.
"""
from contextvars import ContextVar
import math
import re

_current_calc = ContextVar('engitools_mechanical_calc', default=None)


def _norm(value):
    text = str(value or '').replace('\u200c', ' ').replace('\u200f', ' ').replace('ي', 'ی').replace('ك', 'ک')
    text = re.sub(r'\s+', ' ', text).strip().lower()
    for prefix in ('پلان معماری', 'پلان معماري', 'architectural plan', 'architecture plan'):
        text = text.replace(prefix, ' ')
    return re.sub(r'\s+', '', text)


def _equivalent(a, b):
    a = _norm(a); b = _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # Manifest labels are intentionally concise (e.g. "نیم طبقه") while a
    # consultant title can be "نیم طبقه بالکن تجاری".  Prefix containment is
    # safe only after architecture-title normalization and for >=4 chars.
    return min(len(a), len(b)) >= 4 and (a in b or b in a)


def _profiles(calc):
    analysis = (calc or {}).get('_plan_analysis') or {}
    auto = analysis.get('architectural_auto') or {}
    return list(auto.get('level_profiles') or [])


def _valid_point(value):
    try:
        x, y = value[:2]
        return float(x), float(y)
    except (TypeError, ValueError, IndexError):
        return None


def augment_levels(msp, levels, calc, v8):
    """Merge analyzer-approved active levels into the legacy CAD level list."""
    profiles = _profiles(calc)
    if not profiles:
        return levels

    result = list(levels or [])
    titles = []
    for profile in profiles:
        name = str(profile.get('name') or '').strip()
        point = _valid_point(profile.get('title_point'))
        if not name or point is None:
            continue
        # level_profiles are already the analyzer's ACTIVE levels. Weak orphan
        # candidates are stored separately and never enter this list.
        titles.append({
            'type': 'architecture', 'level': name, 'point': point,
            'text': name, 'source_type': profile.get('source_type'),
            'source_name': profile.get('source_name'),
        })
    if not titles:
        return result

    existing = [str(x.get('level') or '') for x in result]
    missing = [t for t in titles if not any(_equivalent(t['level'], old) for old in existing)]
    if not missing:
        return result

    # Assign actual CAD room/fixture evidence to analyzer title points using the
    # same nearest-title algorithm as the established level engine.  A title
    # with no local symbols is still preserved with a conservative title-based
    # envelope, which is preferable to silently deleting an approved level.
    all_titles = titles
    try:
        spacing = max(v8.v6.title_spacing(all_titles), 1.0)
        rooms = v8.v6.detect_room_labels_spatial(msp)
        fixtures = v8.v6.fixture_inserts(msp)
        assigned_rooms = v8.v6.assign_nearest(rooms, all_titles, spacing * 1.65)
        assigned_fixtures = v8.v6.assign_nearest(fixtures, all_titles, spacing * 1.65)
    except Exception:
        spacing = 25.0
        assigned_rooms = {}
        assigned_fixtures = {}

    profile_by_name = {str(p.get('name') or ''): p for p in profiles}
    for title in missing:
        key = ('architecture', title['level'], title['point'])
        profile = profile_by_name.get(title['level']) or {}
        row = {
            'level': title['level'],
            'title': title,
            'rooms': [dict(x) for x in assigned_rooms.get(key, [])],
            'fixtures': [dict(x) for x in assigned_fixtures.get(key, [])],
            'provenance': 'analyzer-level-profile-bridge-v11',
            'analyzer_geometry_bridge': True,
            'analyzer_source_type': profile.get('source_type'),
            'analyzer_source_name': profile.get('source_name'),
            'analyzer_recognized_room_labels': int(profile.get('recognized_room_labels') or 0),
            'typical_confidence': profile.get('typical_confidence') or 'insufficient',
        }
        result.append(row)

    result.sort(key=lambda x: (-float(x.get('title', {}).get('point', (0, 0))[0]),
                               -float(x.get('title', {}).get('point', (0, 0))[1])))
    # Recompute one coherent vertical reference now that the recovered level is
    # part of the actual CAD level set.
    try:
        v8._apply_vertical_reference(result)
    except Exception:
        pass
    return result


def install(v10_3, v10_4, v8):
    if getattr(v10_4, '_level_geometry_v11_installed', False):
        return

    original_build = v8.build_levels_v8
    original_design = v10_4.design_dxf_v10_4

    def build_levels_with_analyzer(msp):
        levels = original_build(msp)
        calc = _current_calc.get()
        if not calc:
            return levels
        return augment_levels(msp, levels, calc, v8)

    def design_with_level_context(src, dst, discipline, systems, revision, calc):
        if discipline != 'mechanical':
            return original_design(src, dst, discipline, systems, revision, calc)
        token = _current_calc.set(calc)
        try:
            return original_design(src, dst, discipline, systems, revision, calc)
        finally:
            _current_calc.reset(token)

    v8.build_levels_v8 = build_levels_with_analyzer
    v10_4.design_dxf_v10_4 = design_with_level_context
    v10_4._level_geometry_v11_installed = True
