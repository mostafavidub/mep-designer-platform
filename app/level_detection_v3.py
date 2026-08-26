"""Guarded multi-evidence architectural level detection.

This module wraps the existing v2 inference instead of replacing it.  It keeps
proven v2 room/typical logic, restores architecturally explicit levels that v2
would otherwise drop for lack of room labels, and keeps weak/orphan titles as
non-active candidates.  This prevents missing mezzanines while avoiding the
old phantom-level regression from reusable title blocks.
"""
import math
import re
from collections import defaultdict

from . import auto_inference_v2 as v2

LEVEL_DETECTION_VERSION = "multi-evidence-v3.0"


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip()


def _explicit_level_title(text):
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


def _collect_candidates(files):
    rows = []
    for file_info in files or []:
        labels = file_info.get("text_labels") or []
        by_source_rooms = defaultdict(list)
        for item in labels:
            if v2.classify_room(item.get("text") or ""):
                by_source_rooms[(item.get("source_type"), item.get("source_name"))].append((item.get("x"), item.get("y")))
        for item in labels:
            parsed = _explicit_level_title(item.get("text") or "")
            if not parsed:
                continue
            level, basis = parsed
            point = (item.get("x"), item.get("y"))
            source_key = (item.get("source_type"), item.get("source_name"))
            same_source_rooms = by_source_rooms.get(source_key) or []
            nearby = sum(1 for p in same_source_rooms if _distance(point, p) < 100.0)
            source_type = item.get("source_type")
            # Layout/model evidence is strong because main_auto has already
            # filtered incoherent CAD sources. A named block needs room evidence
            # before it can become active; otherwise it remains a candidate.
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
                "title_text": _norm(item.get("text")),
                "title_point": [point[0], point[1]],
                "nearby_room_labels": nearby,
            })
    # Merge duplicates conservatively, retaining the strongest evidence.
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
        "room_counts": {},
        "recognized_room_labels": 0,
        # Unknown room labels must not suppress an explicit occupied level.
        # Planner's authority-safe fallback already scopes non-roof profiles
        # conservatively, while answers can explicitly disable systems.
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


def infer_architecture_facts(analysis, discipline):
    auto = v2.infer_architecture_facts(analysis, discipline)
    candidates = _collect_candidates((analysis or {}).get("files") or [])
    profiles = [dict(p) for p in (auto.get("level_profiles") or [])]
    profile_map = {str(p.get("name")): p for p in profiles if p.get("name")}

    for profile in profiles:
        candidate = next((c for c in candidates if c["name"] == profile.get("name")), None)
        evidence = ["room-pattern-v2"]
        if candidate:
            evidence.append(candidate["basis"])
            profile["level_confidence"] = max(0.95, candidate["confidence"])
        else:
            profile["level_confidence"] = 0.90 if profile.get("recognized_room_labels") else 0.65
        profile["level_evidence"] = evidence
        profile["level_detection_status"] = "confirmed"

    restored = []
    weak = []
    for candidate in candidates:
        if candidate["name"] in profile_map:
            continue
        if candidate["active"]:
            new_profile = _placeholder_profile(candidate)
            profiles.append(new_profile)
            profile_map[candidate["name"]] = new_profile
            restored.append(candidate["name"])
        else:
            weak.append(candidate)

    if profiles:
        auto["level_profiles"] = profiles
        auto["levels"] = [{"name": p["name"], "confidence": p.get("level_confidence")} for p in profiles]
        # Typical groups are intentionally recalculated only from profiles with
        # actual high-confidence geometry/room signatures. Restored title-only
        # levels can never become Typical by accident.
        inferred = v2.typical_groups_from_profiles(profiles)
        explicit = v2.explicit_typical_groups_from_files((analysis or {}).get("files") or [])
        explicit_keys = {tuple(x.get("levels") or []) for x in explicit}
        auto["typical_groups"] = explicit + [x for x in inferred if tuple(x.get("levels") or []) not in explicit_keys]

    auto["candidate_levels"] = weak
    auto["restored_explicit_levels"] = restored
    auto["level_detection_version"] = LEVEL_DETECTION_VERSION
    auto["effective_level_inference"] = "multi-evidence-level-v3"
    diagnostics = list(auto.get("level_detection_diagnostics") or [])
    if restored:
        diagnostics.append("explicit_levels_restored_without_room_labels")
    if weak:
        diagnostics.append("weak_level_titles_retained_as_candidates")
    auto["level_detection_diagnostics"] = list(dict.fromkeys(diagnostics))
    return auto


def install(main_auto_module):
    """Patch only the inference binding used by project analysis."""
    if getattr(main_auto_module, "_level_detection_v3_installed", False):
        return
    main_auto_module.infer_architecture_facts = infer_architecture_facts
    main_auto_module._level_detection_v3_installed = True
