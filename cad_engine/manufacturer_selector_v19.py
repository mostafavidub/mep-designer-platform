"""Provenance-locked manufacturer catalogue and calculation-driven selector."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json


REQUIRED_FIELDS = {
    "manufacturer", "model", "equipment_type", "capacity_kw", "dimensions_mm",
    "connections", "clearance_mm", "max_pipe_length_m", "max_elevation_m",
    "pump", "fan", "datasheet",
}


@dataclass(frozen=True)
class EquipmentRecord:
    manufacturer: str
    model: str
    equipment_type: str
    capacity_kw: float
    dimensions_mm: dict
    connections: dict
    clearance_mm: dict
    max_pipe_length_m: float
    max_elevation_m: float
    pump: dict
    fan: dict
    datasheet: dict


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ingest_datasheet(payload: dict) -> dict:
    missing = sorted(REQUIRED_FIELDS - payload.keys())
    sheet = payload.get("datasheet") or {}
    missing += [f"datasheet.{key}" for key in ("official_url", "revision", "sha256") if not sheet.get(key)]
    if missing:
        return {"status": "INPUT_REQUIRED", "missing_inputs": sorted(set(missing)), "record": None}
    if len(sheet["sha256"]) != 64:
        return {"status": "FAIL", "errors": ["datasheet.sha256 must be a 64-character digest"], "record": None}
    try:
        record = EquipmentRecord(**{key: payload[key] for key in REQUIRED_FIELDS})
    except (TypeError, ValueError) as exc:
        return {"status": "FAIL", "errors": [str(exc)], "record": None}
    return {"status": "PASS", "record": asdict(record), "catalogue_id": sha256(_canonical(asdict(record)).encode()).hexdigest()}


def design_envelope(requirements: dict, reason: str = "NO_OFFICIAL_DATASHEET") -> dict:
    """A non-manufacturer placeholder that cannot be issued as confirmed."""
    return {
        "status": "PRE_SUBMISSION", "selection_type": "DESIGN_ENVELOPE",
        "manufacturer": None, "model": None, "reason": reason,
        "minimum_capacity_kw": float(requirements["design_capacity_kw"]),
        "maximum_dimensions_mm": requirements.get("maximum_dimensions_mm"),
        "required_connections": requirements.get("connections", {}),
        "required_clearance_mm": requirements.get("clearance_mm", {}),
        "claim": "NOT_MANUFACTURER_CONFIRMED",
    }


def _constraint_errors(record: dict, requirements: dict, route: dict) -> list[str]:
    errors = []
    if record["capacity_kw"] < float(requirements["design_capacity_kw"]): errors.append("capacity")
    if route.get("status") != "PASS" or not route.get("selected"): errors.append("coordinated_route")
    else:
        if route["selected"]["length_m"] > record["max_pipe_length_m"]: errors.append("max_pipe_length")
        points = route["selected"]["points"]
        elevation = max(p[2] for p in points) - min(p[2] for p in points)
        if elevation > record["max_elevation_m"]: errors.append("max_elevation")
    required_head = float(requirements.get("pump_head_m", 0))
    if required_head and float(record.get("pump", {}).get("max_head_m", 0)) < required_head: errors.append("pump_head")
    required_flow = float(requirements.get("fan_flow_lps", 0))
    if required_flow and float(record.get("fan", {}).get("max_flow_lps", 0)) < required_flow: errors.append("fan_flow")
    for side, needed in (requirements.get("clearance_mm") or {}).items():
        if float(record.get("clearance_mm", {}).get(side, 0)) < float(needed): errors.append(f"clearance.{side}")
    return errors


def select_equipment(requirements: dict, catalogue: list[dict], route: dict) -> dict:
    if not catalogue:
        return design_envelope(requirements)
    evaluations = []
    for item in catalogue:
        ingested = ingest_datasheet(item)
        if ingested["status"] != "PASS":
            evaluations.append({"model": item.get("model"), "status": ingested["status"], "errors": ingested.get("errors", ingested.get("missing_inputs", []))})
            continue
        record = ingested["record"]
        errors = _constraint_errors(record, requirements, route)
        evaluations.append({"model": record["model"], "status": "PASS" if not errors else "FAIL", "errors": errors, "record": record})
    passing = [x for x in evaluations if x["status"] == "PASS"]
    if not passing:
        result = design_envelope(requirements, "NO_COMPLIANT_MODEL_OR_ROUTE")
        result["evaluations"] = evaluations
        return result
    chosen = min(passing, key=lambda x: (x["record"]["capacity_kw"], x["record"]["manufacturer"], x["record"]["model"]))
    return {"status": "PASS", "selection_type": "MANUFACTURER_MODEL", "record": chosen["record"],
            "evaluations": evaluations, "route_revalidated": True, "claim": "MANUFACTURER_CONFIRMED"}
