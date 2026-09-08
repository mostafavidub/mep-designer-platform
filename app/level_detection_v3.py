"""Guarded multi-evidence architectural level detection.

This module wraps the existing v2 inference instead of replacing it. It keeps
proven room/typical logic, but only occupied-floor/roof evidence may become an
active level. Detail, section, elevation, parking, slope, lintel and similar
support drawings are retained as diagnostics and can never become a floor.
"""
import hashlib
import math
import re
from collections import defaultdict

from . import auto_inference_v2 as v2

LEVEL_DETECTION_VERSION = "multi-evidence-v3.2"

NON_LEVEL_MARKERS = (
    "detail", "دیتیل", "section", "مقطع", "elevation", "نما",
    "parking", "پارکینگ", "slope", "شیب", "شيب", "lintel", "نعل درگاه",
    "door plan", "window plan", "پلان در", "پلان پنجره", "کف سازی", "کفسازی",
)


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip()


def _non_level_title(text):
    s = _norm(text)
    low = s.lower()
    return any(marker in low for marker in NON_LEVEL_MARKERS)


def _explicit_level_title(text):
    # Semantic role is checked before the legacy parser. In particular, a
    # generic Persian slope-plan title used to be promoted to ROOF by v2.
    if _non_level_title(text):
        return None
    parsed = v2._plan_title(text)
    if parsed and parsed[0] == "architecture":
        return parsed[1], "architectural-plan-title"
    s = _norm(text)
    low = s.lower()
    patterns = (
        (r"\bmezzanine(?:\s+floor)?(?:\s+plan)?\b", "نیم طبقه"),
        (r"\bbasement(?:\s+floor)?(?:\s+plan)?\b", "زیرزمین"),
        (r"\bground(?:\s+floor)?(?:\s+plan)?\b", "طبقه همکف"),
        (r"\bpenthouse(?:\s+plan)?\b", "خرپشته"),
    )
    for pattern, name in patterns:
        if re.search(pattern, low):
            return name, "recognized-level-title"
    fa = (
        ("نیم طبقه", "نیم طبقه"),
        ("نیم‌طبقه", "نیم طبقه"),
        ("زیرزمین", "زیرزمین"),
        ("همکف", "طبقه همکف"),
        ("خرپشته", "خرپشته"),
    )
    if "پلان" in s:
        for marker, name in fa:
            if marker in s:
                return name, "recognized-level-title"
    return None


def _distance(a, b):
    try:
        return math.dist((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
    except Exception:
        return 10**12


def _collect_rejected_titles(files):
    rows = []
    for file_info in files or []:
        for item in file_info.get("text_labels") or []:
            text = _norm(item.get("text") or "")
            if not _non_level_title(text):
                continue
            rows.append({
                "text": text,
                "source_type": item.get("source_type"),
                "source_name": item.get("source_name"),
                "point": [item.get("x"), item.get("y")],
                "role": "NON_LEVEL_SUPPORT_DRAWING",
            })
    return rows


def _collect_candidates(files):
    rows = []
    for file_info in files or []:
        labels = file_info.get("text_labels") or []
        source_file = str(file_info.get("file") or "")
        title_points = defaultdict(list)
        for title_item in labels:
            if _explicit_level_title(title_item.get("text") or ""):
                title_points[(title_item.get("source_type"), title_item.get("source_name"))].append(
                    (title_item.get("x"), title_item.get("y"))
                )
        by_source_rooms = defaultdict(list)
        for item in labels:
            if not _explicit_level_title(item.get("text") or "") and v2.classify_room(item.get("text") or ""):
                by_source_rooms[(item.get("source_type"), item.get("source_name"))].append((item.get("x"), item.get("y")))
        for item in labels:
            parsed = _explicit_level_title(item.get("text") or "")
            if not parsed:
                continue
            level, basis = parsed
            point = (item.get("x"), item.get("y"))
            source_key = (item.get("source_type"), item.get("source_name"))
            same_source_rooms = by_source_rooms.get(source_key) or []
            source_titles = title_points.get(source_key) or [point]
            nearby = sum(
                1 for p in same_source_rooms
                if _distance(point, p) < 100.0
                and _distance(point, p) <= min(_distance(other, p) for other in source_titles)
            )
            source_type = item.get("source_type")
            if source_type == "layout":
                confidence = 0.96 if nearby else 0.88
                active = True
            elif nearby >= 2:
                confidence = 0.86
                active = True
            elif nearby == 1:
                confidence = 0.72
                active = True
            else:
                confidence = 0.42
                active = False
            rows.append({
                "name": _norm(level),
                "confidence": confidence,
                "active": active,
                "basis": basis,
                "source_type": source_type,
                "source_name": item.get("source_name"),
                "source_file": source_file,
                "title_text": _norm(item.get("text")),
                "title_point": [point[0], point[1]],
                "nearby_room_labels": nearby,
            })
    merged = {}
    for row in rows:
        old = merged.get(row["name"])
        if old is None or row["confidence"] > old["confidence"]:
            merged[row["name"]] = row
    return list(merged.values())


def _placeholder_profile(candidate):
    name = candidate["name"]
    is_roof = "بام" in name or "roof" in name.lower()
    return {
        "name": name,
        "title_point": candidate.get("title_point"),
        "source_type": candidate.get("source_type"),
        "source_name": candidate.get("source_name"),
        "source_file": candidate.get("source_file"),
        "room_counts": {},
        "recognized_room_labels": 0,
        "wet_fixture_candidate": False,
        "sanitary_candidate": False,
        "conditioned_candidate": not is_roof,
        "ventilation_candidate": False,
        "gas_candidate": False,
        "roof": is_roof,
        "typical_signature": None,
        "typical_confidence": "insufficient",
        "level_confidence": candidate["confidence"],
        "level_evidence": [candidate["basis"], candidate.get("source_type") or "unknown-source"],
        "level_detection_status": "confirmed-from-explicit-title",
    }



def _authority_id(profile):
    point = profile.get("title_point") or [None, None]
    payload = "|".join((
        _norm(profile.get("source_file")),
        _norm(profile.get("source_type")),
        _norm(profile.get("source_name")),
        _norm(profile.get("name")),
        str(point[0] if len(point) > 0 else ""),
        str(point[1] if len(point) > 1 else ""),
    ))
    return "LVL-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12].upper()

def infer_architecture_facts(analysis, discipline):
    auto = v2.infer_architecture_facts(analysis, discipline)
    files = (analysis or {}).get("files") or []
    candidates = _collect_candidates(files)
    rejected_titles = _collect_rejected_titles(files)
    safe_names = {candidate["name"] for candidate in candidates}
    roof_drain_evidence = any((file_info.get("roof_drain_count") or 0) > 0 for file_info in files)

    profiles = []
    rejected_profiles = []
    for raw in auto.get("level_profiles") or []:
        profile = dict(raw)
        name = _norm(profile.get("name"))
        # Reject any semantic support-drawing name that leaked through the
        # legacy inference. A roof created only from a generic slope-plan title
        # is also removed unless separate roof-drain evidence exists.
        if _non_level_title(name):
            rejected_profiles.append(name)
            continue
        if profile.get("roof") and name not in safe_names and not roof_drain_evidence:
            rejected_profiles.append(name or "بام")
            continue
        profiles.append(profile)

    restored = []
    profile_map = {str(p.get("name")): p for p in profiles if p.get("name")}

    for profile in profiles:
        candidate = next((c for c in candidates if c["name"] == profile.get("name")), None)
        evidence = ["room-pattern-v2"]
        if candidate:
            evidence.append(candidate["basis"])
            profile["level_confidence"] = max(0.95, candidate["confidence"])
            profile["source_file"] = candidate.get("source_file") or profile.get("source_file")
            profile["source_type"] = candidate.get("source_type") or profile.get("source_type")
            profile["source_name"] = candidate.get("source_name") or profile.get("source_name")
            if candidate.get("nearby_room_labels", 0) == 0:
                profile["level_detection_status"] = "confirmed-from-explicit-title"
                restored.append(candidate["name"])
        else:
            profile["level_confidence"] = 0.90 if profile.get("recognized_room_labels") else 0.65
        profile["level_evidence"] = evidence
        profile.setdefault("level_detection_status", "confirmed")
        profile["level_authority_id"] = _authority_id(profile)

    weak = []
    for candidate in candidates:
        if candidate["name"] in profile_map:
            continue
        if candidate["active"]:
            new_profile = _placeholder_profile(candidate)
            new_profile["level_authority_id"] = _authority_id(new_profile)
            profiles.append(new_profile)
            profile_map[candidate["name"]] = new_profile
            restored.append(candidate["name"])
        else:
            weak.append(candidate)

    if profiles:
        auto["level_profiles"] = profiles
        auto["levels"] = [{"name": p["name"], "confidence": p.get("level_confidence")} for p in profiles]
        inferred = v2.typical_groups_from_profiles(profiles)
        explicit = [
            group for group in v2.explicit_typical_groups_from_files(files)
            if all(not _non_level_title(member) for member in (group.get("levels") or []))
        ]
        explicit_keys = {tuple(x.get("levels") or []) for x in explicit}
        auto["typical_groups"] = explicit + [x for x in inferred if tuple(x.get("levels") or []) not in explicit_keys]
    else:
        auto["level_profiles"] = []
        auto["levels"] = []
        auto["typical_groups"] = []

    auto["candidate_levels"] = weak
    auto["restored_explicit_levels"] = restored
    auto["rejected_non_level_titles"] = rejected_titles
    auto["rejected_legacy_level_profiles"] = sorted(set(filter(None, rejected_profiles)))
    auto["level_detection_version"] = LEVEL_DETECTION_VERSION
    auto["effective_level_inference"] = "multi-evidence-level-v3"
    diagnostics = list(auto.get("level_detection_diagnostics") or [])
    if restored:
        diagnostics.append("explicit_levels_restored_without_room_labels")
    if weak:
        diagnostics.append("weak_level_titles_retained_as_candidates")
    if rejected_titles or rejected_profiles:
        diagnostics.append("non_level_support_drawings_rejected_from_level_authority")
    auto["level_detection_diagnostics"] = list(dict.fromkeys(diagnostics))
    return auto


def install(main_auto_module):
    """Patch only the inference binding used by project analysis."""
    if getattr(main_auto_module, "_level_detection_v3_installed", False):
        return
    main_auto_module.infer_architecture_facts = infer_architecture_facts
    main_auto_module._level_detection_v3_installed = True
