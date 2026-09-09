"""Parametric construction details and graph-native riser documentation."""
from __future__ import annotations

from hashlib import sha256
import json
import re


DETAIL_FIELDS = {"geometry", "dimensions", "fittings", "material", "clearance", "tag"}
RISER_LEVEL_TYPES = {"GROUND", "FIRST", "SECOND", "ROOF", "BASEMENT", "MEZZANINE"}


def _valid_riser_level_type(value):
    text = str(value or "").upper()
    return text in RISER_LEVEL_TYPES or bool(re.fullmatch(r"TYPICAL_[1-9]\d*_[1-9]\d*", text))
FINAL_DETAIL_FIELDS={
    "radiator_connection": {"dimensions_mm","installation_height_mm","trv","lockshield","flow_connection",
                             "return_connection","pipe_dn_mm","wall_clearance_mm","sleeve"},
    "odu_installation": {"dimensions_mm","service_clearance_mm","base","vibration_isolator","anchors",
                         "power_isolator","refrigerant_connections","drain"},
    "sanitary_connection": {"pipe_dn_mm","trap","vent","cleanout","sleeve","waterproofing","firestop"},
}

MANDATORY_DETAIL_FAMILIES = {
    "sanitary": ("sanitary_connection", "cleanout", "sanitary_riser"),
    "vent": ("vent_terminal", "vent_riser"),
    "cold_water": ("water_connection", "water_riser"),
    "hot_water": ("water_connection", "water_riser"),
    "heating": ("radiator_connection", "heating_riser"),
    "cooling": ("split_connection", "condensate_connection"),
    "gas": ("gas_connection", "gas_riser"),
    "ventilation_exhaust": ("fan_connection", "exhaust_terminal"),
    "roof_rainwater": ("roof_drain", "rainwater_riser"),
}


def required_detail_families(active_systems: dict[str, bool]) -> list[str]:
    """Return the deterministic detail coverage contract without inventing parameters."""
    families = set()
    for system, active in active_systems.items():
        if active:
            families.update(MANDATORY_DETAIL_FAMILIES.get(system, ()))
    return sorted(families)


def generate_detail(spec: dict) -> dict:
    missing = sorted(DETAIL_FIELDS - spec.keys())
    if missing:
        return {"status": "INPUT_REQUIRED", "missing_inputs": missing, "detail": None}
    if not spec["geometry"] or not spec["dimensions"] or not spec["fittings"]:
        return {"status": "FAIL", "errors": ["detail geometry, dimensions and fittings must be non-empty"], "detail": None}
    detail = {key: spec[key] for key in sorted(DETAIL_FIELDS)}
    detail["detail_id"] = spec.get("detail_id") or "DT-" + sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()[:12].upper()
    detail["source"] = "PARAMETRIC_NETWORK_MODEL"
    if spec.get("family"):
        detail["family"] = spec["family"]
    return {"status": "PASS", "detail": detail, "qa": {"executable_geometry": True, "zero_warnings": True}}


def generate_final_parametric_detail(spec: dict) -> dict:
    """Materialize system-specific construction content from governed source identities."""
    common={"family","source_plan_id","source_pmm_id","source_calc_id","parameters"}
    missing=sorted(common-set(spec or {}))
    family=(spec or {}).get('family'); parameters=(spec or {}).get('parameters') or {}
    if family not in FINAL_DETAIL_FIELDS:
        return {"status":"INPUT_REQUIRED","missing_inputs":["SUPPORTED_FINAL_DETAIL_FAMILY"],"detail":None}
    missing += [f'parameters.{key}' for key in sorted(FINAL_DETAIL_FIELDS[family]-set(parameters))]
    if family in {'radiator_connection','odu_installation'} and not spec.get('manufacturer_record'):
        missing.append('manufacturer_record')
    if missing:return {"status":"INPUT_REQUIRED","missing_inputs":sorted(set(missing)),"detail":None}
    manufacturer=spec.get('manufacturer_record') or {}
    if family in {'radiator_connection','odu_installation'}:
        if not manufacturer.get('catalogue_id') or not manufacturer.get('official_document'):
            return {"status":"INPUT_REQUIRED","missing_inputs":["OFFICIAL_MANUFACTURER_CATALOGUE_ID"],"detail":None}
        if parameters['dimensions_mm']!=manufacturer.get('dimensions_mm'):
            return {"status":"FAIL","errors":["DETAIL_DIMENSIONS_DO_NOT_MATCH_MANUFACTURER_RECORD"],"detail":None}
    empty=[key for key in FINAL_DETAIL_FIELDS[family] if parameters.get(key) in (None,'',{},[],False)]
    if empty:return {"status":"FAIL","errors":["DETAIL_EXECUTION_FIELD_EMPTY:"+','.join(sorted(empty))],"detail":None}
    geometry={"type":"PARAMETRIC_CONSTRUCTION_DETAIL","family":family,
              "envelope_mm":parameters.get('dimensions_mm') or {"pipe_dn_mm":parameters.get('pipe_dn_mm')},
              "components":[{"type":key,"value":parameters[key]} for key in sorted(FINAL_DETAIL_FIELDS[family])],
              "source_plan_id":spec['source_plan_id']}
    identity={"source_plan_id":spec['source_plan_id'],"source_pmm_id":spec['source_pmm_id'],
              "source_calc_id":spec['source_calc_id'],"manufacturer_catalogue_id":manufacturer.get('catalogue_id')}
    seed={"family":family,"parameters":parameters,"identity":identity}
    detail_id=spec.get('detail_id') or 'DT-'+sha256(json.dumps(seed,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12].upper()
    detail={"detail_id":detail_id,"family":family,"geometry":geometry,"parameters":parameters,
            "identity":identity,"manufacturer":{"manufacturer":manufacturer.get('manufacturer'),
            "model":manufacturer.get('model'),"official_document":manufacturer.get('official_document')},
            "source":"PARAMETRIC_GOVERNED_MODEL"}
    return {"status":"PASS","detail":detail,"qa":{"executable_geometry":True,"label_only":False,
            "manufacturer_confirmed":family=='sanitary_connection' or bool(manufacturer.get('catalogue_id')),
            "source_identity_complete":all(identity[key] for key in ('source_plan_id','source_pmm_id','source_calc_id'))}}


def _canonical_id(node: dict) -> str:
    if not node.get("id"):
        raise ValueError("network node id is required")
    return node["id"]


def generate_riser_from_network(network: dict) -> dict:
    nodes = network.get("nodes") or []
    edges = network.get("edges") or []
    if not nodes or not edges:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["NETWORK_GRAPH"], "riser": None}
    level_registry=network.get("levels") or []
    invalid_levels=[]
    for level in level_registry:
        if not level.get("id") or not level.get("type"):
            return {"status":"INPUT_REQUIRED","missing_inputs":["LEVEL_ID_AND_TYPE"],"riser":None}
        if not _valid_riser_level_type(level.get("type")):invalid_levels.append(str(level.get("id")))
    referenced_levels={str(value) for edge in edges for value in (edge.get("levels") or [])}
    referenced_levels.update(str(node.get("level")) for node in nodes if node.get("level") is not None)
    detail_contamination=sorted(value for value in referenced_levels if value.upper().startswith("DETAIL"))
    if invalid_levels or detail_contamination:
        bad=sorted(set(invalid_levels+detail_contamination))
        return {"status":"FAIL","errors":["INVALID_RISER_LEVEL_TYPE:"+",".join(bad)],"riser":None,
                "reconciliation":{"mismatch_count":0,"zero_mismatch":False,"invalid_levels":bad},"claim":"NOT_ISSUABLE"}
    try:
        node_ids = {_canonical_id(n) for n in nodes}
    except ValueError as exc:
        return {"status": "FAIL", "errors": [str(exc)], "riser": None}
    dangling = [e.get("id", "UNKNOWN") for e in edges if e.get("from") not in node_ids or e.get("to") not in node_ids]
    if dangling:
        return {"status": "FAIL", "errors": ["dangling_edges:" + ",".join(sorted(dangling))], "riser": None}
    rows = []
    for edge in sorted(edges, key=lambda x: x["id"]):
        identity = edge.get("calc_id") or edge["id"]
        rows.append({
            "plan_id": edge.get("plan_id", identity), "riser_id": edge.get("riser_id", identity),
            "calc_id": identity, "schedule_id": edge.get("schedule_id", identity),
            "network_edge_id": edge["id"], "from": edge["from"], "to": edge["to"], "system": edge["system"],
            "size": edge.get("size"), "material": edge.get("material"),
            "fittings": edge.get("fittings", []), "levels": edge.get("levels", []),
        })
    mismatches = [row for row in rows if len({row["plan_id"], row["riser_id"], row["calc_id"], row["schedule_id"]}) != 1]
    missing_execution = [row["plan_id"] for row in rows if not row["size"] or not row["material"]]
    status = "PASS" if not mismatches and not missing_execution else "FAIL"
    graph_hash=sha256(json.dumps({"nodes":nodes,"edges":edges,"levels":level_registry},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {
        "status": status,
        "riser": {"nodes": nodes, "segments": rows, "levels":level_registry,
                  "source_graph_id": network.get("graph_id"),"source_plan_graph_hash":graph_hash},
        "reconciliation": {"mismatch_count": len(mismatches), "mismatches": mismatches,
                           "missing_execution_data": missing_execution, "zero_mismatch": not mismatches},
        "claim": "GRAPH_DERIVED" if status == "PASS" else "NOT_ISSUABLE",
        "level_policy":"DETAIL levels forbidden; typed architectural levels only",
    }


def validate_detail_family_coverage(details: list[dict], required_families: list[str]) -> dict:
    supplied = {row.get("detail", {}).get("family") for row in details if row.get("status") == "PASS"}
    missing = sorted(set(required_families) - supplied)
    return {"status": "PASS" if not missing else "INPUT_REQUIRED", "required": sorted(set(required_families)),
            "supplied": sorted(value for value in supplied if value), "missing_inputs": [f"DETAIL_FAMILY:{x}" for x in missing]}


def generate_annotation_support(network: dict, annotations: list[dict], enlarged_plans: list[dict]) -> dict:
    """Validate identity-backed annotations and optional enlarged-plan view definitions."""
    edge_ids = {edge.get("id") for edge in network.get("edges") or []}
    annotation_ids = {row.get("network_edge_id") for row in annotations or []}
    unknown = sorted(value for value in annotation_ids - edge_ids if value)
    missing = sorted(value for value in edge_ids - annotation_ids if value)
    invalid_views = sorted(str(row.get("id") or "UNKNOWN") for row in enlarged_plans or []
                           if not row.get("bounds") or not row.get("scale") or not row.get("source_plan_id"))
    errors = []
    if unknown: errors.append("ANNOTATION_UNKNOWN_EDGE:" + ",".join(unknown))
    if invalid_views: errors.append("INVALID_ENLARGED_PLAN:" + ",".join(invalid_views))
    if errors:
        status = "FAIL"
    elif missing:
        status = "INPUT_REQUIRED"
    else:
        status = "PASS"
    return {"status": status, "errors": errors, "missing_inputs": [f"ANNOTATION:{x}" for x in missing],
            "annotations": annotations or [], "enlarged_plans": enlarged_plans or [],
            "identity_policy": "ANNOTATION_NETWORK_EDGE_ID_REQUIRED"}


def reconcile_calculation_outputs(calculation_rows: list[dict], riser: dict) -> dict:
    """Fail closed when a calculated result is orphaned or output IDs diverge."""
    calc_ids = [row.get("calc_id") for row in calculation_rows or []]
    if not calc_ids or any(not value for value in calc_ids):
        return {"status": "INPUT_REQUIRED", "errors": ["CALCULATION_IDENTITIES_MISSING"], "zero_mismatch": False}
    if len(calc_ids) != len(set(calc_ids)):
        return {"status": "FAIL", "errors": ["DUPLICATE_CALCULATION_ID"], "zero_mismatch": False}
    segments = ((riser or {}).get("riser") or {}).get("segments") or []
    output_ids = {segment.get("calc_id") for segment in segments if segment.get("calc_id")}
    orphaned = sorted(set(calc_ids) - output_ids)
    unknown = sorted(output_ids - set(calc_ids))
    identity_mismatch = [segment.get("network_edge_id") or segment.get("calc_id") for segment in segments
                         if len({segment.get("plan_id"), segment.get("riser_id"), segment.get("calc_id"), segment.get("schedule_id")}) != 1]
    errors = []
    if orphaned: errors.append("ORPHAN_CALCULATIONS:" + ",".join(orphaned))
    if unknown: errors.append("OUTPUT_WITHOUT_CALCULATION:" + ",".join(unknown))
    if identity_mismatch: errors.append("OUTPUT_IDENTITY_MISMATCH:" + ",".join(sorted(identity_mismatch)))
    return {"status": "PASS" if not errors else "FAIL", "errors": errors,
            "orphaned_calc_ids": orphaned, "unknown_output_calc_ids": unknown,
            "zero_mismatch": not errors}


def documentation_gate(details: list[dict], riser: dict, calculation_rows: list[dict] | None = None,
                       required_families: list[str] | None = None, annotation_support: dict | None = None) -> dict:
    errors = []
    for index, detail in enumerate(details):
        if detail.get("status") != "PASS": errors.append(f"detail_{index}:{detail.get('status', 'MISSING')}")
    if riser.get("status") != "PASS": errors.append(f"riser:{riser.get('status', 'MISSING')}")
    if not riser.get("reconciliation", {}).get("zero_mismatch"): errors.append("identity_mismatch")
    family_coverage = validate_detail_family_coverage(details, required_families or [])
    if family_coverage["status"] != "PASS": errors.extend(family_coverage["missing_inputs"])
    if annotation_support is not None and annotation_support.get("status") != "PASS":
        errors.extend(annotation_support.get("errors") or annotation_support.get("missing_inputs") or ["annotation_support_failed"])
    calc_reconciliation = None
    if calculation_rows is not None:
        calc_reconciliation = reconcile_calculation_outputs(calculation_rows, riser)
        if calc_reconciliation.get("status") != "PASS": errors.extend(calc_reconciliation.get("errors") or ["calculation_output_mismatch"])
    input_required = any(value.startswith(("DETAIL_FAMILY:", "ANNOTATION:")) for value in errors)
    return {"status": "PASS" if not errors else ("INPUT_REQUIRED" if input_required else "FAIL"), "errors": errors,
            "calculation_reconciliation": calc_reconciliation,
            "detail_family_coverage": family_coverage, "annotation_support": annotation_support,
            "required_identity": "PMM ID -> Calc ID = Plan ID = Riser ID = Schedule ID"}
