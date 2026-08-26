"""Fixture & Equipment Detection v2.

Adds evidence-based multi-signal recognition on top of the existing DXF
analyzer.  The detector is conservative: weak text/layer evidence becomes a
candidate, while downstream-counted detections require stronger or corroborated
signals.  Existing analyzer output is preserved and only enriched.
"""
from collections import Counter
import math
import re

import ezdxf
from ezdxf import bbox

from .fixture_equipment_rulebook import (
    CANDIDATE_THRESHOLD,
    CORROBORATION_BONUS,
    DETECTED_THRESHOLD,
    DETECTION_VERSION,
    EQUIPMENT_ALIASES,
    EQUIPMENT_LAYER_HINTS,
    FIXTURE_ALIASES,
    FIXTURE_LAYER_HINTS,
    GENERIC_EQUIPMENT_LAYER_TOKENS,
    GENERIC_FIXTURE_LAYER_TOKENS,
    SIGNAL_SCORES,
    TEXT_ONLY_MAX_CONFIDENCE,
    WET_ROOM_TYPES,
)


def _norm(value):
    text = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    text = re.sub(r"[_./\\:-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _alias_match(value, aliases):
    s = _norm(value)
    if not s:
        return None
    best = None
    best_len = 0
    for kind, terms in aliases.items():
        for term in terms:
            t = _norm(term)
            if not t:
                continue
            # Short engineering tokens such as WC/FCU must respect token
            # boundaries; longer phrases may occur inside CAD block names.
            if len(t) <= 3 and t.isascii():
                hit = re.search(rf"(?:^|\s){re.escape(t)}(?:$|\s|\d)", s)
            else:
                hit = t in s
            if hit and len(t) > best_len:
                best = kind
                best_len = len(t)
    return best


def _layer_match(layer, hints):
    return _alias_match(layer, hints)


def _point(entity):
    try:
        p = entity.dxf.insert
        return float(p.x), float(p.y)
    except Exception:
        return None


def _text(entity):
    try:
        if entity.dxftype() == "TEXT":
            return (entity.dxf.text or "").strip()
        if entity.dxftype() == "MTEXT":
            return (entity.plain_text() or "").strip()
    except Exception:
        pass
    return ""


def _container_entities(doc):
    # Real drawing spaces first. Named block definitions are inspected through
    # actual INSERT instances, which avoids counting orphan symbol libraries.
    for layout in doc.layouts:
        yield "layout", str(getattr(layout, "name", "") or ""), layout


def _insert_signature(entity):
    """Return a weak compact-symbol geometry signal for an INSERT.

    Geometry alone never decides the fixture/equipment type. It only
    corroborates a generic fixture/equipment layer to help numeric block names.
    """
    try:
        virtual = list(entity.virtual_entities())
    except Exception:
        return False
    if not virtual or len(virtual) > 80:
        return False
    primitive = sum(1 for e in virtual if e.dxftype() in {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "ELLIPSE"})
    if primitive < 2:
        return False
    try:
        ext = bbox.extents(virtual, fast=True)
        if not ext.has_data:
            return False
        w = abs(float(ext.extmax.x) - float(ext.extmin.x))
        h = abs(float(ext.extmax.y) - float(ext.extmin.y))
        if w <= 0 or h <= 0:
            return False
        aspect = max(w, h) / max(min(w, h), 1e-9)
        return aspect <= 6.0
    except Exception:
        return primitive >= 3


def _drawing_scale(base_result):
    bounds = base_result.get("geometry_bounds") or []
    if len(bounds) == 4 and None not in bounds:
        try:
            dx = float(bounds[2]) - float(bounds[0])
            dy = float(bounds[3]) - float(bounds[1])
            diag = math.hypot(dx, dy)
            if diag > 0:
                return diag
        except Exception:
            pass
    return 10000.0


def _classify_texts(doc):
    rows = []
    for source_type, source_name, container in _container_entities(doc):
        for entity in container:
            if entity.dxftype() not in {"TEXT", "MTEXT"}:
                continue
            value = _text(entity)
            point = _point(entity)
            if not value or not point:
                continue
            fixture = _alias_match(value, FIXTURE_ALIASES)
            equipment = _alias_match(value, EQUIPMENT_ALIASES)
            if fixture:
                rows.append({"category": "fixture", "type": fixture, "text": value, "point": point, "source_type": source_type, "source_name": source_name})
            if equipment:
                rows.append({"category": "equipment", "type": equipment, "text": value, "point": point, "source_type": source_type, "source_name": source_name})
    return rows


def _nearest_text(text_rows, category, point, source_name, max_distance):
    candidates = [r for r in text_rows if r["category"] == category and r.get("source_name") == source_name]
    if not candidates:
        candidates = [r for r in text_rows if r["category"] == category]
    best = None
    best_d = None
    for row in candidates:
        d = math.dist(point, row["point"])
        if d <= max_distance and (best_d is None or d < best_d):
            best = row
            best_d = d
    return best


def _combine(signals):
    if not signals:
        return 0.0
    scores = sorted((float(s["score"]) for s in signals), reverse=True)
    score = scores[0]
    independent = len({s["kind"] for s in signals})
    if independent >= 2:
        score += CORROBORATION_BONUS
    if independent >= 3:
        score += CORROBORATION_BONUS / 2
    return round(min(score, 0.99), 3)


def _merge_detection(rows, row, tolerance):
    for existing in rows:
        if existing["category"] != row["category"] or existing["type"] != row["type"]:
            continue
        if existing.get("source_name") != row.get("source_name"):
            continue
        try:
            d = math.dist((existing["x"], existing["y"]), (row["x"], row["y"]))
        except Exception:
            d = tolerance + 1
        if d <= tolerance:
            if row["confidence"] > existing["confidence"]:
                existing.update(row)
            else:
                combined = list(existing.get("evidence") or [])
                for item in row.get("evidence") or []:
                    if item not in combined:
                        combined.append(item)
                existing["evidence"] = combined
            return
    rows.append(row)


def _scan_insert(entity, source_type, source_name, text_rows, max_text_distance):
    name = str(getattr(entity.dxf, "name", "") or "")
    layer = str(getattr(entity.dxf, "layer", "") or "")
    point = _point(entity)
    if not point:
        return []
    compact = _insert_signature(entity)
    results = []
    for category, aliases, layer_hints, generic_tokens in (
        ("fixture", FIXTURE_ALIASES, FIXTURE_LAYER_HINTS, GENERIC_FIXTURE_LAYER_TOKENS),
        ("equipment", EQUIPMENT_ALIASES, EQUIPMENT_LAYER_HINTS, GENERIC_EQUIPMENT_LAYER_TOKENS),
    ):
        signals = []
        detected_type = _alias_match(name, aliases)
        if detected_type:
            signals.append({"kind": "block_name", "value": name, "score": SIGNAL_SCORES["block_name"]})
        layer_type = _layer_match(layer, layer_hints)
        if layer_type:
            if detected_type and layer_type != detected_type:
                # Conflicting explicit signals are not silently resolved.
                layer_type = None
            else:
                detected_type = detected_type or layer_type
                signals.append({"kind": "typed_layer", "value": layer, "score": SIGNAL_SCORES["typed_layer"]})
        nearby = _nearest_text(text_rows, category, point, source_name, max_text_distance)
        if nearby and (not detected_type or nearby["type"] == detected_type):
            detected_type = detected_type or nearby["type"]
            signals.append({"kind": "nearby_text", "value": nearby["text"], "score": SIGNAL_SCORES["nearby_text"]})
        generic_layer = any(_norm(token) in _norm(layer) for token in generic_tokens)
        if detected_type and generic_layer and compact:
            signals.append({"kind": "generic_layer_plus_geometry", "value": layer, "score": SIGNAL_SCORES["generic_layer_plus_geometry"]})
        if not detected_type:
            continue
        confidence = _combine(signals)
        if confidence < CANDIDATE_THRESHOLD:
            continue
        results.append({
            "category": category,
            "type": detected_type,
            "name": name,
            "layer": layer,
            "x": round(point[0], 6),
            "y": round(point[1], 6),
            "source_type": source_type,
            "source_name": source_name,
            "confidence": confidence,
            "status": "detected" if confidence >= DETECTED_THRESHOLD else "candidate",
            "evidence": [{"kind": s["kind"], "value": s["value"]} for s in signals],
        })
    return results


def enhance_dxf_result(path, base_result):
    """Enrich one already-analyzed DXF result with fixture/equipment evidence."""
    result = dict(base_result or {})
    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        result["fixture_detection_version"] = DETECTION_VERSION
        result["fixture_detection_diagnostics"] = [f"fixture_detector_read_failed:{type(exc).__name__}"]
        return result

    text_rows = _classify_texts(doc)
    diag = _drawing_scale(result)
    near_distance = max(diag * 0.025, 1.0)
    dedupe_tolerance = max(diag * 0.00005, 1e-4)
    detections = []

    # Preserve legacy high-confidence block detections first so this release is
    # additive rather than destructive.
    for item in result.get("fixture_blocks") or []:
        try:
            x, y = float(item.get("x")), float(item.get("y"))
        except Exception:
            continue
        kind = str(item.get("kind") or "").strip()
        if not kind:
            continue
        row = {
            "category": "fixture", "type": kind, "name": str(item.get("name") or ""),
            "layer": "", "x": round(x, 6), "y": round(y, 6),
            "source_type": "legacy", "source_name": "legacy-analyzer",
            "confidence": 0.94, "status": "detected",
            "evidence": [{"kind": "legacy_block_detector", "value": str(item.get("name") or "")}],
        }
        _merge_detection(detections, row, dedupe_tolerance)

    for source_type, source_name, container in _container_entities(doc):
        for entity in container:
            if entity.dxftype() != "INSERT":
                continue
            for row in _scan_insert(entity, source_type, source_name, text_rows, near_distance):
                _merge_detection(detections, row, dedupe_tolerance)

    # Text-only evidence remains candidate-level to avoid counting legend text
    # as installed equipment/fixtures, but it is retained for diagnostics and
    # later user confirmation.
    for text_row in text_rows:
        p = text_row["point"]
        row = {
            "category": text_row["category"], "type": text_row["type"], "name": "",
            "layer": "", "x": round(p[0], 6), "y": round(p[1], 6),
            "source_type": text_row["source_type"], "source_name": text_row["source_name"],
            "confidence": TEXT_ONLY_MAX_CONFIDENCE, "status": "candidate",
            "evidence": [{"kind": "explicit_text", "value": text_row["text"]}],
        }
        _merge_detection(detections, row, dedupe_tolerance)

    fixtures = [r for r in detections if r["category"] == "fixture"]
    equipment = [r for r in detections if r["category"] == "equipment"]
    fixture_counts = Counter(r["type"] for r in fixtures if r["status"] == "detected")
    equipment_counts = Counter(r["type"] for r in equipment if r["status"] == "detected")

    result["fixture_detection_version"] = DETECTION_VERSION
    result["fixture_detections"] = fixtures[:20000]
    result["equipment_detections"] = equipment[:20000]
    result["fixture_counts"] = dict(fixture_counts)
    result["equipment_counts"] = dict(equipment_counts)
    result["fixture_blocks_detected"] = sum(fixture_counts.values())
    result["equipment_detected"] = sum(equipment_counts.values())
    result["fixture_detection_diagnostics"] = []
    return result


def _assign_level(detection, profiles):
    if not profiles:
        return None
    point = (float(detection.get("x") or 0), float(detection.get("y") or 0))
    source_name = str(detection.get("source_name") or "")
    same_source = [p for p in profiles if str(p.get("source_name") or "") == source_name and p.get("title_point")]
    candidates = same_source or [p for p in profiles if p.get("title_point")]
    if not candidates:
        return None
    return min(candidates, key=lambda p: math.dist(point, tuple(p["title_point"]))).get("name")


def enrich_auto_inference(auto, analysis):
    files = (analysis or {}).get("files") or []
    fixtures = []
    equipment = []
    for file_info in files:
        fixtures.extend(file_info.get("fixture_detections") or [])
        equipment.extend(file_info.get("equipment_detections") or [])
    profiles = auto.get("level_profiles") or []
    for row in fixtures + equipment:
        if not row.get("level"):
            level = _assign_level(row, profiles)
            if level:
                row["level"] = level
    auto["fixture_detections"] = fixtures
    auto["equipment_detections"] = equipment
    auto["equipment"] = [r for r in equipment if r.get("status") == "detected"]
    auto["fixture_counts"] = dict(Counter(r["type"] for r in fixtures if r.get("status") == "detected"))
    auto["equipment_counts"] = dict(Counter(r["type"] for r in equipment if r.get("status") == "detected"))
    auto["fixture_blocks_detected"] = sum(auto["fixture_counts"].values())
    auto["equipment_detected"] = sum(auto["equipment_counts"].values())
    auto["fixture_detection_version"] = DETECTION_VERSION

    diagnostics = list(auto.get("evidence_diagnostics") or [])
    wet_levels = []
    for profile in profiles:
        rooms = profile.get("room_counts") or {}
        if any(int(rooms.get(room) or 0) > 0 for room in WET_ROOM_TYPES):
            wet_levels.append(str(profile.get("name") or ""))
    detected_fixture_levels = {str(r.get("level")) for r in fixtures if r.get("status") == "detected" and r.get("level")}
    for level in wet_levels:
        if level and level not in detected_fixture_levels:
            code = f"wet_level_without_detected_fixture:{level}"
            if code not in diagnostics:
                diagnostics.append(code)
    auto["evidence_diagnostics"] = diagnostics
    return auto


def install(main_auto_module):
    """Install additive analyzer/inference wrappers before project analysis."""
    if getattr(main_auto_module, "_fixture_detection_v2_installed", False):
        return

    base_analyzer = main_auto_module.analyze_dxf_enhanced
    base_infer = main_auto_module.infer_architecture_facts

    def analyze_with_fixture_detection(path):
        return enhance_dxf_result(path, base_analyzer(path))

    def infer_with_fixture_detection(analysis, discipline):
        return enrich_auto_inference(base_infer(analysis, discipline), analysis)

    main_auto_module.analyze_dxf_enhanced = analyze_with_fixture_detection
    # analyze_project_job resolves these globals at execution time.
    main_auto_module.infer_architecture_facts = infer_with_fixture_detection
    main_auto_module.legacy.analyze_dxf = analyze_with_fixture_detection

    # PMM keeps the same public schema but now preserves per-detection evidence
    # when v2 data is available; old projects still fall back to count summaries.
    from . import project_mechanical_model as pmm
    old_fixture_rows = pmm._fixture_rows

    def fixture_rows_v2(auto):
        detections = auto.get("fixture_detections") or []
        if not detections:
            return old_fixture_rows(auto)
        rows = []
        for d in detections:
            rows.append({
                "type": str(d.get("type") or ""),
                "level": d.get("level"),
                "position": [d.get("x"), d.get("y")],
                "confidence": float(d.get("confidence") or 0),
                "status": d.get("status") or "candidate",
                "evidence": list(d.get("evidence") or []),
                "source": "fixture-equipment-v2",
            })
        return rows

    pmm._fixture_rows = fixture_rows_v2
    main_auto_module._fixture_detection_v2_installed = True
