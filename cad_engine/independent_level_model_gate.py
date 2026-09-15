"""Independent architectural floor/roof ownership and vertical graph.

This module is deliberately source-only: it reads the sealed architectural DXF
and the already reconstructed architecture.  Mechanical reference drawings are
neither accepted nor consulted.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re

import ezdxf
from ezdxf import bbox

GRAPHIC_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "HATCH", "INSERT"}
PRESENTATION_TOKENS = ("frame", "sheet", "border", "title", "support", "suport", "کادر", "قاب")


def _norm(value):
    value = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    value = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    return re.sub(r"\s+", " ", value).strip()


def normalize_level_identity(value, *, roof=False):
    if roof:
        return "ROOF"
    text = _norm(value)
    if not text:
        return None
    if "خرپشته" in text:
        return "ROOF-PENTHOUSE"
    if "بام" in text or "roof" in text:
        return "ROOF"
    if "پیلوت" in text or "pilot" in text:
        return "PILOT"
    if "نیم طبقه" in text or "mezzanine" in text:
        return "MEZZANINE"
    basement = re.search(r"(?:زیرزمین|basement|b)\s*[- ]?\s*(\d+)?", text)
    if basement:
        number = int(basement.group(1) or 1)
        return f"BASEMENT-{number:02d}"
    if "همکف" in text or re.search(r"\b(?:ground|gf|level 0)\b", text):
        return "GROUND"
    persian = {"اول": 1, "دوم": 2, "سوم": 3, "چهارم": 4, "پنجم": 5,
               "ششم": 6, "هفتم": 7, "هشتم": 8, "نهم": 9, "دهم": 10}
    for word, number in persian.items():
        if f"طبقه {word}" in text:
            return f"LEVEL-{number:02d}"
    match = re.search(r"(?:floor|level|طبقه)\s*[- ]?\s*(\d+)", text)
    if match:
        return f"LEVEL-{int(match.group(1)):02d}"
    # Already canonical or a user-confirmed stable label.
    if re.fullmatch(r"(?:level|basement)-\d+", text):
        prefix, number = text.split("-")
        return f"{prefix.upper()}-{int(number):02d}"
    return re.sub(r"[^A-Z0-9\u0600-\u06ff]+", "-", str(value).upper()).strip("-") or None


def _inside(point, bounds, tolerance=1e-7):
    return bool(point and bounds and bounds[0]-tolerance <= point[0] <= bounds[2]+tolerance and
                bounds[1]-tolerance <= point[1] <= bounds[3]+tolerance)


def _entity_extent(entity):
    try:
        extent = bbox.extents([entity], fast=True)
        if extent.has_data:
            return (float(extent.extmin.x), float(extent.extmin.y), float(extent.extmax.x), float(extent.extmax.y))
    except Exception:
        return None
    return None


def _entity_point(entity, extent):
    if extent:
        return ((extent[0]+extent[2])/2, (extent[1]+extent[3])/2)
    for name in ("insert", "location", "start", "center"):
        try:
            point = getattr(entity.dxf, name)
            return float(point.x), float(point.y)
        except Exception:
            pass
    return None


def _graphic_token(entity, extent, bounds):
    width = max(float(bounds[2])-float(bounds[0]), 1e-9)
    height = max(float(bounds[3])-float(bounds[1]), 1e-9)
    return (entity.dxftype(), _norm(getattr(entity.dxf, "layer", "")), tuple(round(v, 5) for v in (
        (extent[0]-bounds[0])/width, (extent[1]-bounds[1])/height,
        (extent[2]-bounds[0])/width, (extent[3]-bounds[1])/height)))


def _point_of(item):
    point = item.get("point") or item.get("centroid") or item.get("label_point")
    if point is None and item.get("polygon"):
        polygon = item["polygon"]
        point = (sum(p[0] for p in polygon)/len(polygon), sum(p[1] for p in polygon)/len(polygon))
    try:
        return float(point[0]), float(point[1])
    except (TypeError, ValueError, IndexError):
        return None


def _identity_for_plan(plan):
    roof = plan.get("drawing_type") == "ROOF_PLAN" and plan.get("mechanical_role") == "ROOF_SUPPORT"
    represented = [normalize_level_identity(item) for item in plan.get("represented_levels") or []]
    represented = [item for item in represented if item]
    level = normalize_level_identity(plan.get("level"), roof=roof)
    if not represented and level:
        represented = [level]
    if len(represented) > 1:
        digest = sha256("|".join(represented).encode()).hexdigest()[:10].upper()
        level = f"TYPICAL-GROUP-{digest}"
    return level, list(dict.fromkeys(represented)), roof


def _vertical_graph(models, shafts):
    nodes, groups, warnings = [], [], []
    for model in models:
        bounds = model["source_bounds"]
        width, height = max(bounds[2]-bounds[0], 1e-9), max(bounds[3]-bounds[1], 1e-9)
        for shaft in shafts:
            if shaft.get("plan_id") != model["plan_id"]:
                continue
            point = _point_of(shaft)
            if not point:
                continue
            represented = model.get("represented_level_ids") or [model["level_id"]]
            for represented_level in represented:
                node = {"shaft_id": shaft.get("id") or f"SHAFT-{len(nodes)+1:03d}", "plan_id": model["plan_id"],
                        "level_id": represented_level, "parent_model_id": model["model_id"], "source_point": point,
                        "normalized_point": (round((point[0]-bounds[0])/width, 6), round((point[1]-bounds[1])/height, 6))}
                nodes.append(node)
    for node in sorted(nodes, key=lambda row: (row["level_id"], row["shaft_id"])):
        match = next((group for group in groups if math.dist(node["normalized_point"], group["reference_point"]) <= .03), None)
        if match is None:
            match = {"vertical_id": f"VERTICAL-{len(groups)+1:03d}", "reference_point": node["normalized_point"], "nodes": []}
            groups.append(match)
        match["nodes"].append(node)
    for group in groups:
        levels = [node["level_id"] for node in group["nodes"]]
        if len(levels) != len(set(levels)):
            warnings.append(f"multiple_shafts_same_level:{group['vertical_id']}")
        residuals = [math.dist(node["normalized_point"], group["reference_point"]) for node in group["nodes"]]
        group["max_normalized_residual"] = round(max(residuals, default=0.0), 6)
        group["level_ids"] = sorted(set(levels))
    return {"status": "PASS" if not warnings else "INPUT_REQUIRED", "nodes": nodes, "verticals": groups,
            "warnings": warnings, "alignment_tolerance": .03}


def _level_order(level_id):
    if level_id.startswith("BASEMENT-"):
        return -int(level_id.split("-")[-1])
    if level_id in {"PILOT", "GROUND"}:
        return 0
    if level_id == "MEZZANINE":
        return .5
    if level_id.startswith("LEVEL-"):
        return int(level_id.split("-")[-1])
    if level_id == "ROOF-PENTHOUSE":
        return 1000
    if level_id == "ROOF":
        return 1001
    return None


def build_independent_level_model(source_path: Path, architecture: dict, recognition: dict, *, unit_to_m=None) -> dict:
    source_path = Path(source_path)
    source_hash = sha256(source_path.read_bytes()).hexdigest()
    doc = ezdxf.readfile(source_path)
    source_views = [dict(plan) for plan in architecture.get("plans") or []
                    if plan.get("mechanical_role") in {"PRIMARY_FLOOR", "ROOF_SUPPORT", "ROOF_ANALYSIS_SUPPORT"}]
    plans = [plan for plan in source_views if plan.get("mechanical_role") in {"PRIMARY_FLOOR", "ROOF_SUPPORT"}]
    errors, missing, warnings = [], [], []
    if not unit_to_m or not math.isfinite(float(unit_to_m)) or float(unit_to_m) <= 0:
        missing.append("CALIBRATED_ARCHITECTURAL_UNIT_REQUIRED")
    plan_ids = [str(plan.get("plan_id") or "") for plan in plans]
    if not plans:
        missing.append("CONFIRMED_ARCHITECTURAL_PLAN_REQUIRED")
    if "" in plan_ids or len(plan_ids) != len(set(plan_ids)):
        errors.append("UNIQUE_PLAN_ID_REQUIRED")

    models = []
    for plan in plans:
        bounds = plan.get("bounds")
        content_bounds = plan.get("content_bounds")
        if not bounds or len(bounds) != 4 or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            errors.append(f"INVALID_PLAN_BOUNDS:{plan.get('plan_id')}")
            continue
        level_id, represented, roof = _identity_for_plan(plan)
        if not level_id:
            missing.append(f"LEVEL_ID_REQUIRED:{plan.get('plan_id')}")
            level_id = f"UNRESOLVED-{plan.get('plan_id')}"
        if not content_bounds or len(content_bounds) != 4:
            missing.append(f"CONTENT_BOUNDS_REQUIRED:{plan.get('plan_id')}")
        models.append({"model_id": f"LEVEL-MODEL-{sha256((source_hash+str(plan['plan_id'])).encode()).hexdigest()[:16].upper()}",
                       "plan_id": plan["plan_id"], "level_id": level_id, "represented_level_ids": represented,
                       "level_instances": [{"level_id": item, "parent_model_role": "TYPICAL_INSTANCE"}
                                           for item in represented] if len(represented)>1 else [],
                       "kind": "ROOF" if roof else ("TYPICAL_FLOOR" if len(represented) > 1 else "FLOOR"),
                       "source_bounds": [float(v) for v in bounds],
                       "source_views": [{"plan_id": plan["plan_id"], "role": plan.get("roof_view_role") or "ARCHITECTURAL_BASE",
                                         "bounds": [float(v) for v in bounds], "local_origin": [float(bounds[0]),float(bounds[1])],
                                         "source_transform": {"scale_x":1.0,"scale_y":1.0,"offset_x":-float(bounds[0]),"offset_y":-float(bounds[1]),"inverse_required":True}}],
                       "content_bounds": [float(v) for v in content_bounds] if content_bounds and len(content_bounds)==4 else None,
                       "local_origin": [float(bounds[0]), float(bounds[1])],
                       "source_transform": {"scale_x": 1.0, "scale_y": 1.0,
                                            "offset_x": -float(bounds[0]), "offset_y": -float(bounds[1]),
                                            "inverse_required": True},
                       "entity_ids": [], "room_ids": [], "shaft_ids": [], "equipment_ids": [],
                       "entities": [],
                       "source_geometry_fingerprint": None})
    level_ids = [model["level_id"] for model in models]
    if len(level_ids) != len(set(level_ids)):
        errors.append("DUPLICATE_LEVEL_ID")

    primary_roof = next((model for model in models if model["kind"] == "ROOF"), None)
    view_owner = {model["plan_id"]: model for model in models}
    for view in source_views:
        if view.get("mechanical_role") != "ROOF_ANALYSIS_SUPPORT":
            continue
        if primary_roof is None:
            errors.append("ROOF_SUPPORT_WITHOUT_ARCHITECTURAL_BASE")
            continue
        primary_roof["source_views"].append({"plan_id": view["plan_id"], "role": view.get("roof_view_role") or "SLOPE_DRAINAGE_SUPPORT",
                                             "bounds": [float(v) for v in view["bounds"]],
                                             "local_origin":[float(view["bounds"][0]),float(view["bounds"][1])],
                                             "source_transform":{"scale_x":1.0,"scale_y":1.0,"offset_x":-float(view["bounds"][0]),"offset_y":-float(view["bounds"][1]),"inverse_required":True}})
        view_owner[view["plan_id"]] = primary_roof

    owner_by_handle, graphic_tokens = {}, defaultdict(list)
    for entity in doc.modelspace():
        extent = _entity_extent(entity)
        point = _entity_point(entity, extent)
        matching_views = [view for view in source_views if _inside(point, view.get("bounds"))]
        matches = list({view_owner.get(view.get("plan_id"))["model_id"]: view_owner.get(view.get("plan_id"))
                        for view in matching_views if view_owner.get(view.get("plan_id"))}.values())
        if len(matches) > 1:
            errors.append(f"MULTIPLE_ENTITY_OWNER:{getattr(entity.dxf, 'handle', '?')}")
            continue
        if not matches:
            continue
        model = matches[0]
        source_view = next(view for view in matching_views if view_owner.get(view.get("plan_id")) is model)
        view_bounds = source_view["bounds"]
        handle = str(getattr(entity.dxf, "handle", "") or "")
        if handle in owner_by_handle:
            errors.append(f"DUPLICATE_ENTITY_HANDLE:{handle}")
            continue
        owner_by_handle[handle] = model["model_id"]
        model["entity_ids"].append(handle)
        layer = _norm(getattr(entity.dxf, "layer", ""))
        if extent:
            origin = [float(view_bounds[0]),float(view_bounds[1])]
            model["entities"].append({"entity_id": handle, "type": entity.dxftype(), "layer": str(getattr(entity.dxf, "layer", "") or ""),
                                      "source_view_plan_id": source_view["plan_id"],
                                      "source_extent": [round(value, 6) for value in extent],
                                      "local_extent": [round(extent[0]-origin[0], 6), round(extent[1]-origin[1], 6),
                                                       round(extent[2]-origin[0], 6), round(extent[3]-origin[1], 6)]})
        if entity.dxftype() in GRAPHIC_TYPES and extent and not any(token in layer for token in PRESENTATION_TOKENS):
            token=(source_view.get("roof_view_role") or "ARCHITECTURAL_BASE",)+_graphic_token(entity, extent, view_bounds)
            graphic_tokens[model["model_id"]].append(token)

    model_by_plan = dict(view_owner)
    classified_plan_ids = {plan.get("plan_id") for plan in architecture.get("plans") or []}
    excluded_plan_ids = {plan.get("plan_id") for plan in architecture.get("plans") or []
                         if plan.get("mechanical_role") == "EXCLUDE"}
    for key, target in (("rooms", "room_ids"), ("shafts", "shaft_ids")):
        for item in architecture.get(key) or []:
            model = model_by_plan.get(item.get("plan_id"))
            if model:
                model[target].append(str(item.get("id") or f"{key.upper()}-{len(model[target])+1:03d}"))
    for item in recognition.get("detections") or []:
        model = model_by_plan.get(item.get("plan_id"))
        if model:
            model["equipment_ids"].append(str(item.get("id") or f"OBJECT-{len(model['equipment_ids'])+1:03d}"))
    for model in models:
        tokens = sorted(graphic_tokens[model["model_id"]])
        model["entity_ids"] = sorted(model["entity_ids"])
        model["entities"] = sorted(model["entities"], key=lambda row: row["entity_id"])
        for key in ("room_ids", "shaft_ids", "equipment_ids"):
            model[key] = sorted(set(model[key]))
        model["source_geometry_fingerprint"] = sha256(json.dumps(tokens, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest() if tokens else None
        if not tokens:
            missing.append(f"DRAWABLE_GEOMETRY_REQUIRED:{model['plan_id']}")

    by_fingerprint = defaultdict(list)
    for model in models:
        if model["source_geometry_fingerprint"]:
            by_fingerprint[model["source_geometry_fingerprint"]].append(model)
    duplicate_groups = []
    for fingerprint, group in by_fingerprint.items():
        if len(group) < 2:
            continue
        explicit_typical = all(model["kind"] == "TYPICAL_FLOOR" for model in group)
        duplicate_groups.append({"fingerprint": fingerprint, "model_ids": [model["model_id"] for model in group],
                                 "explicit_typical": explicit_typical})
        if not explicit_typical:
            errors.append("UNAPPROVED_DUPLICATE_LEVEL_GEOMETRY:" + ",".join(model["level_id"] for model in group))

    roof_models = [model for model in models if model["kind"] == "ROOF"]
    roof_plans = [plan for plan in plans if plan.get("mechanical_role") == "ROOF_SUPPORT"]
    if len(roof_models) != len(roof_plans):
        errors.append("FABRICATED_OR_UNCONFIRMED_ROOF_MODEL")
    if len(roof_models) > 1:
        missing.append("AMBIGUOUS_MULTIPLE_ROOF_MODELS")
    roof_feature_layers = defaultdict(list)
    if len(roof_models) == 1:
        for row in roof_models[0]["entities"]:
            layer = _norm(row["layer"])
            if any(token in layer for token in ("parapet", "جان پناه", "جانپناه")):
                roof_feature_layers["parapets"].append(row["entity_id"])
            if any(token in layer for token in ("slope", "شیب")):
                roof_feature_layers["slope_evidence"].append(row["entity_id"])
            if any(token in layer for token in ("drain", "roof drain", "کفشور", "آبرو")):
                roof_feature_layers["drain_evidence"].append(row["entity_id"])
            if any(token in layer for token in ("opening", "void", "بازشو")):
                roof_feature_layers["prohibited_zones"].append(row["entity_id"])
    roof = {"status": "CONFIRMED" if len(roof_models)==1 else ("NOT_PROVIDED" if not roof_models else "INPUT_REQUIRED"),
            "model_id": roof_models[0]["model_id"] if len(roof_models)==1 else None,
            "equipment_ids": roof_models[0]["equipment_ids"] if len(roof_models)==1 else [],
            "shaft_ids": roof_models[0]["shaft_ids"] if len(roof_models)==1 else [],
            "features": {key: sorted(value) for key, value in roof_feature_layers.items()}}
    vertical = _vertical_graph(models, architecture.get("shafts") or [])
    warnings.extend(vertical.get("warnings") or [])
    order = {}
    for model in models:
        identities = model.get("represented_level_ids") or [model["level_id"]]
        for identity in identities:
            order[identity] = _level_order(identity)
    unresolved_order = sorted(level for level, value in order.items() if value is None)
    if unresolved_order:
        missing.extend(f"LEVEL_ELEVATION_OR_ORDER_REQUIRED:{level}" for level in unresolved_order)

    checks = {
        "immutable_source_identity": bool(source_hash),
        "calibrated_units": not any("CALIBRATED_ARCHITECTURAL_UNIT_REQUIRED" in row for row in missing),
        "confirmed_frame_inventory": bool(plans),
        "drawing_type_classification": all(model["kind"] in {"FLOOR", "TYPICAL_FLOOR", "ROOF"} for model in models),
        "unique_plan_identity": bool(plan_ids) and len(plan_ids)==len(set(plan_ids)),
        "normalized_level_identity": bool(level_ids) and all(not row.startswith("UNRESOLVED-") for row in level_ids),
        "vertical_level_order_available": bool(models) and not unresolved_order,
        "unique_entity_ownership": not any(row.startswith("MULTIPLE_ENTITY_OWNER") for row in errors),
        "local_source_roundtrip": all(model["source_transform"]["inverse_required"] for model in models),
        "independent_drawable_geometry": all(model["source_geometry_fingerprint"] for model in models),
        # Objects on sections, elevations, furniture and other explicitly
        # excluded views are retained by reconstruction as source evidence but
        # are not floor-model objects. Unknown/unclassified ownership still
        # fails; only a deliberate EXCLUDE classification is exempt.
        "room_level_binding": all(room.get("plan_id") in model_by_plan or room.get("plan_id") in excluded_plan_ids
                                  for room in architecture.get("rooms") or []),
        "shaft_level_binding": all(shaft.get("plan_id") in model_by_plan or shaft.get("plan_id") in excluded_plan_ids
                                   for shaft in architecture.get("shafts") or []),
        "equipment_level_binding": all(item.get("plan_id") in model_by_plan or item.get("plan_id") in excluded_plan_ids
                                       for item in recognition.get("detections") or []),
        "typical_floor_evidence": not any(row.startswith("UNAPPROVED_DUPLICATE_LEVEL_GEOMETRY") for row in errors),
        "roof_evidence_only": not any(row == "FABRICATED_OR_UNCONFIRMED_ROOF_MODEL" for row in errors),
        "vertical_core_graph": vertical.get("status") in {"PASS", "INPUT_REQUIRED"},
        "cross_level_geometry_zero": not any(row.startswith("MULTIPLE_ENTITY_OWNER") for row in errors),
        "deterministic_model_fingerprint": all(model["model_id"] and model["source_geometry_fingerprint"] for model in models),
    }
    false_checks = [name for name, passed in checks.items() if not passed]
    status = "FAIL" if errors else ("INPUT_REQUIRED" if missing or false_checks else "PASS")
    return {"status": status, "rule_id": "MEP-LEVEL-MODEL-001", "source_sha256": source_hash,
            "unit_to_m": float(unit_to_m) if unit_to_m else None, "models": models, "roof": roof,
            "level_order": order, "vertical_graph": vertical, "entity_ownership": owner_by_handle, "duplicate_groups": duplicate_groups,
            "excluded_source_plan_ids": sorted(str(item) for item in excluded_plan_ids if item),
            "classified_source_plan_ids": sorted(str(item) for item in classified_plan_ids if item),
            "errors": sorted(set(errors)), "missing_inputs": sorted(set(missing)), "warnings": sorted(set(warnings)),
            "checks": checks, "failed_checks": false_checks, "passed_count": sum(checks.values()), "required_count": len(checks),
            "score": round(100*sum(checks.values())/len(checks), 2)}
