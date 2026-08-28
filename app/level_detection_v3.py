"""Guarded multi-evidence architectural level detection.

This module wraps the existing v2 inference instead of replacing it. It keeps
proven v2 room/typical logic, restores architecturally explicit levels that v2
would otherwise drop for lack of room labels, and keeps weak/orphan titles as
non-active candidates. This prevents missing mezzanines while avoiding the old
phantom-level regression from reusable title blocks.
"""
import math
import re
from collections import defaultdict

from . import auto_inference_v2 as v2

LEVEL_DETECTION_VERSION = "multi-evidence-v3.4"


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip()


def _explicit_level_title(text):
    s = _norm(text)
    if "پلان" in s and "معماری" in s and ("نیم طبقه" in s or "نیم‌طبقه" in s):
        level = _norm(s.replace("پلان", " ").replace("معماری", " ")).replace("نیم‌طبقه", "نیم طبقه")
        if level:
            return level, "architectural-plan-title"
    parsed = v2._plan_title(text)
    if parsed and parsed[0] == "architecture":
        return parsed[1], "architectural-plan-title"
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
        ("نیم طبقه", "نیم طبقه"), ("نیم‌طبقه", "نیم طبقه"),
        ("زیرزمین", "زیرزمین"), ("همکف", "طبقه همکف"), ("خرپشته", "خرپشته"),
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
    """Collect explicit levels and attach only room evidence owned by that title."""
    rows = []
    for file_info in files or []:
        labels = file_info.get("text_labels") or []
        title_rows = []
        for item in labels:
            parsed = _explicit_level_title(item.get("text") or "")
            if not parsed:
                continue
            level, basis = parsed
            title_rows.append({
                "name": _norm(level), "basis": basis,
                "source_type": item.get("source_type"), "source_name": item.get("source_name"),
                "title_text": _norm(item.get("text")),
                "title_point": [item.get("x"), item.get("y")],
            })
        room_rows = [item for item in labels if v2.classify_room(item.get("text") or "")]
        for title in title_rows:
            source_key = (title["source_type"], title["source_name"])
            competing = [other for other in title_rows if (other["source_type"], other["source_name"]) == source_key]
            owned_rooms = 0
            for room in room_rows:
                if (room.get("source_type"), room.get("source_name")) != source_key:
                    continue
                rp = (room.get("x"), room.get("y"))
                nearest = min(competing, key=lambda other: _distance(rp, other["title_point"])) if competing else title
                if nearest is title:
                    owned_rooms += 1
            source_type = title["source_type"]
            if source_type == "layout":
                confidence = 0.96 if owned_rooms else 0.88; active = True
            elif owned_rooms >= 2:
                confidence = 0.86; active = True
            elif owned_rooms == 1:
                confidence = 0.72; active = True
            else:
                confidence = 0.42; active = False
            rows.append({**title, "confidence": confidence, "active": active, "nearby_room_labels": owned_rooms})
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
        "name": name, "title_point": candidate.get("title_point"),
        "source_type": candidate.get("source_type"), "source_name": candidate.get("source_name"),
        "room_counts": {}, "recognized_room_labels": 0,
        "wet_fixture_candidate": False, "sanitary_candidate": False,
        "conditioned_candidate": not is_roof, "ventilation_candidate": False,
        "gas_candidate": False, "roof": is_roof, "typical_signature": None,
        "typical_confidence": "insufficient", "level_confidence": candidate["confidence"],
        "level_evidence": [candidate["basis"], candidate.get("source_type") or "unknown-source"],
        "level_detection_status": "confirmed-from-explicit-title",
    }


def _mark_title_only_restorations(profiles, candidates, restored):
    """Fail-safe provenance pass for explicit active levels with no owned rooms."""
    by_name = {str(p.get("name")): p for p in profiles if p.get("name")}
    for candidate in candidates:
        if not candidate.get("active") or int(candidate.get("nearby_room_labels") or 0) != 0:
            continue
        name = candidate["name"]
        if name not in restored:
            restored.append(name)
        profile = by_name.get(name)
        if profile is None:
            profile = _placeholder_profile(candidate)
            profiles.append(profile); by_name[name] = profile
        profile["typical_signature"] = None
        profile["typical_confidence"] = "insufficient"
        profile["level_confidence"] = max(float(profile.get("level_confidence") or 0), float(candidate["confidence"]))
        profile["level_detection_status"] = "confirmed-from-explicit-title"
        evidence = list(profile.get("level_evidence") or [])
        for item in (candidate["basis"], candidate.get("source_type") or "unknown-source"):
            if item not in evidence:
                evidence.append(item)
        profile["level_evidence"] = evidence
    return profiles, restored


def infer_architecture_facts(analysis, discipline):
    auto = v2.infer_architecture_facts(analysis, discipline)
    candidates = _collect_candidates((analysis or {}).get("files") or [])
    profiles = [dict(p) for p in (auto.get("level_profiles") or [])]
    profile_map = {str(p.get("name")): p for p in profiles if p.get("name")}
    restored = []

    for profile in profiles:
        candidate = next((c for c in candidates if c["name"] == profile.get("name")), None)
        evidence = ["room-pattern-v2"]
        if candidate:
            evidence.append(candidate["basis"])
            profile["level_confidence"] = max(0.95, candidate["confidence"])
            if candidate.get("active") and int(candidate.get("nearby_room_labels") or 0) == 0:
                profile["typical_signature"] = None
                profile["typical_confidence"] = "insufficient"
                profile["level_detection_status"] = "confirmed-from-explicit-title"
                restored.append(candidate["name"])
            else:
                profile["level_detection_status"] = "confirmed"
        else:
            profile["level_confidence"] = 0.90 if profile.get("recognized_room_labels") else 0.65
            profile["level_detection_status"] = "confirmed"
        profile["level_evidence"] = evidence

    weak = []
    for candidate in candidates:
        if candidate["name"] in profile_map:
            continue
        if candidate["active"]:
            new_profile = _placeholder_profile(candidate)
            profiles.append(new_profile); profile_map[candidate["name"]] = new_profile
            if int(candidate.get("nearby_room_labels") or 0) == 0:
                restored.append(candidate["name"])
        else:
            weak.append(candidate)

    profiles, restored = _mark_title_only_restorations(profiles, candidates, restored)
    restored = list(dict.fromkeys(restored))
    if profiles:
        auto["level_profiles"] = profiles
        auto["levels"] = [{"name": p["name"], "confidence": p.get("level_confidence")} for p in profiles]
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
    if getattr(main_auto_module, "_level_detection_v3_installed", False):
        return
    main_auto_module.infer_architecture_facts = infer_architecture_facts
    main_auto_module._level_detection_v3_installed = True
