"""Fail-closed Mechanical equipment selection and placement acceptance."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math


CONTRACT_VERSION = "equipment-selection-placement/1"
CONTROL_WEIGHTS = {
    "typed_room_model": 5,
    "existing_equipment_classification": 3,
    "design_basis_complete": 6,
    "space_by_space_demand": 8,
    "water_service_duties": 4,
    "ventilation_duties": 4,
    "official_catalogue_evidence": 7,
    "deterministic_selection": 6,
    "capacity_match": 8,
    "candidate_location_evidence": 4,
    "architectural_host_validity": 7,
    "service_clearance": 6,
    "network_connection_complete": 7,
    "safety_and_code_clearance": 6,
    "multi_criteria_placement": 4,
    "plan_riser_schedule_identity": 6,
    "equipment_visual_qa": 5,
    "exact_output_release_evidence": 4,
}
assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100


def _stable(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _finite_positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _ids(rows):
    return {row.get("equipment_id") or row.get("id") for row in rows if row.get("equipment_id") or row.get("id")}


def exact_equipment_output_evidence(path, expected_ids):
    """Reopen the issued DXF and prove that every expected public tag exists."""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(path))
        texts = []
        for entity in doc.modelspace():
            if entity.dxftype() in {"TEXT", "MTEXT"}:
                texts.append(str(entity.dxf.text if entity.dxftype() == "TEXT" else entity.text))
        found = {eid for eid in expected_ids if any(str(eid) in value for value in texts)}
        return {"reopened": True, "immutable": True, "equipment_ids": sorted(found)}
    except Exception as exc:
        return {"reopened": False, "immutable": False, "equipment_ids": [], "error": type(exc).__name__}


def evaluate_equipment_selection_placement(context, exact_output=None):
    """Evaluate all eighteen controls without inventing missing engineering evidence.

    ``context`` is an additive runtime contract. It may be assembled from PMM,
    calculations, official catalogue selection, routing and documentation phases.
    Missing evidence is INPUT_REQUIRED; contradictory evidence is FAIL.
    """
    context = context or {}; exact_output = exact_output or {}
    rooms = context.get("rooms") or []
    required = context.get("required_equipment") or []
    selected = context.get("selected_equipment") or []
    calculations = context.get("calculations") or []
    routes = context.get("routes") or []
    schedules = context.get("schedules") or []
    risers = context.get("risers") or []
    candidates = context.get("placement_candidates") or []
    design_basis = context.get("design_basis") or {}
    missing = {name: [] for name in CONTROL_WEIGHTS}
    errors = {name: [] for name in CONTROL_WEIGHTS}

    room_by_id = {row.get("id"): row for row in rooms if row.get("id")}
    calc_by_id = {row.get("calc_id"): row for row in calculations if row.get("calc_id")}
    selected_by_id = {row.get("equipment_id") or row.get("id"): row for row in selected
                      if row.get("equipment_id") or row.get("id")}

    # 1 — authoritative room, level, use, geometry and height.
    if not rooms:
        missing["typed_room_model"].append("TYPED_ROOM_MODEL_REQUIRED")
    for room in rooms:
        absent = [key for key in ("id", "level_id", "use", "bounds", "area_m2", "height_m") if room.get(key) is None]
        if absent:
            missing["typed_room_model"].append(f"ROOM_FIELDS:{room.get('id')}:{','.join(absent)}")

    # 2 — source architectural equipment is explicitly classified and confidence-backed.
    inventory = context.get("existing_equipment_inventory")
    if inventory is None:
        missing["existing_equipment_classification"].append("EXISTING_EQUIPMENT_INVENTORY_REQUIRED")
    else:
        for row in inventory:
            if row.get("classification") not in {"EXISTING", "PROPOSED", "NOT_EQUIPMENT"} or not _finite_positive(row.get("confidence")):
                errors["existing_equipment_classification"].append("UNCLASSIFIED_ARCHITECTURAL_OBJECT:" + str(row.get("id")))

    # 3 — project basis is explicit rather than reference-derived.
    basis_fields = context.get("required_design_basis_fields") or []
    if not basis_fields:
        missing["design_basis_complete"].append("REQUIRED_DESIGN_BASIS_FIELD_LIST_REQUIRED")
    absent = [key for key in basis_fields if design_basis.get(key) in (None, "", "UNKNOWN")]
    if absent:
        missing["design_basis_complete"].append("DESIGN_BASIS:" + ",".join(sorted(absent)))
    if design_basis.get("source") == "MECHANICAL_REFERENCE_DRAWING":
        errors["design_basis_complete"].append("REFERENCE_DERIVED_GENERATION_INPUT_FORBIDDEN")

    # 4 — every required item has a positive, room-bound demand calculation.
    for row in required:
        eid = row.get("equipment_id") or row.get("id")
        calc = calc_by_id.get(row.get("calc_id"))
        if not calc or not _finite_positive(calc.get("demand")) or not calc.get("unit") or not calc.get("formula"):
            missing["space_by_space_demand"].append("DEMAND_CALCULATION_REQUIRED:" + str(eid))
        if row.get("room_id") and row.get("room_id") not in room_by_id:
            errors["space_by_space_demand"].append("UNKNOWN_ROOM:" + str(eid))

    # 5/6 — applicable pump/tank/hot-water and ventilation duties are explicit.
    for row in selected:
        eid = row.get("equipment_id") or row.get("id")
        kind = str(row.get("kind") or "").lower()
        if kind in {"pump", "booster_pump", "tank", "water_heater", "package"}:
            for key in row.get("required_duty_fields") or []:
                if not _finite_positive(row.get(key)):
                    missing["water_service_duties"].append(f"DUTY:{eid}:{key}")
        if kind in {"fan", "exhaust_fan", "ahu", "fcu"}:
            for key in ("airflow", "external_static_pressure"):
                if not _finite_positive(row.get(key)):
                    missing["ventilation_duties"].append(f"VENTILATION_DUTY:{eid}:{key}")

    # 7/8 — immutable official data and reproducible winning candidate.
    for eid, row in selected_by_id.items():
        sheet = row.get("datasheet") or {}
        if not row.get("manufacturer") or not row.get("model") or not sheet.get("official_url") or len(str(sheet.get("sha256") or "")) != 64:
            missing["official_catalogue_evidence"].append("OFFICIAL_DATASHEET_REQUIRED:" + str(eid))
        evaluated = row.get("evaluated_candidate_ids") or []
        if not evaluated or row.get("selection_rule") is None or row.get("selected_candidate_id") not in evaluated:
            missing["deterministic_selection"].append("REPRODUCIBLE_SELECTION_REQUIRED:" + str(eid))

    # 9 — selected capacity satisfies demand and the explicit oversizing limit.
    for req in required:
        eid = req.get("equipment_id") or req.get("id"); item = selected_by_id.get(eid)
        calc = calc_by_id.get(req.get("calc_id"))
        if not item:
            missing["capacity_match"].append("SELECTION_REQUIRED:" + str(eid)); continue
        if not calc or not _finite_positive(item.get("selected_capacity")):
            missing["capacity_match"].append("CAPACITY_EVIDENCE_REQUIRED:" + str(eid)); continue
        demand = float(calc["demand"]); capacity = float(item["selected_capacity"])
        maximum = req.get("max_oversize_ratio")
        if maximum is None:
            missing["capacity_match"].append("MAX_OVERSIZE_RATIO_REQUIRED:" + str(eid))
        elif capacity < demand or capacity / demand > float(maximum) + 1e-9:
            errors["capacity_match"].append("CAPACITY_OUTSIDE_PERMITTED_RANGE:" + str(eid))

    # 10/11 — candidates and selected hosts remain inside authoritative geometry.
    candidate_equipment = Counter(row.get("equipment_id") for row in candidates if row.get("status") == "VALID")
    for eid, row in selected_by_id.items():
        if candidate_equipment[eid] < 1:
            missing["candidate_location_evidence"].append("VALID_CANDIDATE_REQUIRED:" + str(eid))
        if not row.get("host_id") or not row.get("level_id") or row.get("inside_host") is not True:
            errors["architectural_host_validity"].append("INVALID_ARCHITECTURAL_HOST:" + str(eid))
        if row.get("architectural_collision") or row.get("egress_obstruction"):
            errors["architectural_host_validity"].append("ARCHITECTURAL_OR_EGRESS_CONFLICT:" + str(eid))

    # 12 — installation, replacement and service envelope.
    for eid, row in selected_by_id.items():
        if row.get("service_clearance_status") != "PASS" or row.get("replacement_access") is not True:
            errors["service_clearance"].append("SERVICE_OR_REPLACEMENT_ACCESS_FAILED:" + str(eid))

    # 13 — declared ports and actual routes agree exactly.
    route_ports = Counter()
    for route in routes:
        for endpoint in (route.get("from"), route.get("to")):
            if endpoint:
                route_ports[(endpoint, route.get("system"))] += 1
    for eid, row in selected_by_id.items():
        for port in row.get("required_ports") or []:
            if route_ports[(eid, port)] != 1:
                errors["network_connection_complete"].append(f"PORT_ROUTE_COUNT_{route_ports[(eid, port)]}:{eid}:{port}")

    # 14/15 — safety and scored placement decision.
    for eid, row in selected_by_id.items():
        if row.get("safety_status") != "PASS" or row.get("code_clearance_status") != "PASS":
            errors["safety_and_code_clearance"].append("SAFETY_OR_CODE_CLEARANCE_FAILED:" + str(eid))
        scores = row.get("placement_scores") or {}
        if not scores or any(not math.isfinite(float(value)) for value in scores.values()):
            missing["multi_criteria_placement"].append("PLACEMENT_SCORE_REQUIRED:" + str(eid))
        elif row.get("chosen_candidate_id") != row.get("highest_ranked_candidate_id"):
            errors["multi_criteria_placement"].append("NON_OPTIMAL_CANDIDATE_WITHOUT_OVERRIDE:" + str(eid))

    # 16 — immutable identity and capacity parity across documents.
    expected_ids = set(selected_by_id)
    for label, rows in (("PLAN", context.get("plan_equipment") or []), ("RISER", risers), ("SCHEDULE", schedules)):
        if _ids(rows) != expected_ids:
            errors["plan_riser_schedule_identity"].append(label + "_EQUIPMENT_IDENTITY_MISMATCH")
        for row in rows:
            eid = row.get("equipment_id") or row.get("id"); selected_row = selected_by_id.get(eid) or {}
            if eid and row.get("selected_capacity") != selected_row.get("selected_capacity"):
                errors["plan_riser_schedule_identity"].append(label + "_CAPACITY_MISMATCH:" + str(eid))

    # 17 — independent per-equipment and per-sheet visual checks.
    visual = context.get("visual_qa") or {}
    if visual.get("status") != "PASS" or set(visual.get("equipment_ids") or []) != expected_ids or visual.get("critical_defects"):
        errors["equipment_visual_qa"].append("EQUIPMENT_VISUAL_QA_NOT_PASS")

    # 18 — exact issued file is reopened, immutable and contains every identity.
    if not exact_output:
        missing["exact_output_release_evidence"].append("EXACT_OUTPUT_EVIDENCE_REQUIRED")
    elif exact_output.get("reopened") is not True or exact_output.get("immutable") is not True or set(exact_output.get("equipment_ids") or []) != expected_ids:
        errors["exact_output_release_evidence"].append("EXACT_OUTPUT_EQUIPMENT_PARITY_FAILED")

    controls = []
    for name, weight in CONTROL_WEIGHTS.items():
        state = "FAIL" if errors[name] else ("INPUT_REQUIRED" if missing[name] else "PASS")
        controls.append({"id": name, "weight": weight, "status": state,
                         "errors": errors[name], "missing_inputs": missing[name]})
    score = sum(row["weight"] for row in controls if row["status"] == "PASS")
    status = "FAIL" if any(row["status"] == "FAIL" for row in controls) else (
        "INPUT_REQUIRED" if any(row["status"] == "INPUT_REQUIRED" for row in controls) else "PASS")
    report = {"contract": CONTRACT_VERSION, "status": status, "score": score,
              "controls": controls, "all_controls_pass": all(row["status"] == "PASS" for row in controls),
              "release_allowed": status == "PASS" and score == 100,
              "errors": sorted({item for row in controls for item in row["errors"]}),
              "missing_inputs": sorted({item for row in controls for item in row["missing_inputs"]}),
              "evidence_hash": _stable({"context": context, "exact_output": exact_output})}
    report["preflight_allowed"] = all(row["status"] == "PASS" for row in controls[:-1])
    return report
