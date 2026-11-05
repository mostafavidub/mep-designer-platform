"""Deterministic M4/M6/M16 rainwater applicability and validation engine."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite, log10, pi, sqrt
from shapely.geometry import LineString, Point, Polygon
from shapely.affinity import translate
from shapely.ops import unary_union

from .executable_rulebook import load_rulebook_module, module_dependency_identity, rule_rows, validate_rulebook_module


PASS, FAIL, INPUT_REQUIRED, NOT_APPLICABLE = "PASS", "FAIL", "INPUT_REQUIRED", "NOT_APPLICABLE"


def _result(rule, status, *, evidence=(), missing=(), errors=(), message_fa=""):
    return {
        "rule_id": rule["rule_id"], "rule_version": rule["version"],
        "status": status, "authority": rule["authority"], "kind": rule["kind"],
        "source_ids": sorted({value for source in rule["sources"] for value in source["source_ids"]}),
        "evidence": list(evidence), "missing_inputs": sorted(set(missing)),
        "errors": sorted(set(errors)), "message_fa": message_fa,
        "llm_override_allowed": False,
    }


def _roof(snapshot): return (snapshot or {}).get("roof") or {}
def _basis(snapshot): return (snapshot or {}).get("design_basis") or {}
def _context(snapshot): return (snapshot or {}).get("rule_context") or {}
def _catchments(snapshot): return _roof(snapshot).get("catchments") or []
def _stacks(snapshot): return _roof(snapshot).get("stacks") or []


def _polygon_source_sha256(points):
    normalized=[[float(point[0]),float(point[1])] for point in points]
    return sha256(json.dumps(normalized,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()


def _nonfinite_numeric_paths(value, path="snapshot"):
    """Reject NaN/inf before any comparison can silently false-PASS."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, float):
        return [] if isfinite(value) else [path]
    if isinstance(value, str) and value.strip().lower() in {
            "nan", "+nan", "-nan", "inf", "+inf", "-inf",
            "infinity", "+infinity", "-infinity"}:
        return [path]
    if isinstance(value, dict):
        return [item for key, child in value.items()
                for item in _nonfinite_numeric_paths(child, f"{path}.{key}")]
    if isinstance(value, (list, tuple)):
        return [item for index, child in enumerate(value)
                for item in _nonfinite_numeric_paths(child, f"{path}[{index}]")]
    return []


def _flat_roof_surface_slope(rule, snapshot):
    roof_type = _roof(snapshot).get("roof_type") or _context(snapshot).get("roof_type")
    if roof_type is None: return _result(rule, INPUT_REQUIRED, missing=["roof.roof_type"])
    if roof_type != "FLAT": return _result(rule, NOT_APPLICABLE, evidence=[f"roof_type={roof_type}"])
    values = [row.get("roof_surface_slope_percent", row.get("slope_percent")) for row in _catchments(snapshot)]
    if not values or any(value is None for value in values):
        return _result(rule, INPUT_REQUIRED, missing=["catchments[].roof_surface_slope_percent"])
    minimum = float(rule["parameters"]["minimum_percent"])
    bad = [index for index, value in enumerate(values) if float(value) < minimum]
    return _result(rule, FAIL if bad else PASS, evidence=[f"roof_surface_slopes={values}"],
                   errors=[f"ROOF_SURFACE_SLOPE_BELOW_{minimum:g}_PERCENT:{i}" for i in bad])


def _main_roof_min_two(rule, snapshot):
    role = _roof(snapshot).get("roof_role") or _context(snapshot).get("roof_role")
    if role is None: return _result(rule, INPUT_REQUIRED, missing=["roof.roof_role"])
    if role in {"PENTHOUSE_ROOF", "BALCONY"}: return _result(rule, NOT_APPLICABLE, evidence=[f"roof_role={role}"])
    if role != "MAIN_ROOF": return _result(rule, NOT_APPLICABLE, evidence=[f"roof_role={role}"])
    drains = {str((row.get("drain") or {}).get("id")) for row in _catchments(snapshot) if (row.get("drain") or {}).get("id")}
    stacks = {str(row.get("id")) for row in _stacks(snapshot) if row.get("id")}
    errors = []
    if len(drains) < 2: errors.append("MAIN_ROOF_REQUIRES_AT_LEAST_TWO_DISTINCT_DRAINS")
    if len(stacks) < 2: errors.append("MAIN_ROOF_REQUIRES_AT_LEAST_TWO_DISTINCT_STACKS")
    return _result(rule, FAIL if errors else PASS, evidence=[f"drains={len(drains)}", f"stacks={len(stacks)}"], errors=errors)


def _system_separation(rule, snapshot):
    value = _context(snapshot).get("rainwater_sanitary_separation_verified")
    if value is None: return _result(rule, INPUT_REQUIRED, missing=["network.system_separation_verified"])
    return _result(rule, PASS if value is True else FAIL, evidence=[f"separation={value}"],
                   errors=[] if value is True else ["RAINWATER_NETWORK_SHARED_WITH_SANITARY_OR_VENT"])


def _emergency_shaft(rule, snapshot):
    scope = _context(snapshot).get("building_in_m4_scope")
    if scope is None: return _result(rule, INPUT_REQUIRED, missing=["project.building_in_m4_scope"])
    if scope is False: return _result(rule, NOT_APPLICABLE, evidence=["building_in_m4_scope=false"])
    shaft = _roof(snapshot).get("emergency_rainwater_shaft") or _context(snapshot).get("emergency_rainwater_shaft")
    if not shaft: return _result(rule, FAIL, errors=["EMERGENCY_RAINWATER_SHAFT_NOT_PROVIDED"])
    return _result(rule, PASS, evidence=[f"emergency_shaft={shaft.get('id') if isinstance(shaft,dict) else shaft}"])


def _secondary(rule, snapshot):
    secondary = _roof(snapshot).get("secondary_network") or {}
    routes = secondary.get("routes") or []
    discharges = secondary.get("discharge_points") or []
    elevation = secondary.get("elevation_m")
    primary = {tuple(tuple(point) for point in row.get("route") or []) for row in _catchments(snapshot)}
    if not routes or not discharges or elevation is None:
        return _result(rule, INPUT_REQUIRED, missing=[name for name, value in (
            ("secondary.routes", routes), ("secondary.discharge_points", discharges),
            ("secondary.elevation_m", elevation)) if value in (None, [], {})])
    route_shapes = {tuple(tuple(point) for point in row.get("points") or []) for row in routes}
    primary_discharge = {tuple(row.get("route", [])[-1]) for row in _catchments(snapshot) if row.get("route")}
    secondary_discharge = {tuple(row.get("point") or []) for row in discharges if row.get("point")}
    errors = []
    if primary & route_shapes: errors.append("SECONDARY_ROUTE_NOT_DISTINCT_FROM_PRIMARY")
    if primary_discharge & secondary_discharge: errors.append("SECONDARY_DISCHARGE_NOT_DISTINCT_FROM_PRIMARY")
    primary_elevation = _context(snapshot).get("primary_network_elevation_m")
    if primary_elevation is None: return _result(rule, INPUT_REQUIRED, missing=["primary_network_elevation_m"])
    if float(elevation) <= float(primary_elevation): errors.append("SECONDARY_NETWORK_NOT_ABOVE_PRIMARY")
    return _result(rule, FAIL if errors else PASS,
                   evidence=[f"secondary_routes={len(routes)}", f"secondary_discharges={len(discharges)}",
                             f"secondary_elevation_m={elevation}"], errors=errors)


def _rainfall(rule, snapshot):
    basis = _basis(snapshot); authority = (snapshot.get("draft_assumption_basis") or {}).get("rainfall_authority") or basis.get("rainfall_authority")
    missing = [name for name, value in (("rainfall_intensity_mm_h", basis.get("rainfall_intensity_mm_h")),
        ("rainfall_duration_h", basis.get("rainfall_duration_h")),
        ("rainfall_return_period_years", basis.get("rainfall_return_period_years")),
        ("rainfall_authority", authority)) if value is None]
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing)
    errors = []
    if authority != "OFFICIAL_DATA": errors.append("RAINFALL_BASIS_NOT_OFFICIAL_DATA")
    if float(basis["rainfall_duration_h"]) != 1.0: errors.append("RAINFALL_DURATION_NOT_ONE_HOUR")
    if float(basis["rainfall_return_period_years"]) < 30: errors.append("RAINFALL_RETURN_PERIOD_BELOW_30_YEARS")
    return _result(rule, FAIL if errors else PASS, evidence=[f"rainfall={basis['rainfall_intensity_mm_h']}mm/h", f"authority={authority}"], errors=errors)


def _emergency_blockage(rule, snapshot):
    secondary = _roof(snapshot).get("secondary_network") or {}
    missing=[]
    for name in ("unobstructed", "outlet_visible"):
        if secondary.get(name) is None: missing.append(f"secondary.{name}")
    structural = _context(snapshot).get("structural_rain_load_R_review")
    if structural is None: missing.append("structural.rain_load_R_review")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing)
    errors=[]
    if secondary.get("unobstructed") is not True: errors.append("EMERGENCY_PATH_OBSTRUCTED")
    if secondary.get("outlet_visible") is not True: errors.append("EMERGENCY_OUTLET_NOT_VISIBLE")
    if structural != "APPROVED": errors.append("STRUCTURAL_RAIN_LOAD_R_NOT_APPROVED")
    return _result(rule, FAIL if errors else PASS, evidence=[f"structural_review={structural}"], errors=errors)


def _drain_detail(rule, snapshot):
    drains=[row.get("drain") or {} for row in _catchments(snapshot)]
    if not drains: return _result(rule, INPUT_REQUIRED, missing=["drains"])
    fields=("strainer_height_mm","strainer_open_area_ratio","watertight_connection")
    missing=[f"drains[{i}].{key}" for i,row in enumerate(drains) for key in fields if row.get(key) is None]
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    errors=[]
    for i,row in enumerate(drains):
        if float(row["strainer_height_mm"]) < 100: errors.append(f"DRAIN_{i}_STRAINER_HEIGHT_BELOW_100_MM")
        if float(row["strainer_open_area_ratio"]) < 1.5: errors.append(f"DRAIN_{i}_STRAINER_OPEN_AREA_BELOW_1_5")
        if row["watertight_connection"] is not True: errors.append(f"DRAIN_{i}_CONNECTION_NOT_WATERTIGHT")
    return _result(rule, FAIL if errors else PASS, evidence=[f"drain_details={len(drains)}"], errors=errors)


def _horizontal_slope(rule, snapshot):
    values=[row.get("horizontal_pipe_slope_percent") for row in _catchments(snapshot) if row.get("route")]
    if not values or any(value is None for value in values):return _result(rule, INPUT_REQUIRED, missing=["segments[].horizontal_pipe_slope_percent"])
    errors=[f"HORIZONTAL_PIPE_SLOPE_BELOW_1_PERCENT:{i}" for i,value in enumerate(values) if float(value)<1]
    errors += [f"HORIZONTAL_PIPE_REVERSE_SLOPE:{i}" for i,value in enumerate(values) if float(value)<0]
    return _result(rule, FAIL if errors else PASS, evidence=[f"horizontal_pipe_slopes={values}"], errors=errors)


def _stack(rule, snapshot):
    stacks=_stacks(snapshot)
    if not stacks:return _result(rule, INPUT_REQUIRED, missing=["stacks"])
    missing=[f"stacks[{i}].{key}" for i,row in enumerate(stacks) for key in ("dn_mm","systems") if row.get(key) is None]
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    errors=[]
    for i,row in enumerate(stacks):
        if float(row["dn_mm"])<80:errors.append(f"STACK_{i}_DN_BELOW_80_MM")
        if set(row["systems"])-{"rainwater"}:errors.append(f"STACK_{i}_SHARED_WITH_OTHER_SYSTEM")
    return _result(rule, FAIL if errors else PASS, evidence=[f"stacks={len(stacks)}"], errors=errors)


def _no_reduction(rule, snapshot):
    segments=snapshot.get("calculated_segments") or []
    if not segments:return _result(rule, INPUT_REQUIRED, missing=["calculated_segments[].size_mm"])
    missing=[f"calculated_segments[{i}].{key}" for i,row in enumerate(segments)
             for key in ("size_mm","network_path_id","flow_order") if row.get(key) is None]
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    paths={}; errors=[]; evidence=[]
    for row in segments:paths.setdefault(str(row["network_path_id"]),[]).append(row)
    for path,rows in sorted(paths.items()):
        ordered=sorted(rows,key=lambda row:float(row["flow_order"]))
        sizes=[float(row["downpipe_dn_mm"] or row["size_mm"]) if row.get("downpipe_dn_mm") is not None else float(row["size_mm"]) for row in ordered]
        errors += [f"DOWNSTREAM_DIAMETER_REDUCTION:{path}:{i}" for i,(a,b) in enumerate(zip(sizes,sizes[1:])) if b<a]
        evidence.append(f"{path} ordered_sizes={sizes}")
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _appendix(rule, snapshot):
    method=_basis(snapshot).get("approved_engineering_method")
    if method is None:return _result(rule, NOT_APPLICABLE, evidence=["appendix_7_not_selected"])
    if method!="M16_APPENDIX_7":return _result(rule, NOT_APPLICABLE, evidence=[f"method={method}"])
    if _basis(snapshot).get("engineering_method_authority")!="ENGINEER_APPROVED":return _result(rule, INPUT_REQUIRED, missing=["engineering_method_authority"])
    return _result(rule, PASS, evidence=["M16 Appendix 7 selected with printed anomalies preserved"])


def _structural(rule, snapshot):
    load=_context(snapshot).get("structural_rain_load_R")
    review=_context(snapshot).get("structural_ponding_stability_review")
    if load is None or review is None:return _result(rule, INPUT_REQUIRED, missing=[name for name,value in (("structural.rain_load_R",load),("structural.ponding_stability_review",review)) if value is None])
    if review!="APPROVED":return _result(rule, FAIL, errors=["STRUCTURAL_PONDING_REVIEW_NOT_APPROVED"])
    return _result(rule, PASS, evidence=[f"structural_rain_load_R={load}","structural approval referenced"])


def _identity(rule, snapshot):
    segments=snapshot.get("calculated_segments") or []
    if not segments:return _result(rule, INPUT_REQUIRED, missing=["calculated_segments"])
    errors=[]
    for row in segments:
        values={row.get(key) for key in ("calc_id","plan_id","riser_id","schedule_id")}
        if None in values or len(values)!=1:errors.append(f"IDENTITY_MISMATCH:{row.get('id','UNKNOWN')}")
    return _result(rule, FAIL if errors else PASS, evidence=[f"segments={len(segments)}"], errors=errors)


def _full_column_pressure(rule, snapshot):
    stacks=_stacks(snapshot)
    if not stacks:return _result(rule, INPUT_REQUIRED, missing=["stacks"])
    missing=[f"stacks[{i}].{key}" for i,row in enumerate(stacks)
             for key in ("water_column_height_m","component_pressure_rating_kpa") if row.get(key) is None]
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    errors=[]; evidence=[]
    factor=float(rule["parameters"]["water_kpa_per_m"])
    for i,row in enumerate(stacks):
        required=float(row["water_column_height_m"])*factor
        rating=float(row["component_pressure_rating_kpa"])
        evidence.append(f"stack[{i}] required={required:.3f}kPa rating={rating:.3f}kPa")
        if rating<required:errors.append(f"STACK_{i}_PRESSURE_RATING_BELOW_FULL_COLUMN_HEAD")
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _forbidden_joints(rule, snapshot):
    joints=_context(snapshot).get("rainwater_joints")
    if joints is None:return _result(rule, INPUT_REQUIRED, missing=["joints[]"])
    forbidden={"CEMENT","CONCRETE","BITUMINOUS_PASTE"}; errors=[]
    for i,row in enumerate(joints):
        method=str(row.get("method") or "").upper(); materials=[str(x).upper() for x in row.get("materials") or []]
        diameters=row.get("diameters_mm") or []
        if not method or not materials or not diameters:return _result(rule, INPUT_REQUIRED, missing=[f"joints[{i}].method/materials/diameters_mm"])
        if method in forbidden:errors.append(f"JOINT_{i}_FORBIDDEN_METHOD_{method}")
        if method=="ADHESIVE" and len(set(materials))>1:errors.append(f"JOINT_{i}_UNLIKE_PLASTIC_ADHESIVE")
        if method=="RUBBER_RING" and len(set(float(x) for x in diameters))>1:errors.append(f"JOINT_{i}_UNEQUAL_DIAMETER_RUBBER_RING")
    return _result(rule, FAIL if errors else PASS, evidence=[f"joints={len(joints)}"], errors=errors)


def _cleanouts(rule, snapshot):
    cleanouts=_context(snapshot).get("cleanouts")
    segments=_context(snapshot).get("cleanout_segments")
    if cleanouts is None or segments is None:return _result(rule, INPUT_REQUIRED, missing=[k for k,v in (("cleanouts[]",cleanouts),("segments[]",segments)) if v is None])
    errors=[]
    for i,row in enumerate(cleanouts):
        for key in ("location_type","dn_mm","pipe_dn_mm","watertight","accessible"):
            if row.get(key) is None:return _result(rule, INPUT_REQUIRED, missing=[f"cleanouts[{i}].{key}"])
        minimum=float(row["pipe_dn_mm"]) if float(row["pipe_dn_mm"])<=100 else 100
        if float(row["dn_mm"])<minimum:errors.append(f"CLEANOUT_{i}_SIZE_BELOW_MINIMUM")
        if row["watertight"] is not True:errors.append(f"CLEANOUT_{i}_NOT_WATERTIGHT")
        if row["accessible"] is not True:errors.append(f"CLEANOUT_{i}_NOT_ACCESSIBLE")
    for i,row in enumerate(segments):
        if any(row.get(k) is None for k in ("dn_mm","length_m","max_cleanout_spacing_m")):
            return _result(rule, INPUT_REQUIRED, missing=[f"segments[{i}].dn_mm/length_m/max_cleanout_spacing_m"])
        limit=15 if float(row["dn_mm"])<100 else 30
        if float(row["max_cleanout_spacing_m"])>limit:errors.append(f"SEGMENT_{i}_CLEANOUT_SPACING_EXCEEDS_{limit}M")
    required={"STACK_BASE","DIRECTION_CHANGE_OVER_45","BUILDING_EXIT"}
    present={str(x.get("location_type")) for x in cleanouts}
    errors += [f"MISSING_CLEANOUT_{x}" for x in sorted(required-present)]
    return _result(rule, FAIL if errors else PASS, evidence=[f"cleanouts={len(cleanouts)}"], errors=errors)


def _environmental_protection(rule, snapshot):
    components=_context(snapshot).get("rainwater_components")
    if components is None:return _result(rule, INPUT_REQUIRED, missing=["components[]"])
    errors=[]
    for i,row in enumerate(components):
        exposures=row.get("exposures"); protections=row.get("protections")
        if exposures is None or protections is None:return _result(rule, INPUT_REQUIRED, missing=[f"components[{i}].exposures/protections"])
        missing=set(exposures)-set(protections)
        errors += [f"COMPONENT_{i}_MISSING_{x}_PROTECTION" for x in sorted(missing)]
        if "FIRE_RATED_PENETRATION" in exposures and row.get("firestop_rating") is None:
            return _result(rule, INPUT_REQUIRED, missing=[f"components[{i}].firestop_rating"])
        if row.get("material")=="PLASTIC" and row.get("above_lowest_floor") is True and row.get("fire_class") not in {"B-s1-d0","B1"}:
            errors.append(f"COMPONENT_{i}_PLASTIC_FIRE_CLASS_NOT_ACCEPTED")
    return _result(rule, FAIL if errors else PASS, evidence=[f"components={len(components)}"], errors=errors)


def _supports(rule, snapshot):
    supports=_context(snapshot).get("rainwater_supports")
    if supports is None:return _result(rule, INPUT_REQUIRED, missing=["supports[]"])
    errors=[]
    for i,row in enumerate(supports):
        needed=("spacing_m","allowed_spacing_m","full_pipe_load_included","corrosion_compatible","anchorage_approved")
        absent=[f"supports[{i}].{k}" for k in needed if row.get(k) is None]
        if absent:return _result(rule, INPUT_REQUIRED, missing=absent)
        if row.get("spacing_authority") not in {"OFFICIAL_DATA","PRODUCT_APPROVAL"}:return _result(rule, INPUT_REQUIRED, missing=[f"supports[{i}].spacing_authority"])
        if float(row["spacing_m"])>float(row["allowed_spacing_m"]):errors.append(f"SUPPORT_{i}_SPACING_EXCEEDED")
        for key in ("full_pipe_load_included","corrosion_compatible","anchorage_approved"):
            if row[key] is not True:errors.append(f"SUPPORT_{i}_{key.upper()}_FAILED")
    return _result(rule, FAIL if errors else PASS, evidence=[f"supports={len(supports)}"], errors=errors)


def _upper_roof_discharge(rule, snapshot):
    applies=_context(snapshot).get("upper_roof_discharges_to_lower_roof")
    if applies is None:return _result(rule, INPUT_REQUIRED, missing=["upper_roof_discharges_to_lower_roof"])
    if applies is False:return _result(rule, NOT_APPLICABLE, evidence=["upper_roof_discharge=false"])
    rows=_context(snapshot).get("upper_roof_discharges")
    if not rows:return _result(rule, INPUT_REQUIRED, missing=["upper_roof_discharges[]"])
    errors=[]
    for i,row in enumerate(rows):
        if row.get("elbow_configuration") not in {"ONE_90","TWO_45"}:errors.append(f"UPPER_DISCHARGE_{i}_ELBOW_CONFIGURATION_INVALID")
        if row.get("impact_protection") not in {"STONE","CONCRETE"}:errors.append(f"UPPER_DISCHARGE_{i}_IMPACT_PROTECTION_MISSING")
    return _result(rule, FAIL if errors else PASS, evidence=[f"upper_roof_discharges={len(rows)}"], errors=errors)


def _leak_test(rule, snapshot):
    stage=_context(snapshot).get("installation_stage_requires_test")
    if stage is None:return _result(rule, INPUT_REQUIRED, missing=["installation_stage_requires_test"])
    if stage is False:return _result(rule, NOT_APPLICABLE, evidence=["installation_test_stage=false"])
    tests=_context(snapshot).get("rainwater_leak_tests")
    if not tests:return _result(rule, INPUT_REQUIRED, missing=["tests[]"])
    errors=[]
    for i,row in enumerate(tests):
        needed=("full_head_height_m","highest_stack_height_m","duration_minutes","performed_before_covering","leak_detected","retest_passed")
        missing=[f"tests[{i}].{k}" for k in needed if row.get(k) is None]
        if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
        if float(row["full_head_height_m"])<float(row["highest_stack_height_m"]):errors.append(f"TEST_{i}_NOT_FULL_HEAD")
        if float(row["duration_minutes"])<15:errors.append(f"TEST_{i}_DURATION_BELOW_15_MINUTES")
        if row["performed_before_covering"] is not True:errors.append(f"TEST_{i}_PERFORMED_AFTER_COVERING")
        if row["leak_detected"] is True and row["retest_passed"] is not True:errors.append(f"TEST_{i}_LEAK_NOT_CLEARED_BY_RETEST")
    return _result(rule, FAIL if errors else PASS, evidence=[f"physical_tests={len(tests)}"], errors=errors)


def _material_certificate_marking(rule, snapshot):
    components=_context(snapshot).get("rainwater_components")
    if components is None:return _result(rule, INPUT_REQUIRED, missing=["rainwater_components[]"])
    if not components:return _result(rule, INPUT_REQUIRED, missing=["rainwater_components[]"])
    missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(components):
        for key in ("manufacturer_mark_permanent","standard_mark_permanent","certificate"):
            if row.get(key) is None:missing.append(f"rainwater_components[{i}].{key}")
        certificate=row.get("certificate") or {}
        for key in ("id","issuer","issuer_competent","standard","product_identity"):
            if certificate.get(key) in (None,""):missing.append(f"rainwater_components[{i}].certificate.{key}")
        provenance=certificate.get("evidence_provenance") or {}
        for key in ("source_sha256","verification_authority","verified_at","verification_status"):
            if provenance.get(key) in (None,""):missing.append(f"rainwater_components[{i}].certificate.evidence_provenance.{key}")
        if row.get("manufacturer_mark_permanent") is False:errors.append(f"COMPONENT_{i}_MANUFACTURER_MARK_NOT_PERMANENT")
        if row.get("standard_mark_permanent") is False:errors.append(f"COMPONENT_{i}_STANDARD_MARK_NOT_PERMANENT")
        if certificate and certificate.get("issuer_competent") is False:errors.append(f"COMPONENT_{i}_CERTIFICATE_ISSUER_NOT_COMPETENT")
        if provenance.get("verification_status") not in (None,"VALID"):errors.append(f"COMPONENT_{i}_CERTIFICATE_EVIDENCE_NOT_VALID")
        if certificate.get("product_identity") not in (None,row.get("product_identity")):
            errors.append(f"COMPONENT_{i}_CERTIFICATE_PRODUCT_IDENTITY_MISMATCH")
        if certificate.get("id"):evidence.append(f"component[{i}] certificate={certificate['id']}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _appendix7_effective_area(rule, snapshot):
    if _basis(snapshot).get("approved_engineering_method") != "M16_APPENDIX_7":
        return _result(rule, NOT_APPLICABLE, evidence=["appendix_7_not_selected"])
    catchments=_catchments(snapshot)
    if not catchments:return _result(rule, INPUT_REQUIRED, missing=["catchments[]"])
    missing=[]; errors=[]; evidence=[]; identities={str(row.get("id")) for row in catchments}
    calculated={str(row.get("catchment_id")):row for row in snapshot.get("calculated_catchments") or []}
    for i,row in enumerate(catchments):
        walls=row.get("contributing_wall_areas_m2"); transfers=row.get("upstream_transfer_ids")
        if walls is None:missing.append(f"catchments[{i}].contributing_wall_areas_m2")
        if transfers is None:missing.append(f"catchments[{i}].upstream_transfer_ids"); continue
        if len(transfers)!=len(set(str(x) for x in transfers)):errors.append(f"CATCHMENT_{i}_UPSTREAM_TRANSFER_DUPLICATE")
        unknown=set(str(x) for x in transfers)-identities
        errors += [f"CATCHMENT_{i}_UPSTREAM_TRANSFER_UNKNOWN:{x}" for x in sorted(unknown)]
        if str(row.get("id")) in set(str(x) for x in transfers):errors.append(f"CATCHMENT_{i}_SELF_TRANSFER")
        if walls is not None and any(float(x)<0 for x in walls):errors.append(f"CATCHMENT_{i}_NEGATIVE_CONTRIBUTING_WALL_AREA")
        result=calculated.get(str(row.get("id")))
        if result:evidence.append(f"{row.get('id')} effective_area_m2={result.get('effective_area_m2')}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence or [f"catchments={len(catchments)}"], errors=errors)


def _appendix7_complete_sizing(rule, snapshot):
    if _basis(snapshot).get("approved_engineering_method") != "M16_APPENDIX_7":
        return _result(rule, NOT_APPLICABLE, evidence=["appendix_7_not_selected"])
    if _basis(snapshot).get("engineering_method_authority") != "ENGINEER_APPROVED":
        return _result(rule, INPUT_REQUIRED, missing=["engineering_method_authority"])
    rainfall=_basis(snapshot).get("rainfall_intensity_mm_h")
    rows=snapshot.get("calculated_catchments")
    if rainfall is None or rows is None:return _result(rule, INPUT_REQUIRED, missing=[k for k,v in (("rainfall_intensity_mm_h",rainfall),("calculated_catchments[]",rows)) if v is None])
    if not rows:return _result(rule, INPUT_REQUIRED, missing=["calculated_catchments[]"])
    errors=[]; evidence=[]
    for i,row in enumerate(rows):
        appendix=row.get("appendix7_evidence")
        if not appendix:return _result(rule, INPUT_REQUIRED, missing=[f"calculated_catchments[{i}].appendix7_evidence"])
        if row.get("drain_dn_mm") is None or row.get("downpipe_dn_mm") is None:errors.append(f"CATCHMENT_{i}_APPENDIX7_CAPACITY_UNRESOLVED")
        if float(appendix.get("base_rainfall_mm_h",0))!=25.4:errors.append(f"CATCHMENT_{i}_APPENDIX7_BASE_RAINFALL_CHANGED")
        if row.get("downpipe_dn_mm")==250 and appendix.get("horizontal_slope_percent")==4.0 and appendix.get("printed_anomaly_preserved") is not True:
            errors.append(f"CATCHMENT_{i}_DN250_PRINTED_ANOMALY_NOT_PRESERVED")
        evidence.append(f"{row.get('catchment_id')} vertical=DN{row.get('drain_dn_mm')} horizontal=DN{row.get('downpipe_dn_mm')}")
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _trench_burial(rule, snapshot):
    rows=_context(snapshot).get("buried_gravity_rainwater_segments")
    if rows is None:return _result(rule, INPUT_REQUIRED, missing=["buried_gravity_rainwater_segments[]"])
    if not rows:return _result(rule, NOT_APPLICABLE, evidence=["no_buried_gravity_rainwater_segments"])
    errors=[]; missing=[]; evidence=[]
    for i,row in enumerate(rows):
        for key in ("id","soil_condition","continuous_shaped_bedding","balanced_compaction","lift_mm","inspection_before_covering"):
            if row.get(key) is None:missing.append(f"buried_segments[{i}].{key}")
        if row.get("affects_excavation_depth") is None:missing.append(f"buried_segments[{i}].affects_excavation_depth")
        if row.get("affects_excavation_depth") is True:
            geometry_hash=row.get("excavation_geometry_sha256")
            response=row.get("m7_geotechnical_excavation_response") or {};provenance=response.get("evidence_provenance") or {}
            if not geometry_hash:missing.append(f"buried_segments[{i}].excavation_geometry_sha256")
            for key in ("response_id","excavation_geometry_sha256","status"):
                if response.get(key) in (None,""):missing.append(f"buried_segments[{i}].m7_geotechnical_excavation_response.{key}")
            if response.get("excavation_geometry_sha256")!=geometry_hash:errors.append(f"BURIED_SEGMENT_{i}_M7_GEOMETRY_HASH_MISMATCH")
            if response.get("status")!="APPROVED":errors.append(f"BURIED_SEGMENT_{i}_M7_EXCAVATION_NOT_APPROVED")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
                missing.append(f"buried_segments[{i}].m7_geotechnical_excavation_response.valid_provenance")
        if row.get("continuous_shaped_bedding") is False:errors.append(f"BURIED_SEGMENT_{i}_BEDDING_NOT_CONTINUOUS")
        if row.get("balanced_compaction") is False:errors.append(f"BURIED_SEGMENT_{i}_COMPACTION_NOT_BALANCED")
        if row.get("inspection_before_covering") is False:errors.append(f"BURIED_SEGMENT_{i}_INSPECTION_AFTER_COVERING")
        if row.get("lift_mm") is not None and float(row["lift_mm"])>150:errors.append(f"BURIED_SEGMENT_{i}_LIFT_EXCEEDS_150_MM")
        condition=row.get("soil_condition")
        if condition=="ROCK" and row.get("rock_overcut_mm") is None:missing.append(f"buried_segments[{i}].rock_overcut_mm")
        elif condition=="ROCK" and float(row["rock_overcut_mm"])<75:errors.append(f"BURIED_SEGMENT_{i}_ROCK_OVERCUT_BELOW_75_MM")
        if condition=="WEAK" and row.get("weak_soil_overexcavation_diameters") is None:missing.append(f"buried_segments[{i}].weak_soil_overexcavation_diameters")
        elif condition=="WEAK" and float(row["weak_soil_overexcavation_diameters"])<2:errors.append(f"BURIED_SEGMENT_{i}_WEAK_SOIL_OVEREXCAVATION_BELOW_2D")
        evidence.append(f"buried_segment={row.get('id')} soil={condition}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _discharge_boundary_destination(rule, snapshot):
    rows=_context(snapshot).get("rainwater_discharge_destinations")
    if rows is None:return _result(rule, INPUT_REQUIRED, missing=["rainwater_discharge_destinations[]"])
    if not rows:return _result(rule, INPUT_REQUIRED, missing=["rainwater_discharge_destinations[]"])
    errors=[]; missing=[]; evidence=[]
    forbidden={"ADJACENT_PROPERTY","PUBLIC_WAY","BUILDING_FACADE"}
    for i,row in enumerate(rows):
        for key in ("id","destination_type","inside_property","causes_nuisance"):
            if row.get(key) is None:missing.append(f"discharge_destinations[{i}].{key}")
        destination=row.get("destination_type")
        if destination in forbidden:errors.append(f"DISCHARGE_{i}_FORBIDDEN_DESTINATION_{destination}")
        if row.get("inside_property") is False:errors.append(f"DISCHARGE_{i}_OUTSIDE_PROPERTY")
        if row.get("causes_nuisance") is True:errors.append(f"DISCHARGE_{i}_CAUSES_NUISANCE")
        if destination=="OWN_PROPERTY_SURFACE":
            permit=row.get("permit")
            if not isinstance(permit,dict) or not permit.get("id"):
                missing.append(f"discharge_destinations[{i}].permit.id")
            elif permit.get("status")!="APPROVED":errors.append(f"DISCHARGE_{i}_PERMIT_NOT_APPROVED")
        evidence.append(f"discharge={row.get('id')} destination={destination}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _permanent_rainwater_dead_load(rule, snapshot):
    rows=_context(snapshot).get("structural_rainwater_loads")
    if rows is None:return _result(rule, INPUT_REQUIRED, missing=["structural_rainwater_loads[]"])
    if not rows:return _result(rule, INPUT_REQUIRED, missing=["structural_rainwater_loads[]"])
    errors=[]; missing=[]; evidence=[]
    for i,row in enumerate(rows):
        for key in ("component_id","empty_component_mass_kg","contained_water_volume_m3","water_full_mass_kg","support_reaction_id","declared_total_reaction_kn","structural_review"):
            if row.get(key) in (None,""):missing.append(f"structural_rainwater_loads[{i}].{key}")
        empty=row.get("empty_component_mass_kg"); full=row.get("water_full_mass_kg")
        if empty is not None and float(empty)<0:errors.append(f"STRUCTURAL_LOAD_{i}_NEGATIVE_EMPTY_MASS")
        if empty is not None and full is not None and float(full)<float(empty):errors.append(f"STRUCTURAL_LOAD_{i}_FULL_MASS_BELOW_EMPTY_MASS")
        volume=row.get("contained_water_volume_m3")
        if volume is not None and float(volume)<0:errors.append(f"STRUCTURAL_LOAD_{i}_NEGATIVE_WATER_VOLUME")
        if empty is not None and full is not None and volume is not None:
            calculated=float(empty)+1000.0*float(volume)
            if abs(float(full)-calculated)>.01:errors.append(f"STRUCTURAL_LOAD_{i}_FULL_MASS_DENSITY_CALC_MISMATCH")
            calculated_reaction=calculated*9.80665/1000.0;declared_reaction=row.get("declared_total_reaction_kn")
            if declared_reaction is not None and abs(float(declared_reaction)-calculated_reaction)>.001:errors.append(f"STRUCTURAL_LOAD_{i}_REACTION_NOT_DERIVED_FROM_CALCULATED_MASS")
            evidence.append(f"component={row.get('component_id')} water_volume_m3={float(volume):.4f} density_kg_m3=1000 calculated_full_mass_kg={calculated:.2f} calculated_reaction_kn={calculated_reaction:.4f}")
        review=row.get("structural_review") or {}
        if not isinstance(review,dict) or not review.get("approval_id"):missing.append(f"structural_rainwater_loads[{i}].structural_review.approval_id")
        elif review.get("status")!="APPROVED":errors.append(f"STRUCTURAL_LOAD_{i}_REVIEW_NOT_APPROVED")
        if empty is not None and volume is not None:
            reviewed_load=review.get("reviewed_load_kn");calculated_load=(float(empty)+1000.0*float(volume))*9.80665/1000.0
            if reviewed_load is None:missing.append(f"structural_rainwater_loads[{i}].structural_review.reviewed_load_kn")
            elif abs(float(reviewed_load)-calculated_load)>.001:errors.append(f"STRUCTURAL_LOAD_{i}_STRUCTURAL_REVIEW_LOAD_MISMATCH")
        evidence.append(f"component={row.get('component_id')} full_mass_kg={full} reaction={row.get('support_reaction_id')}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

def _architectural_waterproofing_interface(rule, snapshot):
    rows=_context(snapshot).get("waterproofing_interfaces")
    if rows is None:return _result(rule, INPUT_REQUIRED, missing=["waterproofing_interfaces[]"])
    if not rows:return _result(rule, INPUT_REQUIRED, missing=["waterproofing_interfaces[].verified_absence"])
    errors=[];missing=[];evidence=[]
    applicable={"FLAT_ROOF","TERRACE","SEMI_OPEN"}
    for i,row in enumerate(rows):
        for key in ("entity_id","source_geometry_id","surface_type"):
            if not row.get(key):missing.append(f"waterproofing_interfaces[{i}].{key}")
        if row.get("surface_type")=="LOW_EXPOSURE_BALCONY":
            if not row.get("exposure_classification_evidence_id"):missing.append(f"waterproofing_interfaces[{i}].exposure_classification_evidence_id")
            evidence.append(f"waterproofing={row.get('entity_id')} low_exposure_exception")
            continue
        if row.get("surface_type") not in applicable:errors.append(f"WATERPROOFING_{i}_SURFACE_TYPE_INVALID")
        for key in ("membrane_continuous","drain_penetration_sealed","upstand_detail_id"):
            if row.get(key) in (None,""):missing.append(f"waterproofing_interfaces[{i}].{key}")
        if row.get("membrane_continuous") is False:errors.append(f"WATERPROOFING_{i}_MEMBRANE_DISCONTINUITY")
        if row.get("drain_penetration_sealed") is False:errors.append(f"WATERPROOFING_{i}_DRAIN_PENETRATION_UNSEALED")
        evidence.append(f"waterproofing={row.get('entity_id')} source={row.get('source_geometry_id')}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

def _basement_entry_runoff_protection(rule, snapshot):
    context=_context(snapshot); rows=context.get("basement_openings")
    if rows is None:return _result(rule, INPUT_REQUIRED, missing=["basement_openings[]"])
    if not rows:
        if context.get("basement_openings_verified_absent") is True:return _result(rule, NOT_APPLICABLE, evidence=["basement_openings_verified_absent"])
        return _result(rule, INPUT_REQUIRED, missing=["basement_openings_verified_absent"])
    errors=[];missing=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("entity_id","source_geometry_id","opening_type","runoff_interceptor_id","surface_water_entry_prevented","below_grade_waterproofing_continuous"):
            if row.get(key) in (None,""):missing.append(f"basement_openings[{i}].{key}")
        if row.get("surface_water_entry_prevented") is False:errors.append(f"BASEMENT_OPENING_{i}_SURFACE_WATER_ENTRY")
        if row.get("below_grade_waterproofing_continuous") is False:errors.append(f"BASEMENT_OPENING_{i}_WATERPROOFING_DISCONTINUITY")
        evidence.append(f"basement_opening={row.get('entity_id')} interceptor={row.get('runoff_interceptor_id')}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

def _shaft_access_private_route(rule, snapshot):
    rows=_context(snapshot).get("rainwater_route_entities")
    if rows is None or not rows:return _result(rule, INPUT_REQUIRED, missing=["rainwater_route_entities[]"])
    errors=[];missing=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("route_id","source_geometry_id","owner_unit_id","route_points","private_space_polygons","accessible_everywhere"):
            if row.get(key) in (None,""):missing.append(f"rainwater_route_entities[{i}].{key}")
        points=row.get("rerouted_route_points") if row.get("rerouted_route_id") else row.get("route_points")
        if row.get("rerouted_route_id") and not points:missing.append(f"rainwater_route_entities[{i}].rerouted_route_points")
        if points and len(points)<2:errors.append(f"ROUTE_{i}_GEOMETRY_INVALID")
        if points and len(points)>=2:
            line=LineString(points)
            for zone in row.get("private_space_polygons") or []:
                polygon=zone.get("polygon") or []
                if len(polygon)<3:missing.append(f"rainwater_route_entities[{i}].private_space_polygons[].polygon");continue
                if zone.get("unit_id") not in (None,row.get("owner_unit_id")) and line.intersection(Polygon(polygon)).length>1e-9:
                    errors.append(f"ROUTE_{i}_CROSSES_OTHER_UNIT_PRIVATE_ZONE")
        if row.get("accessible_everywhere") is False:errors.append(f"ROUTE_{i}_NOT_ACCESSIBLE")
        if row.get("in_shaft"):
            for key in ("shaft_id","shaft_access_panel_id","shaft_interior_finish_smooth"):
                if row.get(key) in (None,""):missing.append(f"rainwater_route_entities[{i}].{key}")
            if row.get("shaft_interior_finish_smooth") is False:errors.append(f"ROUTE_{i}_SHAFT_FINISH_NOT_SMOOTH")
        evidence.append(f"route={row.get('route_id')} source={row.get('source_geometry_id')} rendered_geometry={'REROUTE' if row.get('rerouted_route_id') else 'ORIGINAL'}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

def _suspended_ceiling_clearance_separation(rule, snapshot):
    context=_context(snapshot);rows=context.get("suspended_ceiling_route_interfaces")
    if rows is None:return _result(rule, INPUT_REQUIRED, missing=["suspended_ceiling_route_interfaces[]"])
    if not rows:
        if context.get("suspended_ceiling_interfaces_verified_absent") is True:return _result(rule, NOT_APPLICABLE, evidence=["suspended_ceiling_interfaces_verified_absent"])
        return _result(rule, INPUT_REQUIRED, missing=["suspended_ceiling_interfaces_verified_absent"])
    errors=[];missing=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("interface_id","source_geometry_id","structural_soffit_elevation_m","finished_ceiling_elevation_m","minimum_legal_clear_height_m","independent_pipe_support","no_ceiling_contact","partition_continuity","fire_protection_continuity"):
            if row.get(key) is None:missing.append(f"suspended_ceiling_route_interfaces[{i}].{key}")
        ceiling=row.get("finished_ceiling_elevation_m"); floor=row.get("finished_floor_elevation_m",0); minimum=row.get("minimum_legal_clear_height_m")
        if ceiling is not None and minimum is not None and float(ceiling)-float(floor)<float(minimum):errors.append(f"CEILING_{i}_CLEAR_HEIGHT_BELOW_MINIMUM")
        for key in ("independent_pipe_support","no_ceiling_contact","partition_continuity","fire_protection_continuity"):
            if row.get(key) is False:errors.append(f"CEILING_{i}_{key.upper()}_FALSE")
        evidence.append(f"ceiling={row.get('interface_id')} clear_height_m={None if ceiling is None else float(ceiling)-float(floor)}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

def _pitched_roof_property_safety(rule, snapshot):
    roof=_roof(snapshot);roof_type=roof.get("roof_type")
    if roof_type is None:return _result(rule, INPUT_REQUIRED, missing=["roof.roof_type"])
    if roof_type!="PITCHED":return _result(rule, NOT_APPLICABLE, evidence=[f"roof_type={roof_type}"])
    context=_context(snapshot);group=context.get("building_group");floors=context.get("building_floor_count")
    edges=context.get("pitched_roof_edges")
    missing=[];errors=[];evidence=[]
    if group is None:missing.append("building_group")
    if floors is None:missing.append("building_floor_count")
    if edges is None or not edges:missing.append("pitched_roof_edges[]")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    for i,row in enumerate(edges):
        for key in ("edge_id","edge_points","boundary_points","slopes_toward_boundary","snow_ice_retention","worker_safety_anchor_id"):
            if row.get(key) in (None,""):missing.append(f"pitched_roof_edges[{i}].{key}")
        if not row.get("snow_ice_retention"):errors.append(f"PITCHED_EDGE_{i}_SNOW_ICE_RETENTION_MISSING")
        if row.get("slopes_toward_boundary"):
            if len(row.get("edge_points") or [])<2 or len(row.get("boundary_points") or [])<2:
                missing.append(f"pitched_roof_edges[{i}].boundary_geometry")
            else:
                distance=LineString(row["edge_points"]).distance(LineString(row["boundary_points"]))
                if int(group)<=5:minimum=.2
                elif int(group)<=7:minimum=.2+.1*max(0,int(floors)-4)
                else:
                    approval=row.get("group8_special_approval") or {}
                    if not approval.get("id"):missing.append(f"pitched_roof_edges[{i}].group8_special_approval.id")
                    minimum=float(approval.get("minimum_setback_m",0))
                if distance+1e-9<minimum:errors.append(f"PITCHED_EDGE_{i}_PROPERTY_SETBACK_BELOW_{minimum:.3f}M")
                evidence.append(f"pitched_edge={row.get('edge_id')} setback_m={distance:.3f} minimum_m={minimum:.3f}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

def _exterior_space_drainage(rule,snapshot):
    c=_context(snapshot);rows=c.get("exterior_drainage_spaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["exterior_drainage_spaces[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["exterior_drainage_spaces_verified_absent"]) if c.get("exterior_drainage_spaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["exterior_drainage_spaces_verified_absent"])
    errors=[];missing=[];evidence=[]
    for i,r in enumerate(rows):
        for k in ("space_id","space_type","polygon","surface_elevation_points","drain_point","drain_elevation_m","route_points","destination_type"):
            if r.get(k) in (None,""):missing.append(f"exterior_drainage_spaces[{i}].{k}")
        polygon=r.get("polygon") or [];drain=r.get("drain_point") or [];route=r.get("route_points") or []
        if len(polygon)>=3 and len(drain)==2 and not Polygon(polygon).covers(Point(drain)):errors.append(f"EXTERIOR_SPACE_{i}_DRAIN_OUTSIDE_POLYGON")
        if len(route)<2 or len(drain)!=2 or Point(route[0]).distance(Point(drain))>1e-9:errors.append(f"EXTERIOR_SPACE_{i}_ROUTE_NOT_CONNECTED_TO_DRAIN")
        if r.get("drain_elevation_m") is not None:
            for point in r.get("surface_elevation_points") or []:
                if len(point)!=3:missing.append(f"exterior_drainage_spaces[{i}].surface_elevation_points[].xyz")
                elif float(point[2])<=float(r["drain_elevation_m"]):errors.append(f"EXTERIOR_SPACE_{i}_SURFACE_NOT_ABOVE_DRAIN")
        if r.get("destination_type")=="PUBLIC_WAY":errors.append(f"EXTERIOR_SPACE_{i}_PUBLIC_WAY_DISCHARGE")
        if r.get("ponding_free") is False:errors.append(f"EXTERIOR_SPACE_{i}_PONDING")
        if r.get("space_type")=="EXTERIOR_EGRESS" and r.get("non_slip") is not True:errors.append(f"EXTERIOR_SPACE_{i}_NOT_NON_SLIP")
        if r.get("space_type")=="SUNKEN_COURTYARD":
            if r.get("roofed") is not False:errors.append(f"EXTERIOR_SPACE_{i}_SUNKEN_COURTYARD_ROOFED")
            if not r.get("cleaning_access_id"):missing.append(f"exterior_drainage_spaces[{i}].cleaning_access_id")
        evidence.append(f"space={r.get('space_id')} type={r.get('space_type')} destination={r.get('destination_type')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _parking_surface_runoff(rule,snapshot):
    c=_context(snapshot);rows=c.get("parking_drainage_areas")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["parking_drainage_areas[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["parking_verified_absent"]) if c.get("parking_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["parking_verified_absent"])
    errors=[];missing=[];evidence=[]
    for i,r in enumerate(rows):
        for k in ("area_id","polygon","surface_elevation_points","drain_point","drain_elevation_m","route_points"):
            if r.get(k) in (None,""):missing.append(f"parking_drainage_areas[{i}].{k}")
        polygon=r.get("polygon") or [];drain=r.get("drain_point") or [];route=r.get("route_points") or []
        if len(polygon)>=3 and len(drain)==2 and not Polygon(polygon).covers(Point(drain)):errors.append(f"PARKING_{i}_DRAIN_OUTSIDE_POLYGON")
        if len(route)<2 or len(drain)!=2 or Point(route[0]).distance(Point(drain))>1e-9:errors.append(f"PARKING_{i}_ROUTE_NOT_CONNECTED_TO_DRAIN")
        if r.get("drain_elevation_m") is not None:
            for point in r.get("surface_elevation_points") or []:
                if len(point)!=3:missing.append(f"parking_drainage_areas[{i}].surface_elevation_points[].xyz")
                elif float(point[2])<=float(r["drain_elevation_m"]):errors.append(f"PARKING_{i}_SURFACE_NOT_ABOVE_DRAIN")
        if r.get("ponding_free") is False:errors.append(f"PARKING_{i}_PONDING")
        if r.get("at_ground_floor_entrance"):
            if r.get("entrance_crest_above_exterior_m") is None:missing.append(f"parking_drainage_areas[{i}].entrance_crest_above_exterior_m")
            elif float(r["entrance_crest_above_exterior_m"])<=0 and not (r.get("approved_alternative") or {}).get("id"):errors.append(f"PARKING_{i}_RUNOFF_ENTRY_NOT_PREVENTED")
        evidence.append(f"parking={r.get('area_id')} drain={r.get('drain_point')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _installation_protection_penetrations(rule,snapshot):
    context=_context(snapshot);rows=context.get("rainwater_installation_interfaces")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["rainwater_installation_interfaces[]"])
    missing=[];errors=[];evidence=[]
    for i,r in enumerate(rows):
        for k in ("interface_id","source_geometry_id","interface_type"):
            if r.get(k) in (None,""):missing.append(f"rainwater_installation_interfaces[{i}].{k}")
        kind=r.get("interface_type")
        if kind in {"FOUNDATION_OR_BEARING_WALL","STRUCTURAL_OPENING"}:
            for k in ("sleeve_or_clearance_detail_id","structural_approval"):
                if r.get(k) in (None,""):missing.append(f"rainwater_installation_interfaces[{i}].{k}")
            approval=r.get("structural_approval") or {}; provenance=approval.get("evidence_provenance") or {}
            if not approval.get("id") or provenance.get("verification_status")!="VALID":missing.append(f"rainwater_installation_interfaces[{i}].structural_approval.valid_provenance")
        if kind in {"CORROSIVE_ENVIRONMENT","VEHICLE_IMPACT_ZONE","BURIED_EXTERNAL"} and not r.get("protection_detail_id"):missing.append(f"rainwater_installation_interfaces[{i}].protection_detail_id")
        if kind=="ELEVATOR_SHAFT":errors.append(f"INSTALLATION_{i}_RAINWATER_IN_ELEVATOR_SHAFT")
        if kind=="DAMAGED_BUILDING_ASSEMBLY" and not r.get("restoration_detail_id"):missing.append(f"rainwater_installation_interfaces[{i}].restoration_detail_id")
        if kind=="FOUNDATION_ADJACENT_TRENCH":
            if r.get("outside_45_degree_influence_line") is None:missing.append(f"rainwater_installation_interfaces[{i}].outside_45_degree_influence_line")
            elif not r.get("outside_45_degree_influence_line"):errors.append(f"INSTALLATION_{i}_TRENCH_INSIDE_FOUNDATION_INFLUENCE")
        if kind=="OUTLET_OPENING" and not r.get("grate_detail_id"):missing.append(f"rainwater_installation_interfaces[{i}].grate_detail_id")
        if kind in {"EXTERNAL_WALL_PENETRATION","EXTERNAL_ROOF_PENETRATION"}:
            model_hash=context.get("building_geometry_sha256")
            if not model_hash:missing.append("building_geometry_sha256")
            reviews=r.get("assembly_continuity_reviews")
            if not isinstance(reviews,list) or not reviews:
                missing.append(f"rainwater_installation_interfaces[{i}].assembly_continuity_reviews[]")
            else:
                required={"FIRE","ACOUSTIC"} if kind=="EXTERNAL_WALL_PENETRATION" else {"FIRE","ACOUSTIC","THERMAL"}
                if r.get("multilayer_assembly"):required.add("LAYER_INTEGRITY")
                indexed={review.get("discipline"):review for review in reviews}
                for discipline in sorted(required):
                    review=indexed.get(discipline)
                    if not review:
                        missing.append(f"rainwater_installation_interfaces[{i}].assembly_continuity_reviews[{discipline}]")
                        continue
                    provenance=review.get("evidence_provenance") or {}
                    for key in ("review_id","assembly_id","detail_id"):
                        if not review.get(key):missing.append(f"rainwater_installation_interfaces[{i}].assembly_continuity_reviews[{discipline}].{key}")
                    if review.get("model_sha256")!=model_hash:errors.append(f"INSTALLATION_{i}_{discipline}_MODEL_HASH_MISMATCH")
                    if review.get("status")!="PASS":errors.append(f"INSTALLATION_{i}_{discipline}_CONTINUITY_NOT_APPROVED")
                    if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
                        missing.append(f"rainwater_installation_interfaces[{i}].assembly_continuity_reviews[{discipline}].valid_provenance")
                evidence.append(f"assembly={r.get('source_geometry_id')} reviews={','.join(sorted(required))}")
        if r.get("imposed_pressure_within_component_rating") is False:errors.append(f"INSTALLATION_{i}_PRESSURE_EXCEEDS_RATING")
        evidence.append(f"installation_interface={r.get('interface_id')} type={kind}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _nonpotable_separation_backflow(rule,snapshot):
    c=_context(snapshot);rows=c.get("nonpotable_reuse_connections")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["nonpotable_reuse_connections[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["nonpotable_connections_verified_absent"]) if c.get("nonpotable_connections_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["nonpotable_connections_verified_absent"])
    missing=[];errors=[];evidence=[]
    for i,r in enumerate(rows):
        for k in ("connection_id","connection_type","potable_network_separate","nonpotable_identification"):
            if r.get(k) in (None,""):missing.append(f"nonpotable_reuse_connections[{i}].{k}")
        if r.get("potable_network_separate") is not True:errors.append(f"NONPOTABLE_{i}_POTABLE_NETWORK_NOT_SEPARATE")
        if r.get("connection_type")=="OPEN_DRAIN_DISCHARGE":
            if r.get("air_gap_mm") is None:missing.append(f"nonpotable_reuse_connections[{i}].air_gap_mm")
            elif float(r["air_gap_mm"])<150:errors.append(f"NONPOTABLE_{i}_AIR_GAP_BELOW_150_MM")
        elif r.get("connection_type") in {"POTABLE_MAKEUP","HOSE_BIB","PRESSURIZED_EQUIPMENT","TREATMENT_FEED"}:
            device=r.get("backflow_device") or {}; provenance=device.get("evidence_provenance") or {}
            for k in ("product_identity","standard","device_type","accessible"):
                if device.get(k) in (None,""):missing.append(f"nonpotable_reuse_connections[{i}].backflow_device.{k}")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"nonpotable_reuse_connections[{i}].backflow_device.valid_provenance")
            if device.get("accessible") is False:errors.append(f"NONPOTABLE_{i}_BACKFLOW_DEVICE_NOT_ACCESSIBLE")
        elif r.get("connection_type")=="DIRECT_POTABLE_TO_NONPOTABLE":errors.append(f"NONPOTABLE_{i}_DIRECT_CONNECTION_FORBIDDEN")
        evidence.append(f"nonpotable_connection={r.get('connection_id')} type={r.get('connection_type')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _documentation_and_stage_closeout(rule,snapshot):
    c=_context(snapshot); docs=c.get("rainwater_documentation")
    if not docs:return _result(rule,INPUT_REQUIRED,missing=["rainwater_documentation"])
    required=("plans","riser_diagram","drains","pipe_routes","diameters","lengths","materials",
              "flow_directions","slopes","cleanouts","outlet_elevation","installation_method",
              "protection_method","maintenance_method","design_pressure","standard_symbols")
    missing=[f"rainwater_documentation.{k}" for k in required if not docs.get(k)]
    stage=c.get("project_stage")
    if stage is None:missing.append("project_stage")
    if stage in {"CONSTRUCTION","FINAL_INSPECTION"}:
        approval=docs.get("supervisor_approval") or {}; provenance=approval.get("evidence_provenance") or {}
        if not approval.get("id") or provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
            missing.append("rainwater_documentation.supervisor_approval.valid_provenance")
    if stage=="FINAL_INSPECTION":
        for k in ("final_inspection","nonconformities_corrected","operation_maintenance_manual"):
            evidence=docs.get(k) or {}; provenance=evidence.get("evidence_provenance") or {}
            if not evidence.get("id") or provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
                missing.append(f"rainwater_documentation.{k}.valid_provenance")
        if c.get("building_high_rise") is None:missing.append("building_high_rise")
        elif c.get("building_high_rise") is True:
            retention=docs.get("high_rise_management_room_retention") or {}
            provenance=retention.get("evidence_provenance") or {}
            for k in ("retention_id","rainwater_as_built_artifact_sha256","roof_access_key_register_id"):
                if retention.get(k) in (None,""):missing.append(f"rainwater_documentation.high_rise_management_room_retention.{k}")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
                missing.append("rainwater_documentation.high_rise_management_room_retention.valid_provenance")
    return _result(rule,INPUT_REQUIRED if missing else PASS,missing=missing,
                   evidence=[f"documentation_stage={stage}"])

def _roof_equipment_overflow(rule,snapshot):
    c=_context(snapshot); rows=c.get("roof_equipment_overflows")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["roof_equipment_overflows[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["roof_equipment_verified_absent"]) if c.get("roof_equipment_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["roof_equipment_verified_absent"])
    missing=[];errors=[];evidence=[]
    for i,r in enumerate(rows):
        for k in ("equipment_id","equipment_type","route_points","receptor_type"):
            if r.get(k) in (None,"",[]):missing.append(f"roof_equipment_overflows[{i}].{k}")
        if r.get("discharges_loose_on_roof"):errors.append(f"ROOF_EQUIPMENT_{i}_OVERFLOW_LOOSE_ON_ROOF")
        if r.get("receptor_type")=="ROOF_RAINWATER_DRAIN" and r.get("equipment_type")!="EVAPORATIVE_COOLER":
            errors.append(f"ROOF_EQUIPMENT_{i}_RAINWATER_DRAIN_RECEPTOR_FORBIDDEN")
        evidence.append(f"roof_equipment={r.get('equipment_id')} receptor={r.get('receptor_type')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _remaining_material_route_support(rule,snapshot):
    c=_context(snapshot); rows=c.get("rainwater_route_installation_records")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["rainwater_route_installation_records[]"])
    missing=[];errors=[];evidence=[]
    for i,r in enumerate(rows):
        for k in ("route_id","gravity_flow_verified","parallel_to_building_surfaces","standard_fittings",
                  "joint_watertight","fire_resistant_material","product_standard","support_system"):
            if r.get(k) in (None,""):missing.append(f"rainwater_route_installation_records[{i}].{k}")
        for k,err in (("gravity_flow_verified","NOT_GRAVITY_FLOW"),("parallel_to_building_surfaces","NOT_PARALLEL_TO_SURFACES"),
                      ("standard_fittings","NONSTANDARD_OR_BENT_FITTING"),("joint_watertight","JOINT_NOT_WATERTIGHT"),
                      ("fire_resistant_material","MATERIAL_NOT_FLAME_RESISTANT")):
            if r.get(k) is False:errors.append(f"ROUTE_{i}_{err}")
        if r.get("embedded_in_concrete") and not (r.get("short_unavoidable_crossing") and r.get("repair_access_detail_id")):
            errors.append(f"ROUTE_{i}_EMBEDDED_IN_CONCRETE")
        if r.get("crosses_expansion_joint") and not (r.get("basement_expansion_joint") or r.get("smooth_expansion_piece_id")):
            errors.append(f"ROUTE_{i}_EXPANSION_JOINT_PIECE_MISSING")
        if r.get("plastic_vertical"):
            support=r.get("support_system") or {}
            for k in ("clamp_type","clamp_material","longitudinal_movement_allowed","manufacturer_instruction_id"):
                if not support.get(k):missing.append(f"rainwater_route_installation_records[{i}].support_system.{k}")
        evidence.append(f"route_installation={r.get('route_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _adjacent_system_conditional_protection(rule,snapshot):
    c=_context(snapshot); missing=[];errors=[];evidence=[]
    if c.get("demolition_with_city_water_or_sewer_connection"):
        for k in ("utility_notification_evidence","utility_disconnection_evidence"):
            e=c.get(k) or {};p=e.get("evidence_provenance") or {}
            if not e.get("id") or p.get("verification_status")!="VALID" or not p.get("source_sha256"):missing.append(f"{k}.valid_provenance")
    elif c.get("demolition_verified_absent") is not True:missing.append("demolition_with_city_water_or_sewer_connection_or_verified_absent")
    potable=c.get("potable_makeup_components")
    if potable:
        for i,e in enumerate(potable):
            cert=e.get("health_certificate") or {};p=cert.get("evidence_provenance") or {}
            if not cert.get("id") or p.get("verification_status")!="VALID" or not p.get("source_sha256"):missing.append(f"potable_makeup_components[{i}].health_certificate.valid_provenance")
    elif c.get("potable_makeup_verified_absent") is not True:missing.append("potable_makeup_components_or_verified_absent")
    tanks=c.get("potable_storage_tanks")
    if tanks:
        for i,t in enumerate(tanks):
            if t.get("flood_or_groundwater_exposed"):errors.append(f"POTABLE_TANK_{i}_FLOOD_OR_GROUNDWATER_EXPOSURE")
            if t.get("rainwater_or_nonpotable_pipe_above"):errors.append(f"POTABLE_TANK_{i}_NONPOTABLE_PIPE_ABOVE")
    elif c.get("potable_storage_tanks_verified_absent") is not True:missing.append("potable_storage_tanks_or_verified_absent")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence or ["conditional_adjacent_systems_verified"],errors=errors)

def _owner_module_compliance_dependency(rule,snapshot):
    owner=rule["parameters"]["owner_module"]
    record=(_context(snapshot).get("interdisciplinary_compliance") or {}).get(owner) or {}
    provenance=record.get("evidence_provenance") or {}
    missing=[]
    if record.get("status") is None:missing.append(f"interdisciplinary_compliance.{owner}.status")
    if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
        missing.append(f"interdisciplinary_compliance.{owner}.valid_provenance")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    if record.get("status")!="PASS":return _result(rule,FAIL,evidence=[f"{owner}_status={record.get('status')}"] ,errors=[f"{owner.upper()}_OWNER_MODULE_NOT_PASS"])
    return _result(rule,PASS,evidence=[f"{owner}_status=PASS",f"{owner}_evidence={provenance.get('source_sha256')}"])

def _roof_access_parapet_geometry(rule,snapshot):
    c=_context(snapshot);r=c.get("roof_access_safety")
    if not r:return _result(rule,INPUT_REQUIRED,missing=["roof_access_safety"])
    missing=[];errors=[]
    for k in ("storeys_above_ground","roof_slope_percent","roof_use","access_type","roof_accessible"):
        if r.get(k) is None:missing.append(f"roof_access_safety.{k}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    storeys=int(r["storeys_above_ground"]);slope=float(r["roof_slope_percent"])
    public_stair_required=storeys>=4 and slope<=33 and r["roof_use"]!="NO_USE"
    if public_stair_required and r.get("access_type")!="PUBLIC_STAIR":errors.append("PUBLIC_STAIR_TO_ROOF_REQUIRED")
    if r.get("access_type")=="PUBLIC_STAIR":
        for k in ("stair_headhouse_area_m2","stair_enclosure_area_m2"):
            if r.get(k) is None:missing.append(f"roof_access_safety.{k}")
        if not missing and float(r["stair_headhouse_area_m2"])>float(r["stair_enclosure_area_m2"]):errors.append("STAIR_HEADHOUSE_EXCEEDS_STAIR_ENCLOSURE")
    parapet_required=bool(r["roof_accessible"]) or (slope==0 and r.get("access_type")=="PUBLIC_STAIR")
    if parapet_required:
        if r.get("parapet_height_m") is None:missing.append("roof_access_safety.parapet_height_m")
        elif float(r["parapet_height_m"])<1.10:errors.append("ACCESSIBLE_ROOF_PARAPET_BELOW_1_10_M")
        polygon=r.get("parapet_polygon") or []
        roof_polygon=r.get("roof_polygon") or []
        if len(polygon)<3 or len(roof_polygon)<3:missing.extend([k for k,v in (("roof_access_safety.parapet_polygon",polygon),("roof_access_safety.roof_polygon",roof_polygon)) if len(v)<3])
        elif not Polygon(polygon).covers(Polygon(roof_polygon)):errors.append("PARAPET_DOES_NOT_ENCLOSE_ACCESSIBLE_ROOF")
        segments=r.get("parapet_edge_segments")
        if segments is None:missing.append("roof_access_safety.parapet_edge_segments[]")
        elif len(roof_polygon)>=3:
            declared={frozenset((tuple(s.get("start") or []),tuple(s.get("end") or []))) for s in segments
                      if len(s.get("start") or [])==2 and len(s.get("end") or [])==2 and float(s.get("height_m") or 0)>=1.10}
            for i,a in enumerate(roof_polygon):
                b=roof_polygon[(i+1)%len(roof_polygon)]
                if frozenset((tuple(a),tuple(b))) not in declared:errors.append(f"PARAPET_EDGE_{i}_NOT_CONTINUOUS_OR_TOO_LOW")
            for i,s in enumerate(segments):
                if s.get("opening"):
                    opening=s.get("opening_geometry") or {};guard=s.get("opening_guard_geometry") or {}
                    if not s.get("opening_guard_id") or any(len((opening.get(k) or []))!=2 for k in ("start","end")) or any(len((guard.get(k) or []))!=2 for k in ("start","end")):
                        missing.append(f"roof_access_safety.parapet_edge_segments[{i}].opening_guard_geometry")
                    else:
                        opening_line=LineString([opening["start"],opening["end"]]);guard_line=LineString([guard["start"],guard["end"]])
                        if float(guard.get("height_m") or 0)<1.10 or not guard_line.buffer(1e-6).covers(opening_line):errors.append(f"PARAPET_EDGE_{i}_OPENING_GUARD_GEOMETRY_INSUFFICIENT")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=[f"roof_access={r.get('access_type')}",f"parapet_height_m={r.get('parapet_height_m')}",f"storeys={storeys}"],errors=errors)

def _entrance_landing_threshold(rule,snapshot):
    rows=_context(snapshot).get("entrance_landing_interfaces")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["entrance_landing_interfaces[]"])
    missing=[];errors=[];evidence=[]
    prohibited={"EDUCATIONAL_CULTURAL","HEALTHCARE_CARE","ASSEMBLY"}
    for i,r in enumerate(rows):
        for k in ("entrance_id","inside_landing_elevation_mm","outside_landing_elevation_mm","threshold_top_elevation_mm","accessible_route","required_egress","occupancy_group","exterior_door"):
            if r.get(k) is None:missing.append(f"entrance_landing_interfaces[{i}].{k}")
        if any(r.get(k) is None for k in ("inside_landing_elevation_mm","outside_landing_elevation_mm","threshold_top_elevation_mm")):continue
        inside=float(r["inside_landing_elevation_mm"]);outside=float(r["outside_landing_elevation_mm"]);top=float(r["threshold_top_elevation_mm"])
        if abs(inside-outside)>1e-6:errors.append(f"ENTRANCE_{i}_LANDINGS_NOT_SAME_LEVEL")
        drop=max(top-inside,top-outside)
        if r.get("occupancy_group") in prohibited and r.get("threshold_present"):errors.append(f"ENTRANCE_{i}_PUBLIC_OCCUPANCY_THRESHOLD_FORBIDDEN")
        if r.get("accessible_route") or r.get("required_egress"):
            if drop>20:errors.append(f"ENTRANCE_{i}_THRESHOLD_DROP_ABOVE_20_MM")
        elif r.get("exterior_door"):
            if r.get("approved_step_height_mm") is None:missing.append(f"entrance_landing_interfaces[{i}].approved_step_height_mm")
            elif drop>float(r["approved_step_height_mm"]):errors.append(f"ENTRANCE_{i}_EXTERIOR_DROP_ABOVE_ONE_APPROVED_STEP")
        elif drop>38:errors.append(f"ENTRANCE_{i}_THRESHOLD_DROP_ABOVE_38_MM")
        evidence.append(f"entrance={r.get('entrance_id')} drop_mm={drop}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _rain_on_snow_load_case(rule,snapshot):
    r=_context(snapshot).get("rain_on_snow_load_case")
    if not r:return _result(rule,INPUT_REQUIRED,missing=["rain_on_snow_load_case"])
    missing=[f"rain_on_snow_load_case.{k}" for k in ("snow_region","roof_slope_deg","slope_run_w_m","balanced_snow_load_kn_m2","rain_surcharge_kn_m2","simultaneous_effects") if r.get(k) is None]
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    region=int(r["snow_region"]);threshold=float(r["slope_run_w_m"])/15.0;slope=float(r["roof_slope_deg"])
    applies=region in {2,3} and slope<threshold;errors=[]
    if applies and abs(float(r["rain_surcharge_kn_m2"])-0.25)>1e-9:errors.append("RAIN_ON_SNOW_SURCHARGE_NOT_0_25_KN_M2")
    if not applies and abs(float(r["rain_surcharge_kn_m2"]))>1e-9:errors.append("RAIN_ON_SNOW_SURCHARGE_APPLIED_OUTSIDE_SCOPE")
    forbidden={"DRIFT","SLIDING_SNOW","UNBALANCED_SNOW","PARTIAL_SNOW"}
    simultaneous=set(r.get("simultaneous_effects") or [])
    if applies and forbidden&simultaneous:errors.append("RAIN_ON_SNOW_COMBINED_WITH_FORBIDDEN_SNOW_EFFECT")
    total=float(r["balanced_snow_load_kn_m2"])+(0.25 if applies else 0.0)
    declared=r.get("declared_combined_load_kn_m2")
    if declared is None:return _result(rule,INPUT_REQUIRED,missing=["rain_on_snow_load_case.declared_combined_load_kn_m2"])
    if abs(float(declared)-total)>1e-9:errors.append("RAIN_ON_SNOW_COMBINED_LOAD_MISMATCH")
    return _result(rule,FAIL if errors else PASS,evidence=[f"region={region}",f"slope={slope}<threshold={threshold}:{applies}",f"combined_load={total}kN/m2"],errors=errors)

def _roof_service_live_loads(rule,snapshot):
    c=_context(snapshot);rows=c.get("roof_service_live_loads")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["roof_service_live_loads[]"])
    minima={"NORMAL_ROOF":(1.5,1.3),"LIGHT_ROOF":(0.5,1.3),"ROOF_GARDEN":(5.0,None),"FABRIC_ROOF":(0.25,1.3),"SERVICE_WALKWAY":(2.0,1.3),"AHU_ROOM":(5.0,None)}
    missing=[];errors=[];evidence=[]
    for i,r in enumerate(rows):
        kind=r.get("load_area_type")
        if kind is None:missing.append(f"roof_service_live_loads[{i}].load_area_type");continue
        if kind=="FIXED_LADDER":
            for k in ("ladder_length_m","point_load_kn","point_load_spacing_m"):
                if r.get(k) is None:missing.append(f"roof_service_live_loads[{i}].{k}")
            if r.get("point_load_kn") is not None and float(r["point_load_kn"])<1.35:errors.append(f"ROOF_LOAD_{i}_LADDER_POINT_LOAD_BELOW_1_35_KN")
            if r.get("point_load_spacing_m") is not None and float(r["point_load_spacing_m"])>3:errors.append(f"ROOF_LOAD_{i}_LADDER_POINT_SPACING_ABOVE_3_M")
            if r.get("rails_extend_above_support") and float(r.get("extension_point_load_kn") or 0)<0.45:errors.append(f"ROOF_LOAD_{i}_LADDER_EXTENSION_LOAD_BELOW_0_45_KN")
        elif kind in minima:
            uniform,point=minima[kind]
            if r.get("uniform_load_kn_m2") is None:missing.append(f"roof_service_live_loads[{i}].uniform_load_kn_m2")
            elif float(r["uniform_load_kn_m2"])<uniform:errors.append(f"ROOF_LOAD_{i}_UNIFORM_BELOW_{uniform:g}_KN_M2")
            if point is not None:
                if r.get("concentrated_load_kn") is None:missing.append(f"roof_service_live_loads[{i}].concentrated_load_kn")
                elif float(r["concentrated_load_kn"])<point:errors.append(f"ROOF_LOAD_{i}_CONCENTRATED_BELOW_{point:g}_KN")
            if kind=="AHU_ROOM" and r.get("manufacturer_recommended_load_kn_m2") is not None and float(r["uniform_load_kn_m2"])<float(r["manufacturer_recommended_load_kn_m2"]):errors.append(f"ROOF_LOAD_{i}_BELOW_MANUFACTURER_RECOMMENDATION")
            if r.get("reduced_uniform_load_kn_m2") is not None and float(r["reduced_uniform_load_kn_m2"])<1 and r.get("integrity_member") and not r.get("adverse_pattern_check_id"):missing.append(f"roof_service_live_loads[{i}].adverse_pattern_check_id")
        else:errors.append(f"ROOF_LOAD_{i}_UNKNOWN_AREA_TYPE")
        evidence.append(f"roof_load={r.get('area_id')} type={kind}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _material_standard_joint_detail(rule,snapshot):
    rows=_context(snapshot).get("rainwater_material_installations")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["rainwater_material_installations[]"])
    standards={"CAST_IRON_HUBLESS":{"ISIRI 2367","DIN 19522","ISO 6594"},"GALVANIZED_STEEL":{"ISIRI 423","ISO 65","EN 10255","ASTM A53/A53M SCH40"},"UPVC":{"ISIRI 12142-1","ISIRI 13361","ISIRI 9119","ASTM D2665","EN 1329","ISO 3633","ISO 1452"},"PP":{"EN 1451"},"HDPE":{"EN 1519","ISO 8770"}}
    allowed_joint={"CAST_IRON_HUBBED":{"OAKUM_LEAD"},"CAST_IRON_HUBLESS":{"RUBBER_SLEEVE_STAINLESS_CLAMP"},"GALVANIZED_STEEL":{"THREADED"},"UPVC":{"SOLVENT_CEMENT_COLD","RUBBER_RING_PUSH_FIT"},"HDPE":{"HEAT_FUSION"}}
    missing=[];errors=[];evidence=[]
    for i,r in enumerate(rows):
        material=r.get("material");standard=r.get("standard");joint=r.get("joint_method")
        for k in ("installation_id","material","standard","fitting_standard_compatible","smooth_internal_bore","joint_method","manufacturer_instruction_id"):
            if r.get(k) in (None,""):missing.append(f"rainwater_material_installations[{i}].{k}")
        if material in standards and standard not in standards[material] and not (r.get("equivalent_standard_approval") or {}).get("id"):errors.append(f"MATERIAL_{i}_STANDARD_NOT_ALLOWED_OR_APPROVED")
        if not r.get("fitting_standard_compatible"):errors.append(f"MATERIAL_{i}_FITTING_STANDARD_INCOMPATIBLE")
        if not r.get("smooth_internal_bore"):errors.append(f"MATERIAL_{i}_INTERNAL_BORE_OBSTRUCTION")
        if material in allowed_joint and joint not in allowed_joint[material]:errors.append(f"MATERIAL_{i}_JOINT_METHOD_INVALID")
        if r.get("buried"):
            marking=str(r.get("burial_marking") or "")
            if material=="GALVANIZED_STEEL":errors.append(f"MATERIAL_{i}_GALVANIZED_STEEL_BURIED_FORBIDDEN")
            if material in {"UPVC","PP"} and marking not in {"D","BD"}:errors.append(f"MATERIAL_{i}_BURIAL_MARKING_D_OR_BD_REQUIRED")
            if material=="HDPE" and marking!="BD":errors.append(f"MATERIAL_{i}_HDPE_BURIAL_MARKING_BD_REQUIRED")
        if material=="PP" and float(r.get("water_column_height_m") or 0)>6:errors.append(f"MATERIAL_{i}_PP_ABOVE_6M_WATER_COLUMN_FORBIDDEN")
        if material=="UPVC" and joint=="SOLVENT_CEMENT_COLD" and float(r.get("ambient_temperature_c") or -999)<5 and not r.get("manufacturer_low_temperature_approval_id"):errors.append(f"MATERIAL_{i}_UPVC_ADHESIVE_BELOW_5C")
        if material=="CAST_IRON_HUBBED":
            if float(r.get("lead_depth_mm") or 0)<25:errors.append(f"MATERIAL_{i}_LEAD_DEPTH_BELOW_25_MM")
            if float(r.get("lead_recess_mm") or 999)>3:errors.append(f"MATERIAL_{i}_LEAD_RECESS_ABOVE_3_MM")
            if r.get("joint_covered_before_test"):errors.append(f"MATERIAL_{i}_JOINT_COVERED_BEFORE_TEST")
        evidence.append(f"material_installation={r.get('installation_id')} {material}/{standard}/{joint}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _material_support_installation_detail(rule, snapshot):
    rows = _context(snapshot).get("rainwater_material_support_installations")
    if rows is None or not rows:
        return _result(rule, INPUT_REQUIRED, missing=["rainwater_material_support_installations[]"])
    missing=[]; errors=[]; evidence=[]
    allowed = {
        ("CAST_IRON", "VERTICAL"): ({"CLAMP"}, {"STEEL_PROFILE", "CAST_IRON"}),
        ("GALVANIZED_STEEL", "VERTICAL"): ({"CLAMP", "U_BOLT", "HANGER", "STEEL_FRAME"}, {"STEEL_PROFILE", "MALLEABLE_CAST_IRON", "BRASS"}),
        ("CAST_IRON", "HORIZONTAL"): ({"HANGER", "WALL_BRACKET", "U_BOLT"}, {"STEEL_PROFILE", "CAST_IRON"}),
        ("GALVANIZED_STEEL", "HORIZONTAL"): ({"HANGER", "WALL_BRACKET", "CLAMP", "U_BOLT", "METAL_ASSEMBLY"}, {"STEEL_PROFILE", "MALLEABLE_CAST_IRON", "BRASS"}),
        ("PLASTIC", "HORIZONTAL"): ({"CLAMP", "U_BOLT"}, {"STEEL", "PLASTIC"}),
    }
    for i,row in enumerate(rows):
        prefix=f"rainwater_material_support_installations[{i}]"
        for key in ("installation_id","material_group","orientation","clamp_type","clamp_material",
                    "support_connected_to_building","longitudinal_movement_allowed"):
            if row.get(key) in (None, ""):
                missing.append(f"{prefix}.{key}")
        pair=(row.get("material_group"),row.get("orientation"))
        if pair not in allowed:
            errors.append(f"SUPPORT_{i}_UNSUPPORTED_MATERIAL_ORIENTATION")
            continue
        clamp_types, clamp_materials=allowed[pair]
        if row.get("clamp_type") not in clamp_types:errors.append(f"SUPPORT_{i}_CLAMP_TYPE_INVALID")
        if row.get("clamp_material") not in clamp_materials:errors.append(f"SUPPORT_{i}_CLAMP_MATERIAL_INVALID")
        if not row.get("support_connected_to_building"):errors.append(f"SUPPORT_{i}_NOT_CONNECTED_TO_BUILDING")
        if row.get("thermal_movement_expected") and not row.get("longitudinal_movement_allowed"):
            errors.append(f"SUPPORT_{i}_THERMAL_MOVEMENT_RESTRAINED")
        if pair == ("CAST_IRON", "VERTICAL"):
            if not row.get("base_below_lowest_elbow"):errors.append(f"SUPPORT_{i}_BASE_NOT_BELOW_LOWEST_ELBOW")
            if row.get("base_bearing") not in {"CONCRETE", "BRICK_CEMENT", "STRUCTURAL_STEEL"}:
                errors.append(f"SUPPORT_{i}_BASE_BEARING_INVALID")
            if not row.get("near_hub_or_joint"):errors.append(f"SUPPORT_{i}_CLAMP_NOT_NEAR_HUB_OR_JOINT")
        if pair == ("CAST_IRON", "HORIZONTAL"):
            if not row.get("near_hub_or_joint"):errors.append(f"SUPPORT_{i}_CLAMP_NOT_NEAR_HUB_OR_JOINT")
            if row.get("buried_in_soil") and not row.get("continuous_sand_bedding"):
                errors.append(f"SUPPORT_{i}_BURIED_CAST_IRON_WITHOUT_SAND_BEDDING")
        if pair[0] == "GALVANIZED_STEEL" and row.get("clamp_over_insulation"):
            if float(row.get("steel_liner_thickness_mm") or 0) < 1.5:
                errors.append(f"SUPPORT_{i}_INSULATION_LINER_BELOW_1_5_MM")
            if float(row.get("steel_liner_length_mm") or 0) < 300:
                errors.append(f"SUPPORT_{i}_INSULATION_LINER_BELOW_300_MM")
        if pair == ("GALVANIZED_STEEL", "HORIZONTAL"):
            if not row.get("fixed_points_anchored") or not row.get("other_points_guided"):
                errors.append(f"SUPPORT_{i}_FIXED_AND_GUIDED_POINTS_INCOMPLETE")
            if row.get("thermal_movement_expected") and not row.get("pendular_movement_allowed"):
                errors.append(f"SUPPORT_{i}_PENDULAR_MOVEMENT_REQUIRED")
        evidence.append(f"support_installation={row.get('installation_id')} {pair[0]}/{pair[1]}")
    if missing:return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _potable_outlet_air_gap(rule, snapshot):
    c=_context(snapshot);rows=c.get("potable_outlets_over_rainwater_receptors")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["potable_outlets_over_rainwater_receptors[]"])
    if not rows:
        return _result(rule,NOT_APPLICABLE,evidence=["potable_outlets_over_rainwater_receptors_verified_absent"]) if c.get("potable_outlets_over_rainwater_receptors_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["potable_outlets_over_rainwater_receptors_verified_absent"])
    fixed={"LAVATORY_SIMILAR":(15,25,40),"GOOSENECK_SINK_LAUNDRY":(20,40,65),"TUB_FILLER_SIMILAR":(25,50,80),"DRINKING_OTHER":(15,25,40)}
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for k in ("outlet_id","outlet_group","effective_diameter_mm","near_wall","vertical_air_gap_mm"):
            if row.get(k) in (None,""):missing.append(f"potable_outlets_over_rainwater_receptors[{i}].{k}")
        if any(row.get(k) in (None,"") for k in ("outlet_group","effective_diameter_mm","near_wall","vertical_air_gap_mm")):continue
        group=row["outlet_group"];diameter=float(row["effective_diameter_mm"]);near=bool(row["near_wall"]);gap=float(row["vertical_air_gap_mm"])
        if group=="POTABLE_STORAGE_TANK":minimum=100.0
        elif group=="OVER_25_MM":minimum=diameter*(3 if near else 2)
        elif group in fixed:
            limit,far_min,near_min=fixed[group]
            if diameter>limit:errors.append(f"AIR_GAP_{i}_DIAMETER_EXCEEDS_GROUP_LIMIT")
            minimum=float(near_min if near else far_min)
        else:errors.append(f"AIR_GAP_{i}_UNKNOWN_OUTLET_GROUP");continue
        if gap<minimum:errors.append(f"AIR_GAP_{i}_BELOW_{minimum:g}_MM")
        evidence.append(f"potable_outlet={row.get('outlet_id')} minimum={minimum:g}mm actual={gap:g}mm")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _lrfd_rainwater_load_combinations(rule, snapshot):
    row=_context(snapshot).get("structural_rainwater_load_combinations")
    if not row:return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_load_combinations"])
    effects=row.get("load_effects") or {};required=("D","L","Lr","S","R","W","E")
    missing=[f"structural_rainwater_load_combinations.load_effects.{key}" for key in required if effects.get(key) is None]
    for key in ("effect_type","effect_unit","direction_convention","capacity_mode","design_capacity_abs",
                "evaluated_cases","governing_case_id","structural_analysis_id","wind_and_seismic_combined","live_load_factor_basis"):
        if row.get(key) in (None,"",{}):missing.append(f"structural_rainwater_load_combinations.{key}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    compatible={"FORCE":{"kN"},"MOMENT":{"kN_m"},"STRESS":{"kPa","MPa"},"PRESSURE":{"kPa","MPa"}}
    if row["effect_type"] not in compatible or row["effect_unit"] not in compatible.get(row["effect_type"],set()):
        return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_load_combinations.compatible_effect_type_and_unit"])
    if row["capacity_mode"]!="SYMMETRIC_ABSOLUTE":
        return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_load_combinations.signed_capacity_envelope"])
    D,L,Lr,S,R,W,E=(float(effects[k]) for k in required)
    basis=row.get("live_load_factor_basis") or {}
    for key in ("nominal_live_load_kpa","occupancy_type","live_load_reduction_applied","declared_factor"):
        if basis.get(key) is None:missing.append(f"structural_rainwater_load_combinations.live_load_factor_basis.{key}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    eligible=float(basis["nominal_live_load_kpa"])<5 and basis["occupancy_type"] not in ("PARKING","PUBLIC_ASSEMBLY") and basis["live_load_reduction_applied"] is False
    live_factor=.5 if eligible else 1.0
    errors=[]
    if abs(float(basis["declared_factor"])-live_factor)>1e-9:errors.append("LRFD_LIVE_LOAD_FACTOR_MISMATCH")
    Lc=L*live_factor
    cases={"LRFD-1":1.4*D,"LRFD-2-LR":1.2*D+1.6*L+.5*Lr,"LRFD-2-S":1.2*D+1.6*L+.5*S,"LRFD-2-R":1.2*D+1.6*L+.5*R,
        "LRFD-3-LR-L":1.2*D+1.6*Lr+Lc,"LRFD-3-S-L":1.2*D+1.6*S+Lc,"LRFD-3-R-L":1.2*D+1.6*R+Lc}
    for sign,label in ((1,"POS"),(-1,"NEG")):
        cases.update({f"LRFD-3-LR-W-{label}":1.2*D+1.6*Lr+sign*.8*W,
            f"LRFD-3-S-W-{label}":1.2*D+1.6*S+sign*.8*W,f"LRFD-3-R-W-{label}":1.2*D+1.6*R+sign*.8*W,
            f"LRFD-4-LR-W-{label}":1.2*D+sign*1.6*W+Lc+.5*Lr,
            f"LRFD-4-S-W-{label}":1.2*D+sign*1.6*W+Lc+.5*S,f"LRFD-4-R-W-{label}":1.2*D+sign*1.6*W+Lc+.5*R,
            f"LRFD-5-E-{label}":1.2*D+sign*E+Lc+.2*S,f"LRFD-6-W-{label}":.9*D+sign*1.6*W,
            f"LRFD-7-E-{label}":.9*D+sign*E})
    declared=row["evaluated_cases"]
    if row.get("wind_and_seismic_combined") is not False:errors.append("WIND_AND_SEISMIC_EFFECTS_MUST_BE_EVALUATED_SEPARATELY")
    for case_id,effect in cases.items():
        if case_id not in declared:errors.append("LOAD_COMBINATION_MISSING:"+case_id)
        elif abs(float(declared[case_id])-effect)>1e-6:errors.append("LOAD_COMBINATION_MISMATCH:"+case_id)
    governing=max(cases,key=lambda key:abs(cases[key]))
    if row["governing_case_id"]!=governing:errors.append("GOVERNING_LOAD_COMBINATION_MISMATCH")
    if float(row["design_capacity_abs"])<abs(cases[governing]):errors.append("DESIGN_CAPACITY_BELOW_GOVERNING_EFFECT")
    return _result(rule,FAIL if errors else PASS,evidence=[f"live_factor={live_factor:g} eligible={eligible}",f"governing={governing}",f"effect={cases[governing]:.6g}{row['effect_unit']}",f"analysis={row['structural_analysis_id']}"],errors=errors)


def _asd_rainwater_load_combinations(rule, snapshot):
    row=_context(snapshot).get("structural_rainwater_asd_combinations")
    if not row:return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_asd_combinations"])
    effects=row.get("load_effects") or {};required=("D","L","Lr","S","R","W","E")
    missing=[f"structural_rainwater_asd_combinations.load_effects.{key}" for key in required if effects.get(key) is None]
    for key in ("effect_type","effect_unit","direction_convention","capacity_mode","allowable_capacity_abs",
                "evaluated_cases","governing_case_id","structural_analysis_id","allowable_stress_increase","wind_and_seismic_combined"):
        if row.get(key) is None or row.get(key) in ("",{}):missing.append(f"structural_rainwater_asd_combinations.{key}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    compatible={"FORCE":{"kN"},"MOMENT":{"kN_m"},"STRESS":{"kPa","MPa"},"PRESSURE":{"kPa","MPa"}}
    if row["effect_type"] not in compatible or row["effect_unit"] not in compatible.get(row["effect_type"],set()):
        return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_asd_combinations.compatible_effect_type_and_unit"])
    if row["capacity_mode"]!="SYMMETRIC_ABSOLUTE":
        return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_asd_combinations.signed_capacity_envelope"])
    D,L,Lr,S,R,W,E=(float(effects[k]) for k in required)
    cases={"ASD-1":D,"ASD-2":D+L}
    for alt,value in (("LR",Lr),("S",S),("R",R)):
        cases[f"ASD-3-{alt}"]=D+value
        cases[f"ASD-4-{alt}"]=D+.75*L+.75*value
    for sign,label in ((1,"POS"),(-1,"NEG")):
        cases[f"ASD-5-W-{label}"]=D+sign*W
        for alt,value in (("LR",Lr),("S",S),("R",R)):
            cases[f"ASD-6-{alt}-W-{label}"]=D+.75*L+sign*.75*W+.75*value
        cases[f"ASD-7-E-{label}"]=D+sign*.7*E
        cases[f"ASD-8-E-{label}"]=D+.75*L+sign*.75*.7*E+.75*S
        cases[f"ASD-9-W-{label}"]=.6*D+sign*W
        cases[f"ASD-10-E-{label}"]=.6*D+sign*.7*E
    declared=row["evaluated_cases"];errors=[]
    if row.get("wind_and_seismic_combined") is not False:errors.append("ASD_WIND_AND_SEISMIC_EFFECTS_MUST_BE_EVALUATED_SEPARATELY")
    for case_id,effect in cases.items():
        if case_id not in declared:errors.append("ASD_LOAD_COMBINATION_MISSING:"+case_id)
        elif abs(float(declared[case_id])-effect)>1e-6:errors.append("ASD_LOAD_COMBINATION_MISMATCH:"+case_id)
    governing=max(cases,key=lambda key:abs(cases[key]))
    if row["governing_case_id"]!=governing:errors.append("ASD_GOVERNING_LOAD_COMBINATION_MISMATCH")
    if float(row["allowable_capacity_abs"])<abs(cases[governing]):errors.append("ALLOWABLE_CAPACITY_BELOW_GOVERNING_EFFECT")
    if row["allowable_stress_increase"] is not False:errors.append("ALLOWABLE_STRESS_INCREASE_PROHIBITED")
    return _result(rule,FAIL if errors else PASS,evidence=[f"governing={governing}",f"effect={cases[governing]:.6g}{row['effect_unit']}",f"analysis={row['structural_analysis_id']}"],errors=errors)


def _primary_blockage_rain_load_and_ponding(rule, snapshot):
    rows=_context(snapshot).get("roof_primary_blockage_rain_loads")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["roof_primary_blockage_rain_loads[]"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("roof_area_id","undeformed_roof_elevation_mm","secondary_inlet_elevation_mm",
                    "hydraulic_head_mm","declared_rain_load_kn_m2","primary_blocked",
                    "roof_slope_percent","primary_blockage_can_retain_water","full_snow_load_kn_m2",
                    "structural_analysis_id"):
            if row.get(key) is None or row.get(key)=="":missing.append(f"roof_primary_blockage_rain_loads[{i}].{key}")
        if any(row.get(k) is None for k in ("undeformed_roof_elevation_mm","secondary_inlet_elevation_mm","hydraulic_head_mm","declared_rain_load_kn_m2")):continue
        if row.get("primary_blocked") is not True:errors.append(f"RAIN_LOAD_{i}_PRIMARY_BLOCKAGE_NOT_ANALYZED")
        ds=float(row["secondary_inlet_elevation_mm"])-float(row["undeformed_roof_elevation_mm"])
        dh=float(row["hydraulic_head_mm"])
        if ds<0:errors.append(f"RAIN_LOAD_{i}_NEGATIVE_STATIC_HEAD");continue
        if dh<0:errors.append(f"RAIN_LOAD_{i}_NEGATIVE_HYDRAULIC_HEAD");continue
        calculated=.01*(ds+dh)
        if abs(float(row["declared_rain_load_kn_m2"])-calculated)>1e-6:errors.append(f"RAIN_LOAD_{i}_FORMULA_MISMATCH")
        ponding_susceptible=float(row["roof_slope_percent"])<2 or row["primary_blockage_can_retain_water"] is True
        if ponding_susceptible:
            pond=row.get("ponding_analysis")
            if not isinstance(pond,dict):missing.append(f"roof_primary_blockage_rain_loads[{i}].ponding_analysis")
            else:
                for key in ("analysis_id","method","solver_version","structural_model_sha256","convergence_tolerance_mm",
                            "final_water_surface_elevation_mm","final_deformed_low_point_elevation_mm",
                            "declared_final_ponded_depth_mm","stable","governing_water_or_snow_load_kn_m2"):
                    if pond.get(key) is None or pond.get(key)=="":missing.append(f"roof_primary_blockage_rain_loads[{i}].ponding_analysis.{key}")
                if pond.get("method") not in (None,"ITERATIVE_DEFORMED_GEOMETRY"):errors.append(f"RAIN_LOAD_{i}_PONDING_METHOD_UNSUPPORTED")
                iterations=pond.get("iterations")
                if not isinstance(iterations,list) or len(iterations)<2:
                    missing.append(f"roof_primary_blockage_rain_loads[{i}].ponding_analysis.iterations[minimum_2]")
                else:
                    for j,item in enumerate(iterations):
                        for key in ("iteration","water_surface_elevation_mm","max_deflection_mm","residual_mm"):
                            if item.get(key) is None:missing.append(f"roof_primary_blockage_rain_loads[{i}].ponding_analysis.iterations[{j}].{key}")
                    if not any(f"iterations[{j}]" in value for j in range(len(iterations)) for value in missing):
                        if [int(item["iteration"]) for item in iterations] != list(range(1,len(iterations)+1)):
                            errors.append(f"RAIN_LOAD_{i}_PONDING_ITERATION_SEQUENCE_INVALID")
                        tolerance=float(pond["convergence_tolerance_mm"])
                        if tolerance<=0 or abs(float(iterations[-1]["residual_mm"]))>tolerance:
                            errors.append(f"RAIN_LOAD_{i}_PONDING_NOT_NUMERICALLY_CONVERGED")
                if pond.get("stable") is False:errors.append(f"RAIN_LOAD_{i}_PONDING_UNSTABLE")
                if pond.get("final_water_surface_elevation_mm") is not None and pond.get("final_deformed_low_point_elevation_mm") is not None and pond.get("declared_final_ponded_depth_mm") is not None:
                    depth=max(0.0,float(pond["final_water_surface_elevation_mm"])-float(pond["final_deformed_low_point_elevation_mm"]))
                    if abs(depth-float(pond["declared_final_ponded_depth_mm"]))>1e-6:errors.append(f"RAIN_LOAD_{i}_PONDING_DEPTH_GEOMETRY_MISMATCH")
                approval=pond.get("structural_approval")
                if not isinstance(approval,dict):missing.append(f"roof_primary_blockage_rain_loads[{i}].ponding_analysis.structural_approval")
                else:
                    for key in ("approval_id","approver_role","model_sha256","status"):
                        if approval.get(key) in (None,""):missing.append(f"roof_primary_blockage_rain_loads[{i}].ponding_analysis.structural_approval.{key}")
                    if approval.get("approver_role") not in (None,"STRUCTURAL_ENGINEER"):errors.append(f"RAIN_LOAD_{i}_PONDING_APPROVER_ROLE_INVALID")
                    if approval.get("status") not in (None,"APPROVED"):errors.append(f"RAIN_LOAD_{i}_PONDING_APPROVAL_NOT_APPROVED")
                    if approval.get("model_sha256") and pond.get("structural_model_sha256") and approval["model_sha256"]!=pond["structural_model_sha256"]:
                        errors.append(f"RAIN_LOAD_{i}_PONDING_APPROVAL_MODEL_MISMATCH")
                required_governing=max(calculated,float(row["full_snow_load_kn_m2"]))
                if pond.get("governing_water_or_snow_load_kn_m2") is not None and float(pond["governing_water_or_snow_load_kn_m2"])<required_governing:
                    errors.append(f"RAIN_LOAD_{i}_PONDING_GOVERNING_LOAD_BELOW_RAIN_OR_SNOW")
        evidence.append(f"roof={row.get('roof_area_id')} ds={ds:g}mm dh={dh:g}mm R={calculated:g}kN/m2 analysis={row.get('structural_analysis_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _roof_snow_load_basis(rule, snapshot):
    rows=_context(snapshot).get("roof_snow_load_basis")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["roof_snow_load_basis[]"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("roof_area_id","ground_snow_load_ps_kn_m2","importance_factor_is","exposure_factor_cn",
                    "thermal_condition","thermal_factor_ch","slope_factor_cs","declared_balanced_roof_snow_pr_kn_m2",
                    "declared_snow_unit_weight_kn_m3","declared_balanced_snow_height_m",
                    "exposure_geometry_analysis_id","roof_slope_degrees","surface_slippery",
                    "unobstructed_slide","adequate_fall_space","snow_region"):
            if row.get(key) in (None,""):missing.append(f"roof_snow_load_basis[{i}].{key}")
        region_basis=row.get("snow_region_basis") or {}
        if (region_basis.get("source_clause") in (None,"") or
                region_basis.get("verification_status")!="VALID" or
                region_basis.get("snow_region")!=row.get("snow_region") or
                not region_basis.get("source_sha256")):
            missing.append(f"roof_snow_load_basis[{i}].snow_region_basis.valid_matching_official_source")
        if row.get("snow_region") is not None and int(row["snow_region"]) not in range(1,7):
            errors.append(f"SNOW_{i}_REGION_OUT_OF_RANGE")
        if any(row.get(k) is None for k in ("ground_snow_load_ps_kn_m2","importance_factor_is","exposure_factor_cn","thermal_factor_ch","slope_factor_cs","declared_balanced_roof_snow_pr_kn_m2","declared_snow_unit_weight_kn_m3","declared_balanced_snow_height_m","roof_slope_degrees","surface_slippery","unobstructed_slide","adequate_fall_space")):continue
        ch=float(row["thermal_factor_ch"]);alpha=float(row["roof_slope_degrees"])
        expected_ch={"GENERAL":1.0,"ALWAYS_SLIGHTLY_ABOVE_FREEZING":1.1,
                     "UNHEATED_OR_OPEN_BELOW_ROOF":1.2,"ALWAYS_BELOW_FREEZING":1.3}.get(row.get("thermal_condition"))
        if expected_ch is None:errors.append(f"SNOW_{i}_UNKNOWN_THERMAL_CONDITION")
        elif abs(ch-expected_ch)>1e-6:errors.append(f"SNOW_{i}_THERMAL_FACTOR_TABLE_MISMATCH")
        slippery=row["surface_slippery"] is True and row["unobstructed_slide"] is True and row["adequate_fall_space"] is True
        alpha0=(5 if ch==1 else 10 if ch==1.1 else 15) if slippery else (30 if ch==1 else 45)
        expected_cs=1.0 if alpha<=alpha0 else 0.0 if alpha>=70 else 1-(alpha-alpha0)/(70-alpha0)
        if abs(float(row["slope_factor_cs"])-expected_cs)>1e-6:errors.append(f"SNOW_{i}_SLOPE_FACTOR_MISMATCH")
        ps=float(row["ground_snow_load_ps_kn_m2"]);pr=float(row["importance_factor_is"])*float(row["exposure_factor_cn"])*ch*expected_cs*ps
        gamma=.43*ps+2.2;hb=pr/gamma
        if abs(float(row["declared_balanced_roof_snow_pr_kn_m2"])-pr)>1e-6:errors.append(f"SNOW_{i}_PR_FORMULA_MISMATCH")
        if abs(float(row["declared_snow_unit_weight_kn_m3"])-gamma)>1e-6:errors.append(f"SNOW_{i}_UNIT_WEIGHT_FORMULA_MISMATCH")
        if abs(float(row["declared_balanced_snow_height_m"])-hb)>1e-6:errors.append(f"SNOW_{i}_BALANCED_HEIGHT_FORMULA_MISMATCH")
        features=row.get("roof_obstructions")
        if features is None:missing.append(f"roof_snow_load_basis[{i}].roof_obstructions[]")
        else:
            for j,feature in enumerate(features):
                if feature.get("height_above_roof_m") is None:missing.append(f"roof_snow_load_basis[{i}].roof_obstructions[{j}].height_above_roof_m")
                elif feature.get("height_above_roof_m")>hb and row.get("classified_as_exposed_roof") is True:errors.append(f"SNOW_{i}_EXPOSED_CLASSIFICATION_CONTRADICTED_BY_OBSTRUCTION_{j}")
        overhang=row.get("eave_overhang")
        if overhang is not None:
            for key in ("length_m","declared_design_zone_length_m","declared_design_load_kn_m2"):
                if overhang.get(key) is None:missing.append(f"roof_snow_load_basis[{i}].eave_overhang.{key}")
            if all(overhang.get(k) is not None for k in ("length_m","declared_design_zone_length_m","declared_design_load_kn_m2")):
                if abs(float(overhang["declared_design_zone_length_m"])-min(float(overhang["length_m"]),1.5))>1e-6:errors.append(f"SNOW_{i}_OVERHANG_ZONE_LENGTH_MISMATCH")
                if abs(float(overhang["declared_design_load_kn_m2"])-2*pr)>1e-6:errors.append(f"SNOW_{i}_OVERHANG_LOAD_NOT_DOUBLE_PR")
        evidence.append(f"roof={row.get('roof_area_id')} region={row.get('snow_region')} Pr={pr:.6g}kN/m2 gamma={gamma:.6g}kN/m3 hb={hb:.6g}m geometry={row.get('exposure_geometry_analysis_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _rooftop_snow_drift_geometry(rule, snapshot):
    rows=_context(snapshot).get("rooftop_snow_drift_features")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rooftop_snow_drift_features[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["no_rooftop_drift_features"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("feature_id","snow_region","feature_type","face_width_m","windward_roof_length_m",
                    "leeward_roof_length_m","perpendicular_roof_length_m","declared_drift_width_w_m",
                    "drift_height_hd_m","clear_height_hc_m","base_calculation_id","declared_lu_m","declared_max_drift_height_m",
                    "printed_reference_anomaly_acknowledged","structural_model_sha256"):
            if row.get(key) in (None,""):missing.append(f"rooftop_snow_drift_features[{i}].{key}")
        if any(row.get(k) in (None,"") for k in ("snow_region","feature_type","face_width_m","windward_roof_length_m","leeward_roof_length_m","perpendicular_roof_length_m","declared_drift_width_w_m","drift_height_hd_m","clear_height_hc_m","declared_lu_m","declared_max_drift_height_m")):continue
        region=int(row["snow_region"]);kind=row["feature_type"];width=float(row["face_width_m"])
        if region not in (4,5,6):
            if row.get("drift_applied") is True:errors.append(f"DRIFT_{i}_APPLIED_OUTSIDE_REGIONS_4_5_6")
            evidence.append(f"feature={row.get('feature_id')} region={region} not_applicable");continue
        if kind=="ROOFTOP_RAISED_FEATURE" and width<4.5:
            if row.get("drift_applied") is True:errors.append(f"DRIFT_{i}_APPLIED_TO_RAISED_FEATURE_BELOW_4_5_M")
            evidence.append(f"feature={row.get('feature_id')} width_exception");continue
        expected_lu=float(row["perpendicular_roof_length_m"]) if kind=="PARAPET" else max(float(row["windward_roof_length_m"]),float(row["leeward_roof_length_m"]))
        if kind not in ("PARAPET","ROOFTOP_RAISED_FEATURE"):errors.append(f"DRIFT_{i}_UNKNOWN_FEATURE_TYPE");continue
        if abs(float(row["declared_lu_m"])-expected_lu)>1e-6:errors.append(f"DRIFT_{i}_LU_GEOMETRY_MISMATCH")
        hc=float(row["clear_height_hc_m"]);hd=float(row["drift_height_hd_m"])
        if hc<=0:errors.append(f"DRIFT_{i}_HC_MUST_BE_POSITIVE");continue
        relation_6_7_5=hd*hd/hc
        if abs(float(row["declared_drift_width_w_m"])-relation_6_7_5)>1e-6:errors.append(f"DRIFT_{i}_RELATION_6_7_5_WIDTH_MISMATCH")
        if row.get("printed_reference_anomaly_acknowledged") is not True:missing.append(f"rooftop_snow_drift_features[{i}].printed_reference_anomaly_acknowledged")
        interpretation=row.get("structural_interpretation")
        if not isinstance(interpretation,dict):missing.append(f"rooftop_snow_drift_features[{i}].structural_interpretation")
        else:
            for key in ("approval_id","approver_role","status","source_clause","source_printed_page","source_document_sha256","structural_model_sha256","feature_id","base_calculation_id","approved_max_drift_height_m"):
                if interpretation.get(key) in (None,""):missing.append(f"rooftop_snow_drift_features[{i}].structural_interpretation.{key}")
            if interpretation.get("approver_role") not in (None,"STRUCTURAL_ENGINEER"):errors.append(f"DRIFT_{i}_INTERPRETATION_APPROVER_INVALID")
            if interpretation.get("status") not in (None,"APPROVED"):errors.append(f"DRIFT_{i}_INTERPRETATION_NOT_APPROVED")
            if interpretation.get("source_clause") not in (None,"6-7-10 -> relation 6-7-5"):errors.append(f"DRIFT_{i}_INTERPRETATION_SOURCE_CLAUSE_MISMATCH")
            if interpretation.get("source_printed_page") not in (None,61):errors.append(f"DRIFT_{i}_INTERPRETATION_SOURCE_PAGE_MISMATCH")
            if interpretation.get("structural_model_sha256") not in (None,row.get("structural_model_sha256")):errors.append(f"DRIFT_{i}_STRUCTURAL_MODEL_HASH_MISMATCH")
            if interpretation.get("feature_id") not in (None,row.get("feature_id")) or interpretation.get("base_calculation_id") not in (None,row.get("base_calculation_id")):errors.append(f"DRIFT_{i}_INTERPRETATION_SCOPE_MISMATCH")
        expected_height=float(row["declared_max_drift_height_m"])
        if isinstance(interpretation,dict) and interpretation.get("approved_max_drift_height_m") is not None and abs(float(interpretation["approved_max_drift_height_m"])-expected_height)>1e-6:errors.append(f"DRIFT_{i}_APPROVED_MAX_HEIGHT_MISMATCH")
        if expected_height<=0:errors.append(f"DRIFT_{i}_MAX_HEIGHT_MUST_BE_POSITIVE")
        if row.get("drift_applied") is not True:errors.append(f"DRIFT_{i}_REQUIRED_CASE_NOT_APPLIED")
        evidence.append(f"feature={row.get('feature_id')} lu={expected_lu:g}m hd={hd:g}m hc={hc:g}m w={relation_6_7_5:g}m hd_max={expected_height:g}m interpretation={(interpretation or {}).get('approval_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _fluid_load_combination_extensions(rule, snapshot):
    rows=_context(snapshot).get("fluid_load_combination_extensions")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["fluid_load_combination_extensions[]"])
    expected={"LRFD":{"1":1.4,"2":1.2,"3":1.2,"4":1.2,"5":1.2,"7":.9},
              "ASD":{"1":1.0,"2":1.0,"3":1.0,"4":1.0,"5":1.0,"6":1.0,"7":1.0,"8":1.0,"10":.6}}
    missing=[];errors=[];evidence=[];seen={"LRFD":set(),"ASD":set()}
    for i,row in enumerate(rows):
        for key in ("method","base_combination_number","effect_type","effect_unit","base_effect_excluding_f",
                    "fluid_effect_f","declared_effect_including_f","analysis_id"):
            if row.get(key) in (None,""):missing.append(f"fluid_load_combination_extensions[{i}].{key}")
        method=row.get("method");case=str(row.get("base_combination_number"))
        if method not in expected or case not in expected.get(method,{}):errors.append(f"FLUID_{i}_UNSUPPORTED_METHOD_OR_CASE");continue
        seen[method].add(case)
        if any(row.get(k) is None for k in ("base_effect_excluding_f","fluid_effect_f","declared_effect_including_f")):continue
        calculated=float(row["base_effect_excluding_f"])+expected[method][case]*float(row["fluid_effect_f"])
        if abs(float(row["declared_effect_including_f"])-calculated)>1e-6:errors.append(f"FLUID_{i}_COMBINATION_EFFECT_MISMATCH")
        evidence.append(f"{method}-{case} coefficient={expected[method][case]:g} analysis={row.get('analysis_id')}")
    for method,cases in expected.items():
        for case in set(cases)-seen[method]:missing.append(f"fluid_load_combination_extensions.{method}.case_{case}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _heavy_rooftop_equipment_structural_placement(rule, snapshot):
    rows=_context(snapshot).get("heavy_rooftop_equipment_placements")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["heavy_rooftop_equipment_placements[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["heavy_rooftop_equipment_verified_absent"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("equipment_id","operating_mass_kg","support_member_type","building_importance",
                    "building_storeys","structural_model_sha256"):
            if row.get(key) in (None,""):missing.append(f"heavy_rooftop_equipment_placements[{i}].{key}")
        if row.get("support_member_type") in ("CANTILEVER","SLENDER_MEMBER","LONG_SPAN"):
            analysis=row.get("placement_structural_analysis")
            if not isinstance(analysis,dict):missing.append(f"heavy_rooftop_equipment_placements[{i}].placement_structural_analysis")
            else:
                for key in ("analysis_id","status","model_sha256","engineer_approval_id"):
                    if analysis.get(key) in (None,""):missing.append(f"heavy_rooftop_equipment_placements[{i}].placement_structural_analysis.{key}")
                if analysis.get("status") not in (None,"APPROVED"):errors.append(f"EQUIPMENT_{i}_PLACEMENT_NOT_APPROVED")
                if analysis.get("model_sha256") and row.get("structural_model_sha256") and analysis["model_sha256"]!=row["structural_model_sha256"]:errors.append(f"EQUIPMENT_{i}_PLACEMENT_MODEL_MISMATCH")
        importance=row.get("building_importance");storeys=row.get("building_storeys")
        if importance is not None and storeys is not None and (importance in ("HIGH","VERY_HIGH") or (importance=="MEDIUM" and int(storeys)>=5)):
            seismic=row.get("seismic_nonstructural_analysis")
            if not isinstance(seismic,dict):missing.append(f"heavy_rooftop_equipment_placements[{i}].seismic_nonstructural_analysis")
            else:
                for key in ("analysis_id","standard_2800_edition","status","model_sha256","engineer_approval_id"):
                    if seismic.get(key) in (None,""):missing.append(f"heavy_rooftop_equipment_placements[{i}].seismic_nonstructural_analysis.{key}")
                if seismic.get("status") not in (None,"APPROVED"):errors.append(f"EQUIPMENT_{i}_SEISMIC_ANALYSIS_NOT_APPROVED")
                if seismic.get("model_sha256") and row.get("structural_model_sha256") and seismic["model_sha256"]!=row["structural_model_sha256"]:errors.append(f"EQUIPMENT_{i}_SEISMIC_MODEL_MISMATCH")
        evidence.append(f"equipment={row.get('equipment_id')} mass={row.get('operating_mass_kg')}kg support={row.get('support_member_type')} model={row.get('structural_model_sha256')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _roof_live_load_reduction(rule, snapshot):
    rows=_context(snapshot).get("roof_live_load_reductions")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["roof_live_load_reductions[]"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("roof_area_id","roof_use_type","roof_geometry_type","tributary_area_m2","slope_parameter_s","unreduced_l0_kn_m2","declared_lr_kn_m2"):
            if row.get(key) in (None,""):missing.append(f"roof_live_load_reductions[{i}].{key}")
        if any(row.get(k) is None for k in ("tributary_area_m2","slope_parameter_s","unreduced_l0_kn_m2","declared_lr_kn_m2")):continue
        if row["roof_use_type"] not in ("ORDINARY","CANOPY","GREENHOUSE_MAINTENANCE"):
            if float(row["declared_lr_kn_m2"])<float(row["unreduced_l0_kn_m2"]):errors.append(f"ROOF_LIVE_{i}_REDUCTION_NOT_ALLOWED_FOR_SPECIAL_USE")
            continue
        geometry=row["roof_geometry_type"]
        if geometry=="FLAT":s=0.0
        elif geometry=="PITCHED":
            if row.get("roof_slope_percent") is None:missing.append(f"roof_live_load_reductions[{i}].roof_slope_percent");continue
            if row.get("roof_slope_degrees") is not None:errors.append(f"ROOF_LIVE_{i}_DEGREE_INPUT_NOT_S_PARAMETER")
            s=float(row["roof_slope_percent"])
        elif geometry in ("CURVED","DOME"):
            if row.get("rise_m") is None or row.get("span_m") in (None,0):missing.append(f"roof_live_load_reductions[{i}].rise_m_and_positive_span_m");continue
            s=267*float(row["rise_m"])/float(row["span_m"])
        else:errors.append(f"ROOF_LIVE_{i}_UNKNOWN_GEOMETRY_TYPE");continue
        if abs(float(row["slope_parameter_s"])-s)>1e-6:errors.append(f"ROOF_LIVE_{i}_S_PARAMETER_GEOMETRY_MISMATCH")
        at=float(row["tributary_area_m2"]);l0=float(row["unreduced_l0_kn_m2"])
        r1=1 if at<=18 else .6 if at>54 else 1.2-.0111*at
        r2=1 if s<=33 else .6 if s>=100 else 1.2-.006*s
        calculated=max(.6,min(1.5,l0*r1*r2))
        if abs(float(row["declared_lr_kn_m2"])-calculated)>1e-6:errors.append(f"ROOF_LIVE_{i}_REDUCTION_FORMULA_MISMATCH")
        evidence.append(f"roof={row.get('roof_area_id')} At={at:g}m2 S={s:g} R1={r1:.6g} R2={r2:.6g} Lr={calculated:.6g}kN/m2")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _special_use_roof_live_load_reduction(rule, snapshot):
    rows=_context(snapshot).get("special_use_roof_live_load_reductions")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["special_use_roof_live_load_reductions[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["special_use_roofs_verified_absent"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("roof_area_id","special_use_type","unreduced_l0_kn_m2","declared_design_live_load_kn_m2","structural_model_sha256",
                    "member_location_factor_kll","tributary_area_m2","supported_floor_count","is_assembly_area",
                    "is_passenger_vehicle_area","is_one_way_slab"):
            if row.get(key) in (None,""):missing.append(f"special_use_roof_live_load_reductions[{i}].{key}")
        calc=row.get("section_6_5_5_calculation")
        if not isinstance(calc,dict):missing.append(f"special_use_roof_live_load_reductions[{i}].section_6_5_5_calculation");continue
        for key in ("calculation_id","method_clause","result_kn_m2","status","model_sha256","engineer_approval_id"):
            if calc.get(key) in (None,""):missing.append(f"special_use_roof_live_load_reductions[{i}].section_6_5_5_calculation.{key}")
        if calc.get("method_clause") not in (None,"6-5-5"):errors.append(f"SPECIAL_ROOF_{i}_WRONG_REDUCTION_METHOD")
        if calc.get("model_sha256") and row.get("structural_model_sha256") and calc["model_sha256"]!=row["structural_model_sha256"]:errors.append(f"SPECIAL_ROOF_{i}_MODEL_MISMATCH")
        if calc.get("status") not in (None,"APPROVED"):errors.append(f"SPECIAL_ROOF_{i}_CALCULATION_NOT_APPROVED")
        at=row.get("tributary_area_m2");kll=row.get("member_location_factor_kll");l0=row.get("unreduced_l0_kn_m2")
        floors=row.get("supported_floor_count")
        if row.get("is_one_way_slab"):
            if row.get("one_way_slab_span_m") in (None,0):missing.append(f"special_use_roof_live_load_reductions[{i}].one_way_slab_span_m")
            elif at is not None and float(at)>1.5*float(row["one_way_slab_span_m"])**2+1e-9:
                errors.append(f"SPECIAL_ROOF_{i}_ONE_WAY_TRIBUTARY_AREA_EXCEEDS_1_5_SPAN_SQUARED")
        if at is not None and float(at)<=0:errors.append(f"SPECIAL_ROOF_{i}_TRIBUTARY_AREA_NOT_POSITIVE")
        if kll is not None and float(kll)<=0:errors.append(f"SPECIAL_ROOF_{i}_KLL_NOT_POSITIVE")
        if floors is not None and int(floors)<1:errors.append(f"SPECIAL_ROOF_{i}_SUPPORTED_FLOOR_COUNT_INVALID")
        if all(value is not None for value in (at,kll,l0,floors)):
            at=float(at);kll=float(kll);l0=float(l0);floors=int(floors);product=kll*at
            if row.get("is_assembly_area"):
                calculated=l0;basis="ASSEMBLY_NO_REDUCTION"
            elif l0>5 or row.get("is_passenger_vehicle_area"):
                calculated=(.8*l0 if floors>=2 else l0);basis="HIGH_OR_VEHICLE_20_PERCENT_MAX"
            elif product<37:
                calculated=l0;basis="KLL_AT_BELOW_37"
            else:
                ratio=.25+4.57/(product**.5);minimum=.4 if floors>=2 else .5
                calculated=l0*max(ratio,minimum);basis="EQUATION_6_5_1"
            if calc.get("result_kn_m2") is not None and abs(float(calc["result_kn_m2"])-calculated)>1e-6:
                errors.append(f"SPECIAL_ROOF_{i}_CALCULATION_RESULT_MISMATCH")
            if row.get("declared_design_live_load_kn_m2") is not None and float(row["declared_design_live_load_kn_m2"])+1e-9<calculated:
                errors.append(f"SPECIAL_ROOF_{i}_DESIGN_LOAD_BELOW_CALCULATED_RESULT")
            evidence.append(f"roof={row.get('roof_area_id')} use={row.get('special_use_type')} KLL_AT={product:.6g} L0={l0:.6g} L={calculated:.6g} basis={basis} calc={calc.get('calculation_id')} model={row.get('structural_model_sha256')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_equipment_vibration_isolation(rule, snapshot):
    context=_context(snapshot);rows=context.get("rainwater_equipment_vibration_isolation_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_equipment_vibration_isolation_interfaces[]"])
    if not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["vibration_capable_rainwater_equipment_verified_absent"])
                if context.get("vibration_capable_rainwater_equipment_verified_absent") is True else
                _result(rule,INPUT_REQUIRED,missing=["vibration_capable_rainwater_equipment_verified_absent"]))
    model_hash=context.get("building_geometry_sha256");missing=[];errors=[];evidence=[];applicable=0
    for i,row in enumerate(rows):
        p=f"rainwater_equipment_vibration_isolation_interfaces[{i}]"
        for key in ("equipment_id","equipment_type","can_create_undesirable_vibration","equipment_footprint","support_points"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        footprint=row.get("equipment_footprint") or [];points=row.get("support_points") or []
        if len(footprint)<3:missing.append(f"{p}.equipment_footprint[>=3]")
        if not points:missing.append(f"{p}.support_points[]")
        if len(footprint)>=3:
            polygon=Polygon(footprint)
            if not polygon.is_valid or polygon.area<=0:errors.append(f"VIBRATION_{i}_EQUIPMENT_FOOTPRINT_INVALID")
            for j,point in enumerate(points):
                if len(point)!=2:missing.append(f"{p}.support_points[{j}].xy")
                elif not polygon.covers(Point(point)):errors.append(f"VIBRATION_{i}_SUPPORT_{j}_OUTSIDE_EQUIPMENT_FOOTPRINT")
        if row.get("can_create_undesirable_vibration") is False:
            basis=row.get("non_vibrating_equipment_basis") or {}
            for key in ("manufacturer","document_id","equipment_model","verification_status","source_sha256"):
                if basis.get(key) in (None,""):missing.append(f"{p}.non_vibrating_equipment_basis.{key}")
            if basis.get("verification_status") not in (None,"VALID"):errors.append(f"VIBRATION_{i}_NON_VIBRATING_BASIS_INVALID")
            evidence.append(f"vibration_equipment={row.get('equipment_id')} capable=false basis={basis.get('document_id')}");continue
        applicable+=1
        response=row.get("vibration_isolation_response") or {};product=row.get("selected_isolator") or {}
        for key in ("analysis_id","equipment_id","model_sha256","required_isolator_type","status","engineer_approval_id"):
            if response.get(key) in (None,""):missing.append(f"{p}.vibration_isolation_response.{key}")
        for key in ("product_id","equipment_id","isolator_type","manufacturer","model","product_data_sha256","verification_status"):
            if product.get(key) in (None,""):missing.append(f"{p}.selected_isolator.{key}")
        if response.get("equipment_id") not in (None,row.get("equipment_id")):errors.append(f"VIBRATION_{i}_RESPONSE_EQUIPMENT_MISMATCH")
        if product.get("equipment_id") not in (None,row.get("equipment_id")):errors.append(f"VIBRATION_{i}_PRODUCT_EQUIPMENT_MISMATCH")
        if model_hash and response.get("model_sha256") not in (None,model_hash):errors.append(f"VIBRATION_{i}_MODEL_MISMATCH")
        if response.get("required_isolator_type") and product.get("isolator_type") and response["required_isolator_type"]!=product["isolator_type"]:errors.append(f"VIBRATION_{i}_ISOLATOR_TYPE_MISMATCH")
        if response.get("status") not in (None,"PASS","APPROVED"):errors.append(f"VIBRATION_{i}_ANALYSIS_NOT_APPROVED")
        if product.get("verification_status") not in (None,"VALID"):errors.append(f"VIBRATION_{i}_PRODUCT_DATA_INVALID")
        evidence.append(f"vibration_equipment={row.get('equipment_id')} capable=true supports={len(points)} isolator={product.get('product_id')} analysis={response.get('analysis_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    if errors:return _result(rule,FAIL,evidence=evidence,errors=errors)
    return _result(rule,PASS if applicable else NOT_APPLICABLE,evidence=evidence)


def _m6_buried_rainwater_geotechnical_structural_interface(rule,snapshot):
    c=_context(snapshot);rows=c.get("buried_rainwater_geotechnical_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["buried_rainwater_geotechnical_interfaces[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["buried_rainwater_assets_verified_absent"])
        if c.get("buried_rainwater_assets_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["buried_rainwater_assets_verified_absent"]))
    model=c.get("building_geometry_sha256");missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"buried_rainwater_geotechnical_interfaces[{i}]"
        for key in ("asset_id","asset_type","footprint","retained_height_m","groundwater_head_m","ground_surface_elevation_m","asset_base_elevation_m","groundwater_elevation_m","retaining_surface_orientation","pressure_direction","surface_surcharge_kpa","expansive_soil","seismic_lateral_effect_applicable","integral_with_building_structure","horizontal_floor_below_grade"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        polygon=row.get("footprint") or []
        if len(polygon)<3:missing.append(f"{p}.footprint[>=3]")
        elif not Polygon(polygon).is_valid or Polygon(polygon).area<=0:errors.append(f"BURIED_{i}_FOOTPRINT_INVALID")
        response=row.get("geotechnical_structural_response") or {}
        for key in ("analysis_id","asset_id","model_sha256","site_investigation_id","method","method_applicable_to_asset","source_sha256","soil_equivalent_fluid_unit_weight_kn_m3","reviewed_lateral_pressure_at_base_kpa","reviewed_uplift_pressure_kpa","stability_status","status","engineer_approval_id"):
            if response.get(key) in (None,""):missing.append(f"{p}.geotechnical_structural_response.{key}")
        if response.get("asset_id") not in (None,row.get("asset_id")):errors.append(f"BURIED_{i}_ASSET_MISMATCH")
        if model and response.get("model_sha256") not in (None,model):errors.append(f"BURIED_{i}_MODEL_MISMATCH")
        if response.get("method") not in (None,"EQUIVALENT_FLUID_APPROVED"):missing.append(f"{p}.geotechnical_structural_response.supported_site_method")
        if response.get("method_applicable_to_asset") is False:missing.append(f"{p}.geotechnical_structural_response.actual_ground_condition_method")
        if row.get("retaining_surface_orientation") not in (None,"VERTICAL_LATERAL"):missing.append(f"{p}.supported_retaining_surface_analysis")
        if row.get("pressure_direction") not in (None,"NORMAL_TO_RETAINING_SURFACE"):errors.append(f"BURIED_{i}_PRESSURE_DIRECTION_CONTRADICTS_SURFACE_NORMAL")
        gamma=response.get("soil_equivalent_fluid_unit_weight_kn_m3");h=row.get("retained_height_m");gw=row.get("groundwater_head_m");q=row.get("surface_surcharge_kpa")
        if gamma is not None and float(gamma)<5:errors.append(f"BURIED_{i}_SOIL_EQUIVALENT_FLUID_WEIGHT_BELOW_5")
        if all(v is not None for v in (gamma,h,gw,q)):
            derived_h=float(row["ground_surface_elevation_m"])-float(row["asset_base_elevation_m"])
            derived_gw=max(0.0,float(row["groundwater_elevation_m"])-float(row["asset_base_elevation_m"]))
            if abs(float(h)-derived_h)>1e-6:errors.append(f"BURIED_{i}_RETAINED_HEIGHT_ELEVATION_MISMATCH")
            if abs(float(gw)-derived_gw)>1e-6:errors.append(f"BURIED_{i}_GROUNDWATER_HEAD_ELEVATION_MISMATCH")
            if min(float(h),float(gw),float(q))<0:errors.append(f"BURIED_{i}_NEGATIVE_GEOTECHNICAL_INPUT")
            lateral=float(gamma)*float(h)+float(q)+9.80665*float(gw);uplift=9.80665*float(gw) if row.get("horizontal_floor_below_grade") else 0.0
            if response.get("reviewed_lateral_pressure_at_base_kpa") is not None and abs(float(response["reviewed_lateral_pressure_at_base_kpa"])-lateral)>1e-5:errors.append(f"BURIED_{i}_LATERAL_PRESSURE_MISMATCH")
            if response.get("reviewed_uplift_pressure_kpa") is not None and abs(float(response["reviewed_uplift_pressure_kpa"])-uplift)>1e-5:errors.append(f"BURIED_{i}_UPLIFT_PRESSURE_MISMATCH")
            evidence.append(f"buried_asset={row.get('asset_id')} lateral_kpa={lateral:.5f} uplift_kpa={uplift:.5f} analysis={response.get('analysis_id')}")
        for flag,response_key in (("expansive_soil","expansive_soil_effect_included"),("seismic_lateral_effect_applicable","seismic_lateral_effect_included"),("integral_with_building_structure","integral_pressure_variation_included")):
            if row.get(flag) and response.get(response_key) is not True:errors.append(f"BURIED_{i}_{response_key.upper()}_MISSING")
        if response.get("stability_status") not in (None,"PASS","APPROVED"):errors.append(f"BURIED_{i}_STABILITY_NOT_APPROVED")
        if response.get("status") not in (None,"PASS","APPROVED"):errors.append(f"BURIED_{i}_ANALYSIS_NOT_APPROVED")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_construction_stage_load(rule,snapshot):
    c=_context(snapshot);rows=c.get("rainwater_construction_stage_loads")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_construction_stage_loads[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["rainwater_construction_stage_loads_verified_absent"])
        if c.get("rainwater_construction_stage_loads_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["rainwater_construction_stage_loads_verified_absent"]))
    model=c.get("building_geometry_sha256");missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"rainwater_construction_stage_loads[{i}]"
        for key in ("load_case_id","construction_stage","loaded_footprint","items","declared_total_mass_kg","declared_distributed_load_kpa"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        if row.get("construction_stage") not in (None,"ROOF_PIPE_INSTALLATION","RAINWATER_EQUIPMENT_INSTALLATION","RAINWATER_MATERIAL_STAGING"):missing.append(f"{p}.supported_rainwater_construction_stage")
        polygon=row.get("loaded_footprint") or [];items=row.get("items") or []
        if len(polygon)<3:missing.append(f"{p}.loaded_footprint[>=3]");continue
        shape=Polygon(polygon)
        if not shape.is_valid or shape.area<=0:errors.append(f"CONSTRUCTION_LOAD_{i}_FOOTPRINT_INVALID");continue
        if not items:missing.append(f"{p}.items[]");continue
        total=0.0
        for j,item in enumerate(items):
            for key in ("item_id","item_type","quantity","unit_mass_kg"):
                if item.get(key) in (None,""):missing.append(f"{p}.items[{j}].{key}")
            if item.get("quantity") is not None and item.get("unit_mass_kg") is not None:
                if float(item["quantity"])<0 or float(item["unit_mass_kg"])<0:errors.append(f"CONSTRUCTION_LOAD_{i}_ITEM_{j}_NEGATIVE")
                total+=float(item["quantity"])*float(item["unit_mass_kg"])
        pressure=total*9.80665/1000.0/shape.area
        if row.get("declared_total_mass_kg") is not None and abs(float(row["declared_total_mass_kg"])-total)>1e-6:errors.append(f"CONSTRUCTION_LOAD_{i}_TOTAL_MASS_MISMATCH")
        if row.get("declared_distributed_load_kpa") is not None and abs(float(row["declared_distributed_load_kpa"])-pressure)>1e-6:errors.append(f"CONSTRUCTION_LOAD_{i}_DISTRIBUTED_LOAD_MISMATCH")
        response=row.get("temporary_structural_response") or {}
        for key in ("analysis_id","load_case_id","model_sha256","reviewed_total_mass_kg","reviewed_distributed_load_kpa","status","engineer_approval_id"):
            if response.get(key) in (None,""):missing.append(f"{p}.temporary_structural_response.{key}")
        if response.get("load_case_id") not in (None,row.get("load_case_id")):errors.append(f"CONSTRUCTION_LOAD_{i}_CASE_MISMATCH")
        if model and response.get("model_sha256") not in (None,model):errors.append(f"CONSTRUCTION_LOAD_{i}_MODEL_MISMATCH")
        if response.get("reviewed_total_mass_kg") is not None and abs(float(response["reviewed_total_mass_kg"])-total)>1e-6:errors.append(f"CONSTRUCTION_LOAD_{i}_REVIEWED_MASS_MISMATCH")
        if response.get("reviewed_distributed_load_kpa") is not None and abs(float(response["reviewed_distributed_load_kpa"])-pressure)>1e-6:errors.append(f"CONSTRUCTION_LOAD_{i}_REVIEWED_PRESSURE_MISMATCH")
        if response.get("status") not in (None,"PASS","APPROVED"):errors.append(f"CONSTRUCTION_LOAD_{i}_ANALYSIS_NOT_APPROVED")
        evidence.append(f"construction_load={row.get('load_case_id')} stage={row.get('construction_stage')} area_m2={shape.area:.4f} mass_kg={total:.3f} load_kpa={pressure:.6f} analysis={response.get('analysis_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_machinery_impact_load(rule,snapshot):
    c=_context(snapshot);rows=c.get("rainwater_machinery_impact_loads")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_machinery_impact_loads[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["rainwater_machinery_verified_absent"])
        if c.get("rainwater_machinery_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["rainwater_machinery_verified_absent"]))
    model=c.get("building_geometry_sha256");missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"rainwater_machinery_impact_loads[{i}]"
        for key in ("equipment_id","motion_type","operating_mass_kg","manufacturer_impact_factor","declared_design_gravity_load_kn"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        motion=row.get("motion_type");base={"ROTATING":1.2,"RECIPROCATING":1.5}.get(motion)
        if base is None:missing.append(f"{p}.supported_motion_type_ROTATING_or_RECIPROCATING");continue
        mf=row.get("manufacturer_impact_factor");mass=row.get("operating_mass_kg")
        if mf is not None and float(mf)<base:errors.append(f"MACHINERY_IMPACT_{i}_MANUFACTURER_FACTOR_BELOW_CODE_MINIMUM")
        if mass is not None and float(mass)<0:errors.append(f"MACHINERY_IMPACT_{i}_NEGATIVE_MASS")
        if mf is None or mass is None:continue
        factor=max(base,float(mf));load=float(mass)*9.80665/1000.0*factor
        if abs(float(row["declared_design_gravity_load_kn"])-load)>1e-6:errors.append(f"MACHINERY_IMPACT_{i}_DESIGN_LOAD_MISMATCH")
        response=row.get("support_structural_response") or {}
        for key in ("analysis_id","equipment_id","model_sha256","reviewed_design_gravity_load_kn","status","engineer_approval_id"):
            if response.get(key) in (None,""):missing.append(f"{p}.support_structural_response.{key}")
        if response.get("equipment_id") not in (None,row.get("equipment_id")):errors.append(f"MACHINERY_IMPACT_{i}_EQUIPMENT_MISMATCH")
        if model and response.get("model_sha256") not in (None,model):errors.append(f"MACHINERY_IMPACT_{i}_MODEL_MISMATCH")
        if response.get("reviewed_design_gravity_load_kn") is not None and abs(float(response["reviewed_design_gravity_load_kn"])-load)>1e-6:errors.append(f"MACHINERY_IMPACT_{i}_REVIEWED_LOAD_MISMATCH")
        if response.get("status") not in (None,"PASS","APPROVED"):errors.append(f"MACHINERY_IMPACT_{i}_ANALYSIS_NOT_APPROVED")
        evidence.append(f"machinery={row.get('equipment_id')} motion={motion} factor={factor:.3f} design_load_kn={load:.6f} analysis={response.get('analysis_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_serviceability_movement_interface(rule,snapshot):
    c=_context(snapshot);rows=c.get("rainwater_serviceability_movement_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_serviceability_movement_interfaces[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["rainwater_serviceability_movement_interfaces_verified_absent"])
        if c.get("rainwater_serviceability_movement_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["rainwater_serviceability_movement_interfaces_verified_absent"]))
    model=c.get("building_geometry_sha256");missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"rainwater_serviceability_movement_interfaces[{i}]"
        for key in ("interface_id","component_id","route_points_3d","local_axis_basis","fluid_effect_present","soil_or_groundwater_effect_present","stored_material_effect_present","self_straining_causes","selected_joint_capacity_xyz_mm","joint_capacity_envelope","declared_governing_case_id","declared_governing_relative_displacement_xyz_mm","declared_governing_relative_displacement_norm_mm"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        points=row.get("route_points_3d") or []
        if len(points)<2 or any(len(point)!=3 for point in points):missing.append(f"{p}.route_points_3d[>=2].xyz")
        response=row.get("structural_movement_response") or {}
        for key in ("analysis_id","interface_id","model_sha256","service_load_combinations","endpoint_displacements_mm","status","engineer_approval_id","evidence_provenance"):
            if response.get(key) in (None,""):missing.append(f"{p}.structural_movement_response.{key}")
        if response.get("interface_id") not in (None,row.get("interface_id")):errors.append(f"MOVEMENT_{i}_INTERFACE_MISMATCH")
        if model and response.get("model_sha256") not in (None,model):errors.append(f"MOVEMENT_{i}_MODEL_MISMATCH")
        provenance=response.get("evidence_provenance") or {}
        for key in ("verification_status","source_sha256","method_source"):
            if provenance.get(key) in (None,""):missing.append(f"{p}.structural_movement_response.evidence_provenance.{key}")
        if provenance.get("verification_status") not in (None,"VALID"):errors.append(f"MOVEMENT_{i}_PROVENANCE_INVALID")
        combos=response.get("service_load_combinations") or {}
        for case in ("W_SERVICE","E_SERVICE"):
            data=combos.get(case)
            if not isinstance(data,dict):missing.append(f"{p}.structural_movement_response.service_load_combinations.{case}");continue
            for present,key in ((row.get("fluid_effect_present"),"fluid_effect_factor"),(row.get("soil_or_groundwater_effect_present"),"soil_or_groundwater_effect_factor"),(row.get("stored_material_effect_present"),"stored_material_effect_factor")):
                if present and data.get(key) is None:missing.append(f"{p}.structural_movement_response.service_load_combinations.{case}.{key}")
                elif present and abs(float(data[key])-1.0)>1e-9:errors.append(f"MOVEMENT_{i}_{case}_{key.upper()}_NOT_ONE")
        causes=row.get("self_straining_causes") or []
        allowed={"TEMPERATURE","DIFFERENTIAL_SETTLEMENT","MOISTURE","CREEP","SHRINKAGE"}
        if any(cause not in allowed for cause in causes):missing.append(f"{p}.supported_self_straining_causes")
        required_cases={"D_PLUS_T","D_PLUS_075_L_ALT_T"} if causes else set()
        axes=row.get("local_axis_basis") or {}
        if axes.get("unit") not in (None,"mm"):errors.append(f"MOVEMENT_{i}_DISPLACEMENT_UNIT_CONTRADICTION")
        for axis in ("x","y","z"):
            vector=axes.get(axis)
            if not isinstance(vector,list) or len(vector)!=3:missing.append(f"{p}.local_axis_basis.{axis}[3]")
        capacities=row.get("selected_joint_capacity_xyz_mm") or {}
        for axis in ("x","y","z"):
            if capacities.get(axis) is None:missing.append(f"{p}.selected_joint_capacity_xyz_mm.{axis}")
            elif float(capacities[axis])<0:errors.append(f"MOVEMENT_{i}_NEGATIVE_{axis.upper()}_CAPACITY")
        envelope=row.get("joint_capacity_envelope") or {}
        for key in ("method","product_id","product_model","verification_status","source_sha256"):
            if envelope.get(key) in (None,""):missing.append(f"{p}.joint_capacity_envelope.{key}")
        if envelope.get("verification_status") not in (None,"VALID"):errors.append(f"MOVEMENT_{i}_CAPACITY_ENVELOPE_PROVENANCE_INVALID")
        if envelope.get("method") not in (None,"RECTANGULAR_INDEPENDENT","ELLIPSOIDAL_INTERACTION"):missing.append(f"{p}.joint_capacity_envelope.supported_method")
        displacements=response.get("endpoint_displacements_mm") or {};values=[]
        for case in sorted({"W_SERVICE","E_SERVICE"}|required_cases):
            data=displacements.get(case)
            if not isinstance(data,dict):missing.append(f"{p}.structural_movement_response.endpoint_displacements_mm.{case}");continue
            start=data.get("start_xyz_mm");end=data.get("end_xyz_mm")
            if not isinstance(start,list) or not isinstance(end,list) or len(start)!=3 or len(end)!=3:missing.append(f"{p}.structural_movement_response.endpoint_displacements_mm.{case}.start_end_xyz_mm");continue
            delta=[float(end[j])-float(start[j]) for j in range(3)];relative=sum(value**2 for value in delta)**.5;values.append((case,delta,relative))
        if values:
            case,delta,governing=max(values,key=lambda value:value[2]);declared=row.get("declared_governing_relative_displacement_xyz_mm") or []
            if row.get("declared_governing_case_id")!=case:errors.append(f"MOVEMENT_{i}_GOVERNING_CASE_MISMATCH")
            if len(declared)!=3:missing.append(f"{p}.declared_governing_relative_displacement_xyz_mm[3]")
            elif any(abs(float(declared[j])-delta[j])>1e-6 for j in range(3)):errors.append(f"MOVEMENT_{i}_GOVERNING_VECTOR_MISMATCH")
            if abs(float(row["declared_governing_relative_displacement_norm_mm"])-governing)>1e-6:errors.append(f"MOVEMENT_{i}_GOVERNING_NORM_MISMATCH")
            for j,axis in enumerate(("x","y","z")):
                if capacities.get(axis) is not None and abs(delta[j])>float(capacities[axis])+1e-9:errors.append(f"MOVEMENT_{i}_JOINT_{axis.upper()}_CAPACITY_INSUFFICIENT")
            if envelope.get("method")=="ELLIPSOIDAL_INTERACTION" and all(float(capacities.get(axis,0))>0 for axis in ("x","y","z")):
                interaction=sum((delta[j]/float(capacities[axis]))**2 for j,axis in enumerate(("x","y","z")))
                if interaction>1+1e-9:errors.append(f"MOVEMENT_{i}_JOINT_INTERACTION_ENVELOPE_EXCEEDED")
                evidence.append(f"movement_interaction={interaction:.6f} method=ELLIPSOIDAL_INTERACTION")
            evidence.append(f"movement_interface={row.get('interface_id')} causes={','.join(causes) or 'NONE'} case={case} vector_mm={delta} norm_mm={governing:.6f} capacity_xyz_mm={[capacities.get(a) for a in ('x','y','z')]} analysis={response.get('analysis_id')}")
        if response.get("status") not in (None,"PASS","APPROVED"):errors.append(f"MOVEMENT_{i}_ANALYSIS_NOT_APPROVED")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_flood_ice_load_combination_extensions(rule,snapshot):
    c=_context(snapshot);row=c.get("rainwater_flood_ice_load_combination_extensions")
    if row is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_flood_ice_load_combination_extensions"])
    flood=row.get("flood_load_applicable");ice=row.get("atmospheric_ice_load_applicable")
    if flood is None or ice is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_flood_ice_load_combination_extensions.flood_and_ice_applicability"])
    if flood is False and ice is False:
        if c.get("rainwater_site_flood_structural_interfaces_verified_absent") is True and c.get("atmospheric_ice_rainwater_components_verified_absent") is True:
            return _result(rule,NOT_APPLICABLE,evidence=["site_flood_and_atmospheric_ice_interfaces_verified_absent"])
        return _result(rule,INPUT_REQUIRED,missing=["verified_absence_of_flood_and_ice_interfaces"])
    missing=[];errors=[];evidence=[];effects=row.get("load_effects") or {};declared=row.get("evaluated_cases") or {}
    for key in ("D","L","Lr","S","R","W","Fa","Di","Wi"):
        if effects.get(key) is None:missing.append(f"rainwater_flood_ice_load_combination_extensions.load_effects.{key}")
    for key in ("effect_type","effect_unit","direction_convention","structural_analysis_id","structural_model_sha256","evaluated_cases","governing_case_id","capacity_abs"):
        if row.get(key) in (None,"",{}):missing.append(f"rainwater_flood_ice_load_combination_extensions.{key}")
    if flood and not row.get("flood_interface_id"):missing.append("rainwater_flood_ice_load_combination_extensions.flood_interface_id")
    if ice and not row.get("atmospheric_ice_component_id"):missing.append("rainwater_flood_ice_load_combination_extensions.atmospheric_ice_component_id")
    if flood and row.get("flood_interface_id") not in {item.get("asset_id") for item in (c.get("rainwater_site_flood_structural_interfaces") or [])}:
        missing.append("rainwater_flood_ice_load_combination_extensions.matching_actual_flood_asset_interface")
    if ice and row.get("atmospheric_ice_component_id") not in {item.get("component_id") for item in (c.get("atmospheric_ice_rainwater_components") or [])}:
        missing.append("rainwater_flood_ice_load_combination_extensions.matching_actual_atmospheric_ice_component")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    D,L,Lr,S,R,W,Fa,Di,Wi=(float(effects[k]) for k in ("D","L","Lr","S","R","W","Fa","Di","Wi"));cases={}
    if flood:
        for sign,label in ((1,"POS"),(-1,"NEG")):
            for alt,value in (("LR",Lr),("S",S),("R",R)):
                cases[f"LRFD-4-FLOOD-{alt}-{label}"]=1.2*D+sign*(1.6*W+2*Fa)+L+.5*value
                cases[f"ASD-6-FLOOD-{alt}-{label}"]=D+.75*L+sign*(.75*W+1.5*Fa)+.75*value
            cases[f"LRFD-6-FLOOD-{label}"]=.9*D+sign*(1.6*W+2*Fa)
            cases[f"ASD-5-FLOOD-{label}"]=D+sign*(W+1.5*Fa)
            cases[f"ASD-9-FLOOD-{label}"]=.6*D+sign*(W+1.5*Fa)
    if ice:
        cases["LRFD-2-ICE"]=1.2*D+1.6*L+.2*Di+.5*S
        cases["ASD-2-ICE"]=D+L+.7*Di
        for sign,label in ((1,"POS"),(-1,"NEG")):
            cases[f"LRFD-4-ICE-{label}"]=1.2*D+L+Di+sign*1.6*Wi+.5*S
            cases[f"LRFD-6-ICE-{label}"]=.9*D+Di+sign*1.6*Wi
            cases[f"ASD-3-ICE-{label}"]=D+.7*Di+sign*1.1*Wi+S
            cases[f"ASD-9-ICE-{label}"]=.6*D+.7*Di+sign*1.1*Wi
    for case,value in cases.items():
        if case not in declared:errors.append("FLOOD_ICE_COMBINATION_MISSING:"+case)
        elif abs(float(declared[case])-value)>1e-6:errors.append("FLOOD_ICE_COMBINATION_MISMATCH:"+case)
    governing=max(cases,key=lambda case:abs(cases[case]))
    if row.get("governing_case_id")!=governing:errors.append("FLOOD_ICE_GOVERNING_CASE_MISMATCH")
    if float(row["capacity_abs"])+1e-9<abs(cases[governing]):errors.append("FLOOD_ICE_CAPACITY_BELOW_GOVERNING_EFFECT")
    if c.get("building_geometry_sha256") and row.get("structural_model_sha256")!=c.get("building_geometry_sha256"):errors.append("FLOOD_ICE_MODEL_MISMATCH")
    evidence.append(f"flood_ice_combinations flood={flood} ice={ice} governing={governing} effect={cases[governing]:.6f}{row.get('effect_unit')} analysis={row.get('structural_analysis_id')}")
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_occupied_space_rainwater_clearance(rule,snapshot):
    c=_context(snapshot);rows=c.get("occupied_space_rainwater_clearance_routes")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["occupied_space_rainwater_clearance_routes[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["occupied_space_rainwater_routes_verified_absent"])
        if c.get("occupied_space_rainwater_routes_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["occupied_space_rainwater_routes_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"occupied_space_rainwater_clearance_routes[{i}]"
        for key in ("route_id","space_id","space_type","space_polygon","finished_floor_elevation_m","crossing_is_local_overhead_projection","general_space_clear_height_m","bottom_envelope_points","envelope_components"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        polygon=row.get("space_polygon") or [];points=row.get("bottom_envelope_points") or []
        if row.get("space_type") not in (None,"HABITABLE","OCCUPANCY"):missing.append(f"{p}.supported_space_type")
        if row.get("crossing_is_local_overhead_projection") is False:errors.append(f"OCCUPIED_CLEARANCE_{i}_SOURCE_SCOPE_CONTRADICTION_NOT_LOCAL_OVERHEAD_ELEMENT")
        if len(polygon)<3 or len(points)<2 or any(len(point)!=3 for point in points):missing.append(f"{p}.valid_polygon_and_3d_envelope");continue
        zone=Polygon(polygon);line=LineString([(point[0],point[1]) for point in points])
        if not zone.is_valid or not line.is_valid:errors.append(f"OCCUPIED_CLEARANCE_{i}_GEOMETRY_INVALID");continue
        intersection=line.intersection(zone)
        if intersection.is_empty or intersection.length<=1e-9:
            evidence.append(f"occupied_clearance={row.get('route_id')} space={row.get('space_id')} intersects=false");continue
        # Envelope points must bracket the whole crossing; a declared scalar is
        # never accepted in place of the actual 3D bottom envelope.
        crossing_z=[]
        for point in points:
            if zone.covers(Point(point[0],point[1])):crossing_z.append(float(point[2]))
        if not crossing_z:missing.append(f"{p}.bottom_envelope_points_inside_space")
        else:
            clearance=min(crossing_z)-float(row["finished_floor_elevation_m"])
            if clearance+1e-9<2.05:errors.append(f"OCCUPIED_CLEARANCE_{i}_BELOW_2_05M")
            evidence.append(f"occupied_clearance={row.get('route_id')} space={row.get('space_id')} intersection_m={intersection.length:.4f} clearance_m={clearance:.4f}")
        required={"PIPE","INSULATION","SUPPORT"}
        if not required.issubset(set(row.get("envelope_components") or [])):missing.append(f"{p}.envelope_components_PIPE_INSULATION_SUPPORT")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_rainwater_egress_width_obstruction(rule,snapshot):
    c=_context(snapshot);rows=c.get("rainwater_egress_width_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_egress_width_interfaces[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["rainwater_egress_interfaces_verified_absent"])
        if c.get("rainwater_egress_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["rainwater_egress_interfaces_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"rainwater_egress_width_interfaces[{i}]"
        for key in ("egress_id","path_geometry_model","egress_polygon","longitudinal_axis","required_clear_width_m","rainwater_component_footprints","component_inventory_complete","inventory_provenance"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        if row.get("path_geometry_model") not in (None,"STRAIGHT_AXIS_PRISMATIC_SECTIONS"):
            missing.append(f"{p}.supported_path_geometry_model_STRAIGHT_AXIS_PRISMATIC_SECTIONS")
        polygon=row.get("egress_polygon") or []
        if len(polygon)<3:missing.append(f"{p}.egress_polygon[>=3]");continue
        zone=Polygon(polygon)
        if not zone.is_valid or zone.area<=0:errors.append(f"EGRESS_{i}_POLYGON_INVALID");continue
        provenance=row.get("inventory_provenance") or {}
        for key in ("geometry_model_sha256","verification_status","source_sha256"):
            if provenance.get(key) in (None,""):missing.append(f"{p}.inventory_provenance.{key}")
        if provenance.get("verification_status") not in (None,"VALID"):errors.append(f"EGRESS_{i}_INVENTORY_PROVENANCE_INVALID")
        if row.get("component_inventory_complete") is False:missing.append(f"{p}.complete_rainwater_component_inventory")
        components=[]
        for j,item in enumerate(row.get("rainwater_component_footprints") or []):
            footprint=item.get("polygon") or []
            if not item.get("component_id"):missing.append(f"{p}.rainwater_component_footprints[{j}].component_id")
            if len(footprint)<3:missing.append(f"{p}.rainwater_component_footprints[{j}].polygon");continue
            shape=Polygon(footprint)
            if not shape.is_valid:errors.append(f"EGRESS_{i}_COMPONENT_{j}_POLYGON_INVALID")
            else:components.append(shape)
        union=unary_union(components) if components else None
        # Declared sections are supplemental QA only.  Completeness comes from
        # deriving every critical station and every open-interval midpoint from
        # the actual corridor/obstruction vertices along the longitudinal axis.
        axis=row.get("longitudinal_axis") or []
        if len(axis)!=2 or any(len(point)!=2 for point in axis):missing.append(f"{p}.longitudinal_axis[2].xy");continue
        ax=float(axis[1][0])-float(axis[0][0]);ay=float(axis[1][1])-float(axis[0][1]);axis_length=sqrt(ax*ax+ay*ay)
        if axis_length<=1e-9:errors.append(f"EGRESS_{i}_LONGITUDINAL_AXIS_ZERO_LENGTH");continue
        ux=ax/axis_length;uy=ay/axis_length;nx=-uy;ny=ux
        axis_line=LineString(axis)
        if not zone.covers(axis_line):errors.append(f"EGRESS_{i}_LONGITUDINAL_AXIS_OUTSIDE_EGRESS_POLYGON")
        vertices=list(zone.exterior.coords)
        for shape in components:vertices.extend(shape.exterior.coords)
        critical={0.0,axis_length}
        for x,y in vertices:
            station=(float(x)-float(axis[0][0]))*ux+(float(y)-float(axis[0][1]))*uy
            if 0<station<axis_length:critical.add(round(station,9))
        ordered=sorted(critical);derived=list(ordered)
        derived.extend((a+b)/2 for a,b in zip(ordered,ordered[1:]) if b-a>1e-8)
        minx,miny,maxx,maxy=zone.bounds;reach=max(maxx-minx,maxy-miny,axis_length)*2+1
        for j,station in enumerate(sorted(set(derived))):
            cx=float(axis[0][0])+ux*station;cy=float(axis[0][1])+uy*station
            probe=LineString([(cx-nx*reach,cy-ny*reach),(cx+nx*reach,cy+ny*reach)])
            section=probe.intersection(zone)
            if section.is_empty or section.length<=1e-9:errors.append(f"EGRESS_{i}_DERIVED_SECTION_{j}_EMPTY");continue
            clear_geometry=section if union is None else section.difference(union)
            clear_parts=list(clear_geometry.geoms) if hasattr(clear_geometry,"geoms") else [clear_geometry]
            maximum_contiguous_clear=max((part.length for part in clear_parts),default=0.0)
            blocked=section.intersection(union).length if union is not None else 0.0
            if maximum_contiguous_clear+1e-9<float(row["required_clear_width_m"]):errors.append(f"EGRESS_{i}_CONTINUOUS_CLEAR_WIDTH_BELOW_REQUIRED")
            evidence.append(f"egress={row.get('egress_id')} derived_station_m={station:.4f} section_m={section.length:.4f} blocked_m={blocked:.4f} max_contiguous_clear_m={maximum_contiguous_clear:.4f} required_m={float(row['required_clear_width_m']):.4f}")
        for j,section in enumerate(row.get("cross_sections") or []):
            points=section.get("points") or []
            if section.get("station_m") is None:missing.append(f"{p}.cross_sections[{j}].station_m")
            if len(points)!=2 or any(len(point)!=2 for point in points):missing.append(f"{p}.cross_sections[{j}].points[2].xy");continue
            line=LineString(points)
            if not zone.covers(line):errors.append(f"EGRESS_{i}_SECTION_{j}_OUTSIDE_EGRESS_POLYGON")
            blocked=0.0 if union is None else line.intersection(union).length;clear_geometry=line if union is None else line.difference(union)
            parts=list(clear_geometry.geoms) if hasattr(clear_geometry,"geoms") else [clear_geometry]
            clear=max((part.length for part in parts),default=0.0)
            if clear+1e-9<float(row["required_clear_width_m"]):errors.append(f"EGRESS_{i}_SECTION_{j}_CLEAR_WIDTH_BELOW_REQUIRED")
            evidence.append(f"egress={row.get('egress_id')} supplemental_station_m={section.get('station_m')} section_m={line.length:.4f} blocked_m={blocked:.4f} max_contiguous_clear_m={clear:.4f} required_m={float(row['required_clear_width_m']):.4f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_buried_h_load_combination_extensions(rule,snapshot):
    c=_context(snapshot);rows=c.get("rainwater_buried_h_load_combination_extensions")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_buried_h_load_combination_extensions[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["buried_h_load_interfaces_verified_absent"])
        if c.get("buried_h_load_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["buried_h_load_interfaces_verified_absent"]))
    buried={row.get("asset_id"):row for row in c.get("buried_rainwater_geotechnical_interfaces") or []}
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"rainwater_buried_h_load_combination_extensions[{i}]"
        for key in ("asset_id","effect_type","effect_unit","base_effect","h_effect_abs","h_is_permanent","evaluated_cases","governing_case_id","capacity_abs","structural_analysis_id","structural_model_sha256"):
            if row.get(key) in (None,"",{}):missing.append(f"{p}.{key}")
        if row.get("asset_id") not in buried:missing.append(f"{p}.matching_buried_rainwater_asset")
        compatible={"FORCE":{"kN"},"MOMENT":{"kN_m"},"STRESS":{"kPa","MPa"},"PRESSURE":{"kPa","MPa"}}
        if row.get("effect_type") not in compatible or row.get("effect_unit") not in compatible.get(row.get("effect_type"),set()):
            missing.append(f"{p}.compatible_effect_type_and_unit")
        if any(row.get(key) in (None,"") for key in ("base_effect","h_effect_abs","h_is_permanent")):continue
        base=float(row["base_effect"]);h=abs(float(row["h_effect_abs"]));permanent=row["h_is_permanent"] is True
        if float(row["h_effect_abs"])<0:errors.append(f"BURIED_H_{i}_H_EFFECT_MUST_BE_ABSOLUTE")
        cases={"LRFD-H-ADDITIVE":base+1.6*h,"LRFD-H-RELIEVING":base-(.9*h if permanent else 0),
               "ASD-H-ADDITIVE":base+h,"ASD-H-RELIEVING":base-(.6*h if permanent else 0)}
        declared=row.get("evaluated_cases") or {}
        for case,value in cases.items():
            if case not in declared:errors.append(f"BURIED_H_{i}_CASE_MISSING:{case}")
            elif abs(float(declared[case])-value)>1e-6:errors.append(f"BURIED_H_{i}_CASE_MISMATCH:{case}")
        governing=max(cases,key=lambda key:abs(cases[key]))
        if row.get("governing_case_id")!=governing:errors.append(f"BURIED_H_{i}_GOVERNING_CASE_MISMATCH")
        if row.get("capacity_abs") is not None and float(row["capacity_abs"])+1e-9<abs(cases[governing]):errors.append(f"BURIED_H_{i}_CAPACITY_BELOW_GOVERNING_EFFECT")
        response=(buried.get(row.get("asset_id")) or {}).get("geotechnical_structural_response") or {}
        if response.get("analysis_id")!=row.get("structural_analysis_id"):errors.append(f"BURIED_H_{i}_ANALYSIS_ID_MISMATCH")
        if response.get("model_sha256")!=row.get("structural_model_sha256"):errors.append(f"BURIED_H_{i}_MODEL_HASH_MISMATCH")
        evidence.append(f"buried_h={row.get('asset_id')} permanent={permanent} H={h:.6g}{row.get('effect_unit')} governing={governing} effect={cases[governing]:.6g}{row.get('effect_unit')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_visible_rainwater_facade_coordination(rule,snapshot):
    c=_context(snapshot);rows=c.get("visible_rainwater_facade_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["visible_rainwater_facade_interfaces[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["visible_rainwater_facade_interfaces_verified_absent"])
        if c.get("visible_rainwater_facade_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["visible_rainwater_facade_interfaces_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"visible_rainwater_facade_interfaces[{i}]"
        for key in ("component_id","component_type","facade_id","elevation_polyline","architecture_response"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        points=row.get("elevation_polyline") or []
        if len(points)<2 or any(len(point)!=2 for point in points):missing.append(f"{p}.elevation_polyline[>=2].xy")
        response=row.get("architecture_response") or {}
        for key in ("review_id","component_id","facade_id","model_sha256","status","source_sha256"):
            if response.get(key) in (None,""):missing.append(f"{p}.architecture_response.{key}")
        if response.get("component_id") not in (None,row.get("component_id")):errors.append(f"FACADE_{i}_COMPONENT_ID_MISMATCH")
        if response.get("facade_id") not in (None,row.get("facade_id")):errors.append(f"FACADE_{i}_FACADE_ID_MISMATCH")
        if response.get("status") not in (None,"APPROVED"):errors.append(f"FACADE_{i}_ARCHITECTURE_RESPONSE_NOT_APPROVED")
        if c.get("building_geometry_sha256") and response.get("model_sha256")!=c.get("building_geometry_sha256"):errors.append(f"FACADE_{i}_MODEL_HASH_MISMATCH")
        evidence.append(f"facade_component={row.get('component_id')} type={row.get('component_type')} facade={row.get('facade_id')} review={response.get('review_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_main_entrance_runoff_elevation_interface(rule,snapshot):
    c=_context(snapshot);rows=c.get("main_entrance_runoff_elevation_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["main_entrance_runoff_elevation_interfaces[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["main_entrance_runoff_interfaces_verified_absent"])
        if c.get("main_entrance_runoff_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["main_entrance_runoff_interfaces_verified_absent"]))
    missing=[];errors=[];evidence=[];applicable=0
    for i,row in enumerate(rows):
        p=f"main_entrance_runoff_elevation_interfaces[{i}]"
        for key in ("entrance_id","rainwater_runoff_interface","main_entrance_floor_elevation_mm","average_adjacent_way_elevation_mm","site_condition"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        if row.get("rainwater_runoff_interface") is not True:
            evidence.append(f"entrance_runoff={row.get('entrance_id')} applicable=false");continue
        applicable+=1
        if row.get("site_condition") not in ("STANDARD","SPECIAL_LOCAL_CONDITION"):
            missing.append(f"{p}.supported_site_condition");continue
        if any(row.get(k) is None for k in ("main_entrance_floor_elevation_mm","average_adjacent_way_elevation_mm")):continue
        limit=1200.0;approval_id="SOURCE_STANDARD"
        if row.get("site_condition")=="SPECIAL_LOCAL_CONDITION":
            approval=row.get("local_authority_adjustment") or {}
            for key in ("approval_id","authority","status","approved_max_delta_mm","source_sha256"):
                if approval.get(key) in (None,""):missing.append(f"{p}.local_authority_adjustment.{key}")
            if approval.get("status") not in (None,"APPROVED"):errors.append(f"ENTRANCE_RUNOFF_{i}_LOCAL_ADJUSTMENT_NOT_APPROVED")
            if approval.get("approved_max_delta_mm") is not None:limit=float(approval["approved_max_delta_mm"])
            approval_id=approval.get("approval_id")
        delta=float(row["main_entrance_floor_elevation_mm"])-float(row["average_adjacent_way_elevation_mm"])
        if delta>limit+1e-6:errors.append(f"ENTRANCE_RUNOFF_{i}_FLOOR_ABOVE_AVERAGE_WAY_LIMIT")
        evidence.append(f"entrance_runoff={row.get('entrance_id')} floor_minus_average_way_mm={delta:g} limit_mm={limit:g} basis={approval_id}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    if applicable==0:return _result(rule,NOT_APPLICABLE,evidence=evidence)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_pedestrian_ramp_runoff_interface(rule,snapshot):
    c=_context(snapshot);rows=c.get("pedestrian_ramp_runoff_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["pedestrian_ramp_runoff_interfaces[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["pedestrian_ramp_runoff_interfaces_verified_absent"])
        if c.get("pedestrian_ramp_runoff_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["pedestrian_ramp_runoff_interfaces_verified_absent"]))
    stage=c.get("project_stage","DESIGN");missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"pedestrian_ramp_runoff_interfaces[{i}]"
        for key in ("ramp_id","rainwater_runoff_interface","route_class","accessible_required","profile_points","landings","drainage_route_id","ponding_free","selected_surface"):
            if row.get(key) in (None,"",[]):missing.append(f"{p}.{key}")
        if row.get("rainwater_runoff_interface") is not True:continue
        points=row.get("profile_points") or []
        if len(points)<2 or any(len(point)!=2 for point in points):missing.append(f"{p}.profile_points[>=2].station_elevation");continue
        slopes=[]
        for j,(a,b) in enumerate(zip(points,points[1:])):
            run=float(b[0])-float(a[0]);rise=float(b[1])-float(a[1])
            if run<=0:errors.append(f"PEDESTRIAN_RAMP_{i}_PROFILE_STATIONS_NOT_INCREASING");continue
            slope=abs(rise/run*100);slopes.append(slope)
            limit=8.0 if row.get("route_class")=="MAIN_ACCESS_OR_EGRESS" or row.get("accessible_required") is True else 12.5
            if slope>limit+1e-9:errors.append(f"PEDESTRIAN_RAMP_{i}_RUN_{j}_SLOPE_ABOVE_{limit:g}_PERCENT")
        landings=sorted(row.get("landings") or [],key=lambda item:float(item.get("station_m",0)))
        if len(landings)<2:missing.append(f"{p}.top_bottom_landings")
        for j,landing in enumerate(landings):
            for key in ("landing_id","station_m","polygon","slope_x_percent","slope_y_percent"):
                if landing.get(key) in (None,""):missing.append(f"{p}.landings[{j}].{key}")
            polygon=landing.get("polygon") or []
            if len(polygon)<3:missing.append(f"{p}.landings[{j}].polygon[>=3]")
            elif not Polygon(polygon).is_valid:errors.append(f"PEDESTRIAN_RAMP_{i}_LANDING_{j}_POLYGON_INVALID")
            if landing.get("slope_x_percent") is not None and abs(float(landing["slope_x_percent"]))>=2:errors.append(f"PEDESTRIAN_RAMP_{i}_LANDING_{j}_SLOPE_X_NOT_BELOW_2_PERCENT")
            if landing.get("slope_y_percent") is not None and abs(float(landing["slope_y_percent"]))>=2:errors.append(f"PEDESTRIAN_RAMP_{i}_LANDING_{j}_SLOPE_Y_NOT_BELOW_2_PERCENT")
            if not row.get("accessible_required") and len(polygon)>=3:
                minx,miny,maxx,maxy=Polygon(polygon).bounds
                if min(maxx-minx,maxy-miny)+1e-9<.9:errors.append(f"PEDESTRIAN_RAMP_{i}_LANDING_{j}_MIN_DIMENSION_BELOW_0_9M")
        for j,(a,b) in enumerate(zip(landings,landings[1:])):
            if float(b.get("station_m",0))-float(a.get("station_m",0))>9+1e-9:errors.append(f"PEDESTRIAN_RAMP_{i}_RUN_{j}_BETWEEN_LANDINGS_ABOVE_9M")
        if row.get("accessible_required"):
            review=row.get("accessibility_review") or {}
            for key in ("review_id","model_sha256","status","owner_module","source_sha256"):
                if review.get(key) in (None,""):missing.append(f"{p}.accessibility_review.{key}")
            if review.get("status") not in (None,"APPROVED"):errors.append(f"PEDESTRIAN_RAMP_{i}_ACCESSIBILITY_REVIEW_NOT_APPROVED")
            if c.get("building_geometry_sha256") and review.get("model_sha256")!=c.get("building_geometry_sha256"):errors.append(f"PEDESTRIAN_RAMP_{i}_ACCESSIBILITY_MODEL_MISMATCH")
        surface=row.get("selected_surface") or {};approval=surface.get("product_approval") or {}
        for key in ("product_identity","hard","fixed","application_detail_id"):
            if surface.get(key) in (None,""):missing.append(f"{p}.selected_surface.{key}")
        for key in ("approval_id","product_identity","approved_for_wet_pedestrian_ramp","source_sha256"):
            if approval.get(key) in (None,""):missing.append(f"{p}.selected_surface.product_approval.{key}")
        if surface.get("hard") is False:errors.append(f"PEDESTRIAN_RAMP_{i}_SURFACE_NOT_HARD")
        if surface.get("fixed") is False:errors.append(f"PEDESTRIAN_RAMP_{i}_SURFACE_NOT_FIXED")
        if approval.get("product_identity") not in (None,surface.get("product_identity")):errors.append(f"PEDESTRIAN_RAMP_{i}_SURFACE_PRODUCT_MISMATCH")
        if approval.get("approved_for_wet_pedestrian_ramp") is False:errors.append(f"PEDESTRIAN_RAMP_{i}_SURFACE_NOT_APPROVED_NONSLIP_WET")
        if stage in ("CONSTRUCTION","FINAL_INSPECTION"):
            test=surface.get("wet_slip_test") or {}
            for key in ("report_id","product_identity","condition","status","source_sha256"):
                if test.get(key) in (None,""):missing.append(f"{p}.selected_surface.wet_slip_test.{key}")
            if test.get("product_identity") not in (None,surface.get("product_identity")):errors.append(f"PEDESTRIAN_RAMP_{i}_WET_TEST_PRODUCT_MISMATCH")
            if test.get("condition") not in (None,"WET") or test.get("status") not in (None,"PASS"):errors.append(f"PEDESTRIAN_RAMP_{i}_WET_TEST_NOT_PASS")
        if row.get("ponding_free") is False:errors.append(f"PEDESTRIAN_RAMP_{i}_PONDING")
        evidence.append(f"pedestrian_ramp={row.get('ramp_id')} slopes={[round(x,4) for x in slopes]} landings={len(landings)} surface={surface.get('product_identity')} stage={stage}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _roof_serviceability_deflection(rule, snapshot):
    rows=_context(snapshot).get("roof_serviceability_deflection_checks")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["roof_serviceability_deflection_checks[]"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("member_id","span_mm","allowable_deflection_ratio","calculated_deflection_mm","load_combination_id","analysis_id","structural_model_sha256"):
            if row.get(key) in (None,""):missing.append(f"roof_serviceability_deflection_checks[{i}].{key}")
        if any(row.get(k) in (None,0) for k in ("span_mm","allowable_deflection_ratio")):continue
        allowable=float(row["span_mm"])/float(row["allowable_deflection_ratio"])
        limit=row.get("deflection_limit_source")
        if not isinstance(limit,dict):missing.append(f"roof_serviceability_deflection_checks[{i}].deflection_limit_source")
        else:
            for key in ("code","edition","clause","member_type","material","load_condition","attached_component_condition","approved_ratio","engineer_approval_id","structural_model_sha256","status"):
                if limit.get(key) in (None,""):missing.append(f"roof_serviceability_deflection_checks[{i}].deflection_limit_source.{key}")
            if limit.get("approved_ratio") is not None and float(limit["approved_ratio"])!=float(row["allowable_deflection_ratio"]):errors.append(f"DEFLECTION_{i}_LIMIT_RATIO_SOURCE_MISMATCH")
            if limit.get("structural_model_sha256") and limit["structural_model_sha256"]!=row.get("structural_model_sha256"):errors.append(f"DEFLECTION_{i}_LIMIT_MODEL_MISMATCH")
            if limit.get("status") not in (None,"APPROVED"):errors.append(f"DEFLECTION_{i}_LIMIT_NOT_APPROVED")
        if row.get("calculated_deflection_mm") is not None and float(row["calculated_deflection_mm"])>allowable+1e-6:errors.append(f"DEFLECTION_{i}_EXCEEDS_ALLOWABLE")
        response=row.get("analysis_response")
        if not isinstance(response,dict):missing.append(f"roof_serviceability_deflection_checks[{i}].analysis_response")
        else:
            for key in ("analysis_id","model_sha256","status","engineer_approval_id"):
                if response.get(key) in (None,""):missing.append(f"roof_serviceability_deflection_checks[{i}].analysis_response.{key}")
            if response.get("analysis_id") and response["analysis_id"]!=row.get("analysis_id"):errors.append(f"DEFLECTION_{i}_ANALYSIS_ID_MISMATCH")
            if response.get("model_sha256") and response["model_sha256"]!=row.get("structural_model_sha256"):errors.append(f"DEFLECTION_{i}_MODEL_MISMATCH")
            if response.get("status") not in (None,"APPROVED"):errors.append(f"DEFLECTION_{i}_ANALYSIS_NOT_APPROVED")
        evidence.append(f"member={row.get('member_id')} deflection={row.get('calculated_deflection_mm')}mm allowable={allowable:g}mm combination={row.get('load_combination_id')} limit={(limit or {}).get('code')}:{(limit or {}).get('clause')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_rainwater_maintenance_access_geometry(rule, snapshot):
    rows=_context(snapshot).get("rainwater_maintenance_access_paths")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["rainwater_maintenance_access_paths[]"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("path_id","target_type","path_points","required_clear_width_m","corridor_polygon","obstacle_polygons","accessible_entrance_point","target_access_point"):
            if row.get(key) in (None,""):missing.append(f"rainwater_maintenance_access_paths[{i}].{key}")
        points=row.get("path_points") or [];corridor=row.get("corridor_polygon") or []
        if len(points)<2:missing.append(f"rainwater_maintenance_access_paths[{i}].path_points[minimum_2]");continue
        if len(corridor)<3:missing.append(f"rainwater_maintenance_access_paths[{i}].corridor_polygon[minimum_3]");continue
        if row.get("required_clear_width_m") is None:continue
        width=float(row["required_clear_width_m"])
        if row.get("target_type")=="MEP_ONLY_CORRIDOR" and width<.6:errors.append(f"ACCESS_{i}_REQUIRED_WIDTH_BELOW_0_6_M")
        line=LineString(points);footprint=line.buffer(width/2,cap_style=2,join_style=2);corridor_shape=Polygon(corridor)
        if not corridor_shape.covers(footprint):errors.append(f"ACCESS_{i}_CLEAR_FOOTPRINT_OUTSIDE_CORRIDOR")
        entrance=row.get("accessible_entrance_point");target=row.get("target_access_point")
        if entrance and Point(points[0]).distance(Point(entrance))>1e-6:errors.append(f"ACCESS_{i}_START_NOT_CONNECTED_TO_ENTRANCE")
        if target and Point(points[-1]).distance(Point(target))>1e-6:errors.append(f"ACCESS_{i}_END_NOT_CONNECTED_TO_TARGET")
        for j,obstacle in enumerate(row.get("obstacle_polygons") or []):
            polygon=obstacle.get("polygon") if isinstance(obstacle,dict) else obstacle
            if len(polygon or [])<3:missing.append(f"rainwater_maintenance_access_paths[{i}].obstacle_polygons[{j}].polygon");continue
            if footprint.intersects(Polygon(polygon)):errors.append(f"ACCESS_{i}_FOOTPRINT_BLOCKED_BY_OBSTACLE_{j}")
        if row.get("target_type") not in ("MEP_ONLY_CORRIDOR","LIGHTWELL_CLEANING","PATIO_CLEANING","EXTERIOR_ELEMENT_CLEANING"):errors.append(f"ACCESS_{i}_UNKNOWN_TARGET_TYPE")
        evidence.append(f"access={row.get('path_id')} target={row.get('target_type')} width={row.get('required_clear_width_m')}m entrance={row.get('accessible_entrance_point')} point={row.get('target_access_point')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_parking_ramp_slope_geometry(rule, snapshot):
    rows=_context(snapshot).get("parking_ramp_profiles")
    if rows is None or not rows:return _result(rule,INPUT_REQUIRED,missing=["parking_ramp_profiles[]"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("ramp_id","parking_type","covered","parking_size","profile_points"):
            if row.get(key) in (None,""):missing.append(f"parking_ramp_profiles[{i}].{key}")
        pts=row.get("profile_points") or []
        if len(pts)<4:missing.append(f"parking_ramp_profiles[{i}].profile_points[entrance_1m_body_exit_1m]");continue
        pts=sorted(pts,key=lambda p:float(p[0]));length=float(pts[-1][0])-float(pts[0][0])
        if length<=2:errors.append(f"PARKING_RAMP_{i}_LENGTH_NOT_GREATER_THAN_2_M");continue
        if abs(float(pts[1][0])-float(pts[0][0])-1)>1e-6 or abs(float(pts[-1][0])-float(pts[-2][0])-1)>1e-6:missing.append(f"parking_ramp_profiles[{i}].explicit_first_and_last_1m_points");continue
        slopes=[abs((float(b[1])-float(a[1]))/(float(b[0])-float(a[0])))*100 for a,b in zip(pts,pts[1:])]
        if slopes[0]>10+1e-6 or slopes[-1]>10+1e-6:errors.append(f"PARKING_RAMP_{i}_END_ZONE_SLOPE_ABOVE_10_PERCENT")
        kind=row["parking_type"];covered=bool(row["covered"]);size=row["parking_size"]
        if kind=="PUBLIC" and covered:body_limit=16 if length>20 else 17
        elif kind=="PRIVATE" and not covered and size in ("MEDIUM","LARGE"):body_limit=15
        elif kind=="PRIVATE" and covered and size=="SMALL":body_limit=17
        else:missing.append(f"parking_ramp_profiles[{i}].supported_applicability_class");continue
        if any(s>body_limit+1e-6 for s in slopes[1:-1]):errors.append(f"PARKING_RAMP_{i}_BODY_SLOPE_ABOVE_{body_limit}_PERCENT")
        evidence.append(f"ramp={row.get('ramp_id')} length={length:g}m slopes={[round(v,4) for v in slopes]} limit={body_limit}%")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _route_elevation_at_xy(points, xy):
    """Interpolate the bottom-envelope elevation on a 3D route polyline."""
    target=Point(float(xy[0]),float(xy[1]))
    for start,end in zip(points,points[1:]):
        segment=LineString([(float(start[0]),float(start[1])),(float(end[0]),float(end[1]))])
        if segment.distance(target)<=1e-7:
            length=segment.length
            fraction=0.0 if length<=1e-12 else segment.project(target)/length
            return float(start[2])+(float(end[2])-float(start[2]))*fraction
    raise ValueError("point is not on route")


def _m4_parking_service_clearance_geometry(rule, snapshot):
    context=_context(snapshot);rows=context.get("parking_service_clearance_routes")
    absent=context.get("parking_service_clearance_verified_absent")
    if rows and absent is True:
        return _result(rule,FAIL,errors=["PARKING_CLEARANCE_ROWS_CONTRADICT_VERIFIED_ABSENCE"])
    if rows is None:
        return (_result(rule,NOT_APPLICABLE,evidence=["parking_service_clearance_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["parking_service_clearance_routes[]","parking_service_clearance_verified_absent"]))
    if not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["parking_service_clearance_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["parking_service_clearance_verified_absent"]))
    missing=[];errors=[];evidence=[]
    limits=rule["parameters"]["minimum_clearance_m"]
    for i,row in enumerate(rows):
        for key in ("route_id","parking_zone_id","parking_size","parking_polygon","floor_elevation_m",
                    "bottom_envelope_points","envelope_components","selected_route"):
            if row.get(key) in (None,""):missing.append(f"parking_service_clearance_routes[{i}].{key}")
        polygon_points=row.get("parking_polygon") or []
        route=row.get("bottom_envelope_points") or []
        if len(polygon_points)<3:missing.append(f"parking_service_clearance_routes[{i}].parking_polygon[minimum_3]")
        if len(route)<2 or any(len(point)!=3 for point in route):missing.append(f"parking_service_clearance_routes[{i}].bottom_envelope_points[minimum_2_xyz]")
        components=set(row.get("envelope_components") or [])
        if not {"PIPE","INSULATION","SUPPORT"}.issubset(components):
            missing.append(f"parking_service_clearance_routes[{i}].envelope_components[PIPE_INSULATION_SUPPORT]")
        size=row.get("parking_size")
        if size not in limits:
            errors.append(f"PARKING_CLEARANCE_{i}_UNKNOWN_PARKING_SIZE")
        if missing and (len(polygon_points)<3 or len(route)<2 or any(len(point)!=3 for point in route) or size not in limits):continue
        polygon=Polygon(polygon_points)
        if not polygon.is_valid or polygon.area<=0:
            errors.append(f"PARKING_CLEARANCE_{i}_INVALID_PARKING_POLYGON");continue

        def assess(candidate):
            line=LineString([(float(p[0]),float(p[1])) for p in candidate])
            intersection=line.intersection(polygon)
            if intersection.is_empty:return None,None
            sample_points=[]
            geometries=list(intersection.geoms) if hasattr(intersection,"geoms") else [intersection]
            for geometry in geometries:
                if geometry.geom_type=="Point":sample_points.append((geometry.x,geometry.y))
                elif hasattr(geometry,"coords"):sample_points.extend(list(geometry.coords))
            clearance=min(_route_elevation_at_xy(candidate,point)-float(row["floor_elevation_m"])
                          for point in sample_points)
            return clearance,intersection

        original_clearance,intersection=assess(route)
        if intersection is None:
            errors.append(f"PARKING_CLEARANCE_{i}_ROUTE_DOES_NOT_INTERSECT_DECLARED_ZONE");continue
        minimum=float(limits[size]);selected=row.get("selected_route")
        if original_clearance+1e-9>=minimum:
            if selected!="ORIGINAL":errors.append(f"PARKING_CLEARANCE_{i}_CONTRADICTORY_SELECTED_ROUTE")
            chosen_clearance=original_clearance
        else:
            reroute=row.get("reroute_bottom_envelope_points") or []
            if selected!="REROUTE":
                errors.append(f"PARKING_CLEARANCE_{i}_BELOW_{minimum:.2f}_M_AND_NO_SELECTED_REROUTE");continue
            if len(reroute)<2 or any(len(point)!=3 for point in reroute):
                missing.append(f"parking_service_clearance_routes[{i}].reroute_bottom_envelope_points[minimum_2_xyz]");continue
            chosen_clearance,reroute_intersection=assess(reroute)
            if reroute_intersection is None:
                errors.append(f"PARKING_CLEARANCE_{i}_REROUTE_DOES_NOT_INTERSECT_DECLARED_ZONE");continue
            if chosen_clearance+1e-9<minimum:
                errors.append(f"PARKING_CLEARANCE_{i}_REROUTE_BELOW_{minimum:.2f}_M")
        evidence.append(f"route={row.get('route_id')} zone={row.get('parking_zone_id')} size={size} selected={selected} clearance={chosen_clearance:.3f}m minimum={minimum:.2f}m")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_patio_natural_ventilation_dependency(rule, snapshot):
    context=_context(snapshot);rows=context.get("covered_patio_natural_ventilation_reviews")
    absent=context.get("covered_transparent_patios_verified_absent")
    if rows and absent is True:return _result(rule,FAIL,errors=["PATIO_VENTILATION_ROWS_CONTRADICT_VERIFIED_ABSENCE"])
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["covered_transparent_patios_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["covered_patio_natural_ventilation_reviews[]","covered_transparent_patios_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("patio_id","cover_material_type","patio_polygon","architecture_geometry_sha256","ventilation_analysis"):
            if row.get(key) in (None,""):missing.append(f"covered_patio_natural_ventilation_reviews[{i}].{key}")
        polygon=row.get("patio_polygon") or []
        if len(polygon)<3:missing.append(f"covered_patio_natural_ventilation_reviews[{i}].patio_polygon[minimum_3]")
        if row.get("cover_material_type") not in (None,"TRANSPARENT"):
            errors.append(f"PATIO_VENTILATION_{i}_CONTRACT_ONLY_APPLIES_TO_TRANSPARENT_COVER")
        analysis=row.get("ventilation_analysis") or {};provenance=analysis.get("evidence_provenance") or {}
        for key in ("analysis_id","analysis_method","model_sha256","status","owner_module","required_open_area_m2","provided_open_area_m2","opening_polygons","airflow_path_geometry_ids","owner_review_id"):
            if analysis.get(key) in (None,"",[]):missing.append(f"covered_patio_natural_ventilation_reviews[{i}].ventilation_analysis.{key}")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
            missing.append(f"covered_patio_natural_ventilation_reviews[{i}].ventilation_analysis.valid_provenance")
        if analysis.get("owner_module") not in (None,"architecture"):errors.append(f"PATIO_VENTILATION_{i}_OWNER_MODULE_NOT_ARCHITECTURE")
        if analysis.get("model_sha256") and row.get("architecture_geometry_sha256") and analysis["model_sha256"]!=row["architecture_geometry_sha256"]:
            errors.append(f"PATIO_VENTILATION_{i}_MODEL_HASH_MISMATCH")
        openings=analysis.get("opening_polygons") or []
        if any(len(points)<3 for points in openings):missing.append(f"covered_patio_natural_ventilation_reviews[{i}].ventilation_analysis.opening_polygons[minimum_3]")
        if openings and analysis.get("provided_open_area_m2") is not None:
            area=sum(Polygon(points).area for points in openings)
            if abs(area-float(analysis["provided_open_area_m2"]))>1e-6:errors.append(f"PATIO_VENTILATION_{i}_OPENING_AREA_GEOMETRY_MISMATCH")
        if analysis.get("required_open_area_m2") is not None and analysis.get("provided_open_area_m2") is not None and float(analysis["provided_open_area_m2"])+1e-9<float(analysis["required_open_area_m2"]):
            errors.append(f"PATIO_VENTILATION_{i}_PROVIDED_OPEN_AREA_BELOW_ARCHITECTURAL_REQUIREMENT")
        if analysis.get("status") not in (None,"APPROVED"):errors.append(f"PATIO_VENTILATION_{i}_ARCHITECTURE_REVIEW_NOT_APPROVED")
        evidence.append(f"patio={row.get('patio_id')} architecture_analysis={analysis.get('analysis_id')} model={analysis.get('model_sha256')} required={analysis.get('required_open_area_m2')}m2 provided={analysis.get('provided_open_area_m2')}m2")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_exterior_intermediary_finish_durability(rule, snapshot):
    context=_context(snapshot);rows=context.get("exterior_intermediary_element_finishes")
    absent=context.get("exterior_intermediary_elements_verified_absent")
    if rows and absent is True:return _result(rule,FAIL,errors=["EXTERIOR_FINISH_ROWS_CONTRADICT_VERIFIED_ABSENCE"])
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["exterior_intermediary_elements_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["exterior_intermediary_element_finishes[]","exterior_intermediary_elements_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("element_id","element_type","element_polygon","exterior_exposures","selected_finish","maintenance_plan_id"):
            if row.get(key) in (None,"",[]):missing.append(f"exterior_intermediary_element_finishes[{i}].{key}")
        polygon=row.get("element_polygon") or []
        if len(polygon)<3:missing.append(f"exterior_intermediary_element_finishes[{i}].element_polygon[minimum_3]")
        elif not Polygon(polygon).is_valid or Polygon(polygon).area<=0:errors.append(f"EXTERIOR_FINISH_{i}_INVALID_ELEMENT_POLYGON")
        finish=row.get("selected_finish") or {};approval=finish.get("product_approval") or {};provenance=approval.get("evidence_provenance") or {}
        for key in ("product_identity","material","standard","suitable_exposures","application_detail_id","product_approval"):
            if finish.get(key) in (None,"",[]):missing.append(f"exterior_intermediary_element_finishes[{i}].selected_finish.{key}")
        for key in ("approval_id","issuer","issuer_competent","product_identity","standard"):
            if approval.get(key) in (None,""):missing.append(f"exterior_intermediary_element_finishes[{i}].selected_finish.product_approval.{key}")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
            missing.append(f"exterior_intermediary_element_finishes[{i}].selected_finish.product_approval.valid_provenance")
        if approval.get("product_identity") and finish.get("product_identity") and approval["product_identity"]!=finish["product_identity"]:errors.append(f"EXTERIOR_FINISH_{i}_APPROVAL_PRODUCT_MISMATCH")
        if approval.get("standard") and finish.get("standard") and approval["standard"]!=finish["standard"]:errors.append(f"EXTERIOR_FINISH_{i}_APPROVAL_STANDARD_MISMATCH")
        if approval.get("issuer_competent") is False:errors.append(f"EXTERIOR_FINISH_{i}_APPROVAL_ISSUER_NOT_COMPETENT")
        uncovered=set(row.get("exterior_exposures") or [])-set(finish.get("suitable_exposures") or [])
        if uncovered:errors.append(f"EXTERIOR_FINISH_{i}_UNSUPPORTED_EXPOSURES:{','.join(sorted(uncovered))}")
        evidence.append(f"element={row.get('element_id')} finish={finish.get('product_identity')} standard={finish.get('standard')} approval={approval.get('approval_id')} maintenance={row.get('maintenance_plan_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_external_light_air_conduit_exclusive_use(rule, snapshot):
    context=_context(snapshot);rows=context.get("external_light_air_conduit_route_inventories")
    absent=context.get("external_light_air_conduits_verified_absent")
    if rows and absent is True:return _result(rule,FAIL,errors=["LIGHT_AIR_CONDUIT_ROWS_CONTRADICT_VERIFIED_ABSENCE"])
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["external_light_air_conduits_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["external_light_air_conduit_route_inventories[]","external_light_air_conduits_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("conduit_id","conduit_polygon","required_functions","service_route_inventory_sha256","service_route_inventory_complete","service_routes"):
            if row.get(key) in (None,""):missing.append(f"external_light_air_conduit_route_inventories[{i}].{key}")
        polygon_points=row.get("conduit_polygon") or []
        if len(polygon_points)<3:missing.append(f"external_light_air_conduit_route_inventories[{i}].conduit_polygon[minimum_3]");continue
        polygon=Polygon(polygon_points)
        if not polygon.is_valid or polygon.area<=0:errors.append(f"LIGHT_AIR_CONDUIT_{i}_INVALID_POLYGON");continue
        if row.get("service_route_inventory_complete") is not True:missing.append(f"external_light_air_conduit_route_inventories[{i}].service_route_inventory_complete=true")
        provenance=row.get("route_inventory_provenance") or {}
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
            missing.append(f"external_light_air_conduit_route_inventories[{i}].route_inventory_provenance")
        functions=set(row.get("required_functions") or [])
        if not functions.intersection({"MANDATORY_LIGHT","MANDATORY_NATURAL_VENTILATION"}):errors.append(f"LIGHT_AIR_CONDUIT_{i}_MANDATORY_FUNCTION_NOT_DECLARED")
        for j,route in enumerate(row.get("service_routes") or []):
            points=route.get("route_points") or []
            if route.get("route_id") in (None,"") or route.get("system") in (None,"") or len(points)<2:
                missing.append(f"external_light_air_conduit_route_inventories[{i}].service_routes[{j}].typed_route");continue
            overlap=LineString(points).intersection(polygon).length
            if overlap>1e-7:errors.append(f"LIGHT_AIR_CONDUIT_{i}_USED_BY_SERVICE_ROUTE_{route.get('route_id')}")
        calculated_inventory_hash=sha256(json.dumps(row.get("service_routes") or [],sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if row.get("service_route_inventory_sha256")!=calculated_inventory_hash:
            errors.append(f"LIGHT_AIR_CONDUIT_{i}_ROUTE_INVENTORY_HASH_MISMATCH")
        evidence.append(f"conduit={row.get('conduit_id')} functions={sorted(functions)} inventory={row.get('service_route_inventory_sha256')} routes={len(row.get('service_routes') or [])}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_parking_ramp_nonslip_surface(rule, snapshot):
    context=_context(snapshot);rows=context.get("parking_ramp_surface_finishes")
    stage=context.get("project_stage")
    if stage not in {"DESIGN","PERMIT_CHANGE","CONSTRUCTION","FINAL_INSPECTION"}:
        return _result(rule,INPUT_REQUIRED,missing=["project_stage[supported_stage]"])
    absent=context.get("parking_ramps_verified_absent")
    if rows and absent is True:return _result(rule,FAIL,errors=["PARKING_RAMP_FINISH_ROWS_CONTRADICT_VERIFIED_ABSENCE"])
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["parking_ramps_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["parking_ramp_surface_finishes[]","parking_ramps_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("ramp_id","ramp_polygon","selected_surface"):
            if row.get(key) in (None,""):missing.append(f"parking_ramp_surface_finishes[{i}].{key}")
        polygon=row.get("ramp_polygon") or []
        if len(polygon)<3:missing.append(f"parking_ramp_surface_finishes[{i}].ramp_polygon[minimum_3]")
        elif not Polygon(polygon).is_valid or Polygon(polygon).area<=0:errors.append(f"PARKING_RAMP_FINISH_{i}_INVALID_POLYGON")
        surface=row.get("selected_surface") or {};approval=surface.get("product_approval") or {};test=surface.get("wet_slip_test") or {}
        for key in ("product_identity","material","application_detail_id","product_approval"):
            if surface.get(key) in (None,""):missing.append(f"parking_ramp_surface_finishes[{i}].selected_surface.{key}")
        for key in ("approval_id","issuer","issuer_competent","product_identity","approved_for_vehicle_ramp_wet"):
            if approval.get(key) in (None,""):missing.append(f"parking_ramp_surface_finishes[{i}].selected_surface.product_approval.{key}")
        physical_acceptance_required=stage in {"CONSTRUCTION","FINAL_INSPECTION"}
        if physical_acceptance_required and not test:
            missing.append(f"parking_ramp_surface_finishes[{i}].selected_surface.wet_slip_test[{stage}]")
        if test:
            for key in ("report_id","standard","condition","status","laboratory","product_identity"):
                if test.get(key) in (None,""):missing.append(f"parking_ramp_surface_finishes[{i}].selected_surface.wet_slip_test.{key}")
        for label,record in (("product_approval",approval),("wet_slip_test",test)):
            if not record and label=="wet_slip_test" and not physical_acceptance_required:continue
            provenance=record.get("evidence_provenance") or {}
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
                missing.append(f"parking_ramp_surface_finishes[{i}].selected_surface.{label}.valid_provenance")
        accreditation=test.get("laboratory_accreditation") or {};accreditation_provenance=accreditation.get("evidence_provenance") or {}
        if test:
            for key in ("accreditation_id","laboratory","scope_standards"):
                if accreditation.get(key) in (None,"",[]):missing.append(f"parking_ramp_surface_finishes[{i}].selected_surface.wet_slip_test.laboratory_accreditation.{key}")
            if accreditation_provenance.get("verification_status")!="VALID" or not accreditation_provenance.get("source_sha256"):
                missing.append(f"parking_ramp_surface_finishes[{i}].selected_surface.wet_slip_test.laboratory_accreditation.valid_provenance")
        if approval.get("product_identity") and surface.get("product_identity") and approval["product_identity"]!=surface["product_identity"]:errors.append(f"PARKING_RAMP_FINISH_{i}_APPROVAL_PRODUCT_MISMATCH")
        if test.get("product_identity") and surface.get("product_identity") and test["product_identity"]!=surface["product_identity"]:errors.append(f"PARKING_RAMP_FINISH_{i}_TEST_PRODUCT_MISMATCH")
        if approval.get("approved_for_vehicle_ramp_wet") is False:errors.append(f"PARKING_RAMP_FINISH_{i}_NOT_APPROVED_FOR_WET_VEHICLE_RAMP")
        if approval.get("issuer_competent") is False:errors.append(f"PARKING_RAMP_FINISH_{i}_APPROVAL_ISSUER_NOT_COMPETENT")
        if accreditation.get("laboratory") and test.get("laboratory") and accreditation["laboratory"]!=test["laboratory"]:errors.append(f"PARKING_RAMP_FINISH_{i}_LAB_ACCREDITATION_IDENTITY_MISMATCH")
        if test.get("standard") and test["standard"] not in set(accreditation.get("scope_standards") or []):errors.append(f"PARKING_RAMP_FINISH_{i}_TEST_STANDARD_OUTSIDE_LAB_SCOPE")
        if test.get("condition") not in (None,"WET"):errors.append(f"PARKING_RAMP_FINISH_{i}_SLIP_TEST_NOT_WET")
        if test.get("status") not in (None,"PASS"):errors.append(f"PARKING_RAMP_FINISH_{i}_SLIP_TEST_NOT_PASS")
        evidence.append(f"ramp={row.get('ramp_id')} stage={stage} surface={surface.get('product_identity')} approval={approval.get('approval_id')} wet_test={test.get('report_id','NOT_REQUIRED_AT_DESIGN')}:{test.get('status','NOT_REQUIRED_AT_DESIGN')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_light_air_conduit_traffic_guard_dependency(rule, snapshot):
    context=_context(snapshot);rows=context.get("external_light_air_conduit_traffic_guards")
    absent=context.get("traffic_exposed_light_air_conduits_verified_absent")
    if rows and absent is True:return _result(rule,FAIL,errors=["LIGHT_AIR_GUARD_ROWS_CONTRADICT_VERIFIED_ABSENCE"])
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["traffic_exposed_light_air_conduits_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["external_light_air_conduit_traffic_guards[]","traffic_exposed_light_air_conduits_verified_absent"]))
    missing=[];errors=[];evidence=[];tolerance=float(rule["parameters"]["qa_measurement_tolerance_m"])
    for i,row in enumerate(rows):
        for key in ("conduit_id","traffic_types","top_surface_elevation_points","adjacent_ground_elevation_points","guard_product","structural_guard_analysis","accessibility_review","geometry_sha256"):
            if row.get(key) in (None,"",[]):missing.append(f"external_light_air_conduit_traffic_guards[{i}].{key}")
        top=row.get("top_surface_elevation_points") or [];ground=row.get("adjacent_ground_elevation_points") or []
        if len(top)<2 or len(ground)<2 or len(top)!=len(ground) or any(len(point)!=3 for point in top+ground):
            missing.append(f"external_light_air_conduit_traffic_guards[{i}].paired_xyz_elevation_points")
        elif max(abs(float(a[2])-float(b[2])) for a,b in zip(top,ground))>tolerance:
            errors.append(f"LIGHT_AIR_GUARD_{i}_TOP_NOT_FLUSH_WITH_GROUND")
        traffic=set(row.get("traffic_types") or [])
        if traffic-set(rule["parameters"]["supported_traffic_types"]):errors.append(f"LIGHT_AIR_GUARD_{i}_UNKNOWN_TRAFFIC_TYPE")
        product=row.get("guard_product") or {};approval=product.get("product_approval") or {};approval_provenance=approval.get("evidence_provenance") or {}
        for key in ("product_identity","material","product_approval"):
            if product.get(key) in (None,""):missing.append(f"external_light_air_conduit_traffic_guards[{i}].guard_product.{key}")
        if product.get("material") not in (None,"METAL"):errors.append(f"LIGHT_AIR_GUARD_{i}_GUARD_NOT_METAL")
        for key in ("approval_id","issuer","issuer_competent","product_identity"):
            if approval.get(key) in (None,""):missing.append(f"external_light_air_conduit_traffic_guards[{i}].guard_product.product_approval.{key}")
        if approval_provenance.get("verification_status")!="VALID" or not approval_provenance.get("source_sha256"):missing.append(f"external_light_air_conduit_traffic_guards[{i}].guard_product.product_approval.valid_provenance")
        structural=row.get("structural_guard_analysis") or {};structural_provenance=structural.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","status","load_case_types","engineer_approval_id"):
            if structural.get(key) in (None,"",[]):missing.append(f"external_light_air_conduit_traffic_guards[{i}].structural_guard_analysis.{key}")
        if structural_provenance.get("verification_status")!="VALID" or not structural_provenance.get("source_sha256"):missing.append(f"external_light_air_conduit_traffic_guards[{i}].structural_guard_analysis.valid_provenance")
        if structural.get("model_sha256") and structural["model_sha256"]!=row.get("geometry_sha256"):errors.append(f"LIGHT_AIR_GUARD_{i}_STRUCTURAL_MODEL_HASH_MISMATCH")
        if structural.get("status") not in (None,"APPROVED"):errors.append(f"LIGHT_AIR_GUARD_{i}_STRUCTURAL_ANALYSIS_NOT_APPROVED")
        if not traffic.issubset(set(structural.get("load_case_types") or [])):errors.append(f"LIGHT_AIR_GUARD_{i}_TRAFFIC_LOAD_CASE_MISSING")
        accessibility=row.get("accessibility_review") or {};access_provenance=accessibility.get("evidence_provenance") or {}
        for key in ("review_id","model_sha256","status","owner_module","accessible_route_geometry_ids"):
            if accessibility.get(key) in (None,"",[]):missing.append(f"external_light_air_conduit_traffic_guards[{i}].accessibility_review.{key}")
        if access_provenance.get("verification_status")!="VALID" or not access_provenance.get("source_sha256"):missing.append(f"external_light_air_conduit_traffic_guards[{i}].accessibility_review.valid_provenance")
        if accessibility.get("owner_module") not in (None,"architecture_accessibility"):errors.append(f"LIGHT_AIR_GUARD_{i}_ACCESSIBILITY_OWNER_INVALID")
        if accessibility.get("model_sha256") and accessibility["model_sha256"]!=row.get("geometry_sha256"):errors.append(f"LIGHT_AIR_GUARD_{i}_ACCESSIBILITY_MODEL_HASH_MISMATCH")
        if accessibility.get("status") not in (None,"APPROVED"):errors.append(f"LIGHT_AIR_GUARD_{i}_ACCESSIBILITY_REVIEW_NOT_APPROVED")
        evidence.append(f"conduit={row.get('conduit_id')} traffic={sorted(traffic)} product={product.get('product_identity')} structural={structural.get('analysis_id')} accessibility={accessibility.get('review_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_light_air_conduit_semi_open_finish_dependency(rule, snapshot):
    context=_context(snapshot);rows=context.get("external_light_air_conduit_semi_open_finish_reviews")
    absent=context.get("external_light_air_conduits_verified_absent")
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["external_light_air_conduits_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["external_light_air_conduit_semi_open_finish_reviews[]","external_light_air_conduits_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for key in ("conduit_id","floor_polygon","wall_surface_ids","architecture_geometry_sha256","semi_open_finish_review"):
            if row.get(key) in (None,"",[]):missing.append(f"external_light_air_conduit_semi_open_finish_reviews[{i}].{key}")
        if len(row.get("floor_polygon") or [])<3:missing.append(f"external_light_air_conduit_semi_open_finish_reviews[{i}].floor_polygon[minimum_3]")
        review=row.get("semi_open_finish_review") or {};provenance=review.get("evidence_provenance") or {}
        for key in ("review_id","model_sha256","status","owner_module","governing_clause_ids","floor_finish_schedule_id","wall_finish_schedule_ids","owner_approval_id"):
            if review.get(key) in (None,"",[]):missing.append(f"external_light_air_conduit_semi_open_finish_reviews[{i}].semi_open_finish_review.{key}")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"external_light_air_conduit_semi_open_finish_reviews[{i}].semi_open_finish_review.valid_provenance")
        if review.get("owner_module") not in (None,"architecture"):errors.append(f"LIGHT_AIR_FINISH_{i}_OWNER_MODULE_NOT_ARCHITECTURE")
        if review.get("model_sha256") and review["model_sha256"]!=row.get("architecture_geometry_sha256"):errors.append(f"LIGHT_AIR_FINISH_{i}_MODEL_HASH_MISMATCH")
        if review.get("status") not in (None,"APPROVED"):errors.append(f"LIGHT_AIR_FINISH_{i}_ARCHITECTURE_REVIEW_NOT_APPROVED")
        evidence.append(f"conduit={row.get('conduit_id')} architecture_review={review.get('review_id')} floor_schedule={review.get('floor_finish_schedule_id')} wall_schedules={review.get('wall_finish_schedule_ids')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _valid_owner_response(response, *, owner, model_hash, prefix, missing, errors):
    provenance=response.get("evidence_provenance") or {}
    for key in ("review_id","owner_module","model_sha256","status","owner_approval_id"):
        if response.get(key) in (None,""):missing.append(f"{prefix}.{key}")
    if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{prefix}.valid_provenance")
    if response.get("owner_module") not in (None,owner):errors.append(f"{prefix.upper().replace('.','_')}_OWNER_MISMATCH")
    if response.get("model_sha256") and response["model_sha256"]!=model_hash:errors.append(f"{prefix.upper().replace('.','_')}_MODEL_HASH_MISMATCH")
    if response.get("status") not in (None,"APPROVED"):errors.append(f"{prefix.upper().replace('.','_')}_NOT_APPROVED")


def _m4_under_open_space_parking_dependency(rule, snapshot):
    context=_context(snapshot);rows=context.get("under_open_space_parking_reviews")
    absent=context.get("under_open_space_parking_verified_absent")
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["under_open_space_parking_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["under_open_space_parking_reviews[]","under_open_space_parking_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        prefix=f"under_open_space_parking_reviews[{i}]"
        for key in ("parking_id","building_group","parking_footprint_polygon","architecture_geometry_sha256","rainwater_interface_ids"):
            if row.get(key) in (None,"",[]):missing.append(f"{prefix}.{key}")
        if row.get("building_group") not in (None,6,7,8):errors.append(f"UNDER_OPEN_PARKING_{i}_BUILDING_GROUP_OUTSIDE_CLAUSE")
        if len(row.get("parking_footprint_polygon") or [])<3:missing.append(f"{prefix}.parking_footprint_polygon[minimum_3]")
        for field,owner in (("urban_development_review","urban_planning"),("basement_projection_review","architecture"),("emergency_access_review","fire_emergency_access")):
            response=row.get(field) or {}
            if not response:missing.append(f"{prefix}.{field}")
            _valid_owner_response(response,owner=owner,model_hash=row.get("architecture_geometry_sha256"),prefix=f"{prefix}.{field}",missing=missing,errors=errors)
        evidence.append(f"parking={row.get('parking_id')} group={row.get('building_group')} rainwater_interfaces={row.get('rainwater_interface_ids')} owner_reviews=urban_planning,architecture,fire_emergency_access")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_basement_parking_light_ventilation_dependency(rule, snapshot):
    context=_context(snapshot);rows=context.get("basement_parking_light_ventilation_strategies")
    absent=context.get("basement_parking_verified_absent")
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["basement_parking_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["basement_parking_light_ventilation_strategies[]","basement_parking_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        prefix=f"basement_parking_light_ventilation_strategies[{i}]"
        for key in ("parking_id","basement_storey_count","direct_open_air_openings_possible","selected_strategy","architecture_geometry_sha256"):
            if row.get(key) in (None,""):missing.append(f"{prefix}.{key}")
        try:storeys=int(row.get("basement_storey_count"))
        except (TypeError,ValueError):continue
        strategy=row.get("selected_strategy")
        if strategy in {"SUNKEN_GARDEN","EXTERNAL_LIGHT_AIR_CONDUIT"}:
            if storeys!=1:errors.append(f"BASEMENT_PARKING_{i}_PASSIVE_LIGHT_AIR_STRATEGY_ONLY_ONE_BASEMENT")
            if not row.get("strategy_geometry_ids"):missing.append(f"{prefix}.strategy_geometry_ids")
            response=row.get("architecture_strategy_review") or {}
            _valid_owner_response(response,owner="architecture",model_hash=row.get("architecture_geometry_sha256"),prefix=f"{prefix}.architecture_strategy_review",missing=missing,errors=errors)
        elif strategy=="DIRECT_OPEN_AIR":
            if row.get("direct_open_air_openings_possible") is not True:errors.append(f"BASEMENT_PARKING_{i}_DIRECT_OPEN_AIR_CONTRADICTS_FEASIBILITY")
            response=row.get("architecture_strategy_review") or {}
            _valid_owner_response(response,owner="architecture",model_hash=row.get("architecture_geometry_sha256"),prefix=f"{prefix}.architecture_strategy_review",missing=missing,errors=errors)
        elif strategy=="MECHANICAL_VENTILATION_AND_FIRE_SYSTEMS":
            for field,owner in (("mechanical_ventilation_review","mechanical_ventilation"),("fire_system_review","fire")):
                response=row.get(field) or {}
                _valid_owner_response(response,owner=owner,model_hash=row.get("architecture_geometry_sha256"),prefix=f"{prefix}.{field}",missing=missing,errors=errors)
        else:errors.append(f"BASEMENT_PARKING_{i}_UNKNOWN_STRATEGY")
        if storeys>1 and strategy!="MECHANICAL_VENTILATION_AND_FIRE_SYSTEMS":errors.append(f"BASEMENT_PARKING_{i}_MULTILEVEL_REQUIRES_MECHANICAL_AND_FIRE_DEPENDENCIES")
        evidence.append(f"parking={row.get('parking_id')} basement_storeys={storeys} strategy={strategy} architecture_model={row.get('architecture_geometry_sha256')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_transparent_roof_cleaning_safety(rule, snapshot):
    context=_context(snapshot);rows=context.get("transparent_roof_cleaning_safety_reviews")
    absent=context.get("large_transparent_roofs_verified_absent")
    if rows is None or not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["large_transparent_roofs_verified_absent=true"])
                if absent is True else _result(rule,INPUT_REQUIRED,missing=["transparent_roof_cleaning_safety_reviews[]","large_transparent_roofs_verified_absent"]))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        prefix=f"transparent_roof_cleaning_safety_reviews[{i}]"
        for key in ("roof_id","roof_polygon","cleaning_path_points","cleaning_anchor_points","architecture_geometry_sha256","structural_cleaner_load_analysis"):
            if row.get(key) in (None,"",[]):missing.append(f"{prefix}.{key}")
        polygon_points=row.get("roof_polygon") or [];path_points=row.get("cleaning_path_points") or [];anchors=row.get("cleaning_anchor_points") or []
        if len(polygon_points)<3:missing.append(f"{prefix}.roof_polygon[minimum_3]")
        if len(path_points)<2:missing.append(f"{prefix}.cleaning_path_points[minimum_2]")
        if len(polygon_points)>=3 and len(path_points)>=2:
            polygon=Polygon(polygon_points);path=LineString(path_points)
            if not polygon.covers(path):errors.append(f"TRANSPARENT_ROOF_{i}_CLEANING_PATH_OUTSIDE_ROOF")
            for j,anchor in enumerate(anchors):
                if Point(anchor).distance(path)>1e-7:errors.append(f"TRANSPARENT_ROOF_{i}_CLEANING_ANCHOR_{j}_NOT_ON_ACCESS_PATH")
        analysis=row.get("structural_cleaner_load_analysis") or {};provenance=analysis.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","status","load_case_id","load_case_type","engineer_approval_id"):
            if analysis.get(key) in (None,""):missing.append(f"{prefix}.structural_cleaner_load_analysis.{key}")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{prefix}.structural_cleaner_load_analysis.valid_provenance")
        if analysis.get("load_case_type") not in (None,"CLEANER_WEIGHT"):errors.append(f"TRANSPARENT_ROOF_{i}_CLEANER_WEIGHT_LOAD_CASE_MISSING")
        if analysis.get("model_sha256") and analysis["model_sha256"]!=row.get("architecture_geometry_sha256"):errors.append(f"TRANSPARENT_ROOF_{i}_STRUCTURAL_MODEL_HASH_MISMATCH")
        if analysis.get("status") not in (None,"APPROVED"):errors.append(f"TRANSPARENT_ROOF_{i}_STRUCTURAL_ANALYSIS_NOT_APPROVED")
        evidence.append(f"roof={row.get('roof_id')} anchors={len(anchors)} structural={analysis.get('analysis_id')} load_case={analysis.get('load_case_id')} model={analysis.get('model_sha256')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_emergency_access_rainwater_interface(rule, snapshot):
    context=_context(snapshot);rows=context.get("emergency_access_rainwater_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["emergency_access_rainwater_interfaces[]"])
    if not rows:
        return _result(rule,NOT_APPLICABLE,evidence=["emergency_access_rainwater_interfaces_verified_absent"]) if context.get("emergency_access_rainwater_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["emergency_access_rainwater_interfaces_verified_absent"])
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256")
    for i,row in enumerate(rows):
        for key in ("interface_id","building_group","rescue_area_polygon"):
            if row.get(key) in (None,""):missing.append(f"emergency_access_rainwater_interfaces[{i}].{key}")
        try: rescue=Polygon(row.get("rescue_area_polygon") or [])
        except Exception: rescue=None
        if rescue is None or not rescue.is_valid or rescue.area<=0:
            missing.append(f"emergency_access_rainwater_interfaces[{i}].rescue_area_polygon.valid")
            continue
        access=None
        if row.get("access_route_polygon"):
            try: access=Polygon(row["access_route_polygon"])
            except Exception: access=None
            if access is None or not access.is_valid or access.area<=0:missing.append(f"emergency_access_rainwater_interfaces[{i}].access_route_polygon.valid")
        group=int(row.get("building_group") or 0)
        if row.get("pitched_roof") and group in {4,5,6,7}:
            for key,minimum in (("rescue_opening_width_m",.9),("rescue_opening_height_m",1.3)):
                if row.get(key) is None:missing.append(f"emergency_access_rainwater_interfaces[{i}].{key}")
                elif float(row[key])+1e-9<minimum:errors.append(f"EMERGENCY_{i}_{key.upper()}_BELOW_{minimum}")
        if row.get("north_lot") and group in {4,6} and row.get("rescue_area_location")=="COURTYARD" and access is None:
            missing.append(f"emergency_access_rainwater_interfaces[{i}].access_route_polygon")
        for key in ("operational_min_elevation_m","operational_max_elevation_m"):
            if row.get(key) is None:missing.append(f"emergency_access_rainwater_interfaces[{i}].{key}")
        zmin=row.get("operational_min_elevation_m");zmax=row.get("operational_max_elevation_m")
        if zmin is not None and zmax is not None and float(zmax)<=float(zmin):errors.append(f"EMERGENCY_{i}_INVALID_OPERATIONAL_ELEVATION_RANGE")
        zones=[rescue]+([access] if access is not None else [])
        for j,route in enumerate(row.get("rainwater_routes") or []):
            points=route.get("selected_points")
            if not points or len(points)<2:missing.append(f"emergency_access_rainwater_interfaces[{i}].rainwater_routes[{j}].selected_points");continue
            if any(len(point)!=3 for point in points):missing.append(f"emergency_access_rainwater_interfaces[{i}].rainwater_routes[{j}].selected_points[].xyz");continue
            line=LineString([[point[0],point[1]] for point in points]);route_zmin=min(float(point[2]) for point in points);route_zmax=max(float(point[2]) for point in points)
            vertical_overlap=zmin is not None and zmax is not None and route_zmax>=float(zmin)-1e-7 and route_zmin<=float(zmax)+1e-7
            if vertical_overlap and any(line.intersection(zone).length>1e-7 for zone in zones):errors.append(f"EMERGENCY_{i}_ROUTE_{j}_OCCUPIES_RESCUE_ACCESS_3D")
            evidence.append(f"emergency_route={route.get('route_id')} selected_length_m={line.length:.3f}")
        for j,item in enumerate(row.get("rainwater_equipment_footprints") or []):
            try: footprint=Polygon(item.get("polygon") or [])
            except Exception: footprint=None
            if footprint is None or not footprint.is_valid or footprint.area<=0:missing.append(f"emergency_access_rainwater_interfaces[{i}].rainwater_equipment_footprints[{j}].polygon.valid");continue
            for key in ("bottom_elevation_m","top_elevation_m"):
                if item.get(key) is None:missing.append(f"emergency_access_rainwater_interfaces[{i}].rainwater_equipment_footprints[{j}].{key}")
            item_zmin=item.get("bottom_elevation_m");item_zmax=item.get("top_elevation_m")
            if item_zmin is not None and item_zmax is not None and float(item_zmax)<float(item_zmin):errors.append(f"EMERGENCY_{i}_EQUIPMENT_{j}_INVALID_ELEVATION_RANGE")
            vertical_overlap=item_zmin is not None and item_zmax is not None and zmin is not None and zmax is not None and float(item_zmax)>=float(zmin)-1e-7 and float(item_zmin)<=float(zmax)+1e-7
            if vertical_overlap and any(footprint.intersection(zone).area>1e-7 for zone in zones):errors.append(f"EMERGENCY_{i}_EQUIPMENT_{j}_OCCUPIES_RESCUE_ACCESS_3D")
            evidence.append(f"emergency_equipment={item.get('equipment_id')} footprint_m2={footprint.area:.3f}")
        if row.get("plant_space_below_emergency_route") and group in {6,7}:
            response=row.get("heavy_vehicle_structural_response") or {};provenance=response.get("evidence_provenance") or {}
            if not model_hash:missing.append("building_geometry_sha256")
            for key in ("analysis_id","structural_model_sha256","load_case_id"):
                if not response.get(key):missing.append(f"emergency_access_rainwater_interfaces[{i}].heavy_vehicle_structural_response.{key}")
            if response.get("structural_model_sha256")!=model_hash:errors.append(f"EMERGENCY_{i}_STRUCTURAL_MODEL_HASH_MISMATCH")
            if response.get("status")!="PASS":errors.append(f"EMERGENCY_{i}_HEAVY_VEHICLE_STRUCTURE_NOT_APPROVED")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"emergency_access_rainwater_interfaces[{i}].heavy_vehicle_structural_response.valid_provenance")
            evidence.append(f"emergency_structural_analysis={response.get('analysis_id')} load_case={response.get('load_case_id')}")
        evidence.append(f"emergency_interface={row.get('interface_id')} rescue_area_m2={rescue.area:.3f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_rainwater_acoustic_interface(rule, snapshot):
    context=_context(snapshot);rows=context.get("rainwater_acoustic_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_acoustic_interfaces[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["rainwater_acoustic_interfaces_verified_absent"]) if context.get("rainwater_acoustic_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["rainwater_acoustic_interfaces_verified_absent"])
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256");receiver_levels={};receiver_limits={}
    for i,row in enumerate(rows):
        for key in ("interface_id","receiver_id","source_point_xyz","receiver_point_xyz","propagation_model"):
            if row.get(key) in (None,""):missing.append(f"rainwater_acoustic_interfaces[{i}].{key}")
        source=row.get("source_point_xyz") or [];receiver=row.get("receiver_point_xyz") or []
        if len(source)!=3 or len(receiver)!=3:missing.append(f"rainwater_acoustic_interfaces[{i}].source_receiver_xyz");continue
        distance=sqrt(sum((float(a)-float(b))**2 for a,b in zip(source,receiver)))
        if distance<=0:errors.append(f"ACOUSTIC_{i}_ZERO_RECEIVER_DISTANCE");continue
        response=row.get("m18_acoustic_limit_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("response_id","limit_dba","model_sha256"):
            if response.get(key) in (None,""):missing.append(f"rainwater_acoustic_interfaces[{i}].m18_acoustic_limit_response.{key}")
        if not model_hash:missing.append("building_geometry_sha256")
        if response.get("model_sha256")!=model_hash:errors.append(f"ACOUSTIC_{i}_MODEL_HASH_MISMATCH")
        if response.get("status")!="PASS":errors.append(f"ACOUSTIC_{i}_OWNER_RESPONSE_NOT_APPROVED")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"rainwater_acoustic_interfaces[{i}].m18_acoustic_limit_response.valid_provenance")
        insertion=float(row.get("selected_treatment_insertion_loss_dba") or 0);model=row.get("propagation_model")
        if model=="FREE_FIELD_POINT_SOURCE":
            if row.get("source_sound_power_dba") is None:missing.append(f"rainwater_acoustic_interfaces[{i}].source_sound_power_dba")
            correction=float(row.get("declared_geometry_correction_dba") or 0)
            if abs(correction)>1e-9:errors.append(f"ACOUSTIC_{i}_ARBITRARY_FREE_FIELD_CORRECTION_FORBIDDEN")
            predicted=float(row.get("source_sound_power_dba") or 0)-20*log10(distance)-11-insertion
        elif model in {"SHAFT_OR_STRUCTURE_BORNE","ENCLOSED_SPECIALIST_MODEL","LINE_SOURCE_SPECIALIST_MODEL"}:
            specialist=row.get("specialist_propagation_response") or {};specialist_provenance=specialist.get("evidence_provenance") or {}
            for key in ("analysis_id","method","predicted_receiver_level_dba","model_sha256","prediction_basis"):
                if specialist.get(key) in (None,""):missing.append(f"rainwater_acoustic_interfaces[{i}].specialist_propagation_response.{key}")
            if specialist.get("model_sha256")!=model_hash:errors.append(f"ACOUSTIC_{i}_SPECIALIST_MODEL_HASH_MISMATCH")
            if specialist.get("status")!="PASS":errors.append(f"ACOUSTIC_{i}_SPECIALIST_RESPONSE_NOT_APPROVED")
            if specialist_provenance.get("verification_status")!="VALID" or not specialist_provenance.get("source_sha256"):missing.append(f"rainwater_acoustic_interfaces[{i}].specialist_propagation_response.valid_provenance")
            basis=specialist.get("prediction_basis")
            if basis not in {"PRE_SELECTED_TREATMENT","POST_SELECTED_TREATMENT"}:
                missing.append(f"rainwater_acoustic_interfaces[{i}].specialist_propagation_response.supported_prediction_basis")
            specialist_level=float(specialist.get("predicted_receiver_level_dba") or 0)
            predicted=(specialist_level-insertion if basis=="PRE_SELECTED_TREATMENT" else specialist_level)
            if basis=="POST_SELECTED_TREATMENT" and abs(insertion)>1e-9:
                evidence.append(f"acoustic_{i}_selected_treatment_already_in_specialist_prediction={insertion:.2f}dB")
        else:
            missing.append(f"rainwater_acoustic_interfaces[{i}].supported_propagation_model")
            predicted=0.0
        declared=row.get("declared_receiver_level_dba")
        if declared is None:missing.append(f"rainwater_acoustic_interfaces[{i}].declared_receiver_level_dba")
        elif abs(float(declared)-predicted)>.1:errors.append(f"ACOUSTIC_{i}_DECLARED_LEVEL_MISMATCH")
        receiver_id=row.get("receiver_id");receiver_levels.setdefault(receiver_id,[]).append(predicted)
        if response.get("limit_dba") is not None:
            limit=float(response["limit_dba"])
            if receiver_id in receiver_limits and abs(receiver_limits[receiver_id]-limit)>.1:
                errors.append(f"ACOUSTIC_RECEIVER_{receiver_id}_INCONSISTENT_OWNER_LIMITS")
            else:
                receiver_limits[receiver_id]=limit
        evidence.append(f"acoustic={row.get('interface_id')} distance_m={distance:.3f} predicted_dba={predicted:.2f} treatment_dba={insertion:.2f}")
    for receiver_id,levels in receiver_levels.items():
        combined=10*log10(sum(10**(level/10) for level in levels))
        if receiver_id in receiver_limits and combined>receiver_limits[receiver_id]+1e-9:errors.append(f"ACOUSTIC_RECEIVER_{receiver_id}_LOG_SUM_EXCEEDS_OWNER_LIMIT")
        evidence.append(f"acoustic_receiver={receiver_id} logarithmic_sum_dba={combined:.2f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_stage_documents_materials_site_protection(rule, snapshot):
    context=_context(snapshot);stage=context.get("project_stage")
    if stage not in {"DESIGN","PERMIT_CHANGE","CONSTRUCTION","FINAL_INSPECTION"}:return _result(rule,INPUT_REQUIRED,missing=["project_stage"])
    missing=[];errors=[];evidence=[]
    docs=context.get("m4_rainwater_technical_document_register") or {}
    phase=context.get("deliverable_generation_phase")
    if phase not in {"PRE_GENERATION","POST_GENERATION_QA"}:missing.append("deliverable_generation_phase")
    for key in ("design_basis_id","calculation_basis_id","material_specification_id"):
        if not docs.get(key):missing.append(f"m4_rainwater_technical_document_register.{key}")
    if phase=="POST_GENERATION_QA":
        for key in ("plans_id","sections_id","details_id","calculations_id"):
            if not docs.get(key):missing.append(f"m4_rainwater_technical_document_register.{key}")
    evidence.append(f"m4_document_register={docs.get('register_id')} stage={stage}")
    if stage=="PERMIT_CHANGE" or docs.get("post_permit_change"):
        change=docs.get("approved_change_record") or {};provenance=change.get("evidence_provenance") or {}
        for key in ("change_id","approval_id","approved_revision"):
            if not change.get(key):missing.append(f"m4_rainwater_technical_document_register.approved_change_record.{key}")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append("m4_rainwater_technical_document_register.approved_change_record.valid_provenance")
    materials=context.get("m4_rainwater_material_selections")
    if materials is None:return _result(rule,INPUT_REQUIRED,missing=missing+["m4_rainwater_material_selections[]"])
    for i,row in enumerate(materials):
        for key in ("selection_id","product_identity","standard_or_approval"):
            if not row.get(key):missing.append(f"m4_rainwater_material_selections[{i}].{key}")
        if row.get("new_or_innovative"):
            certificate=row.get("legal_authority_certificate") or {};provenance=certificate.get("evidence_provenance") or {}
            if not certificate.get("certificate_id") or provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"m4_rainwater_material_selections[{i}].legal_authority_certificate.valid")
        evidence.append(f"m4_material={row.get('selection_id')} product={row.get('product_identity')}")
    plan=context.get("m4_construction_protection_plan") or {}
    for key in ("material_storage_method","public_utility_protection_method","protected_landscape_method"):
        if not plan.get(key):missing.append(f"m4_construction_protection_plan.{key}")
    if stage in {"CONSTRUCTION","FINAL_INSPECTION"}:
        records=context.get("m4_construction_protection_records")
        if not records:missing.append("m4_construction_protection_records[]")
        for i,row in enumerate(records or []):
            for key in ("record_id","inspection_type","inspected_at","result","project_contract_id","model_sha256","covered_protection_methods"):
                if not row.get(key):missing.append(f"m4_construction_protection_records[{i}].{key}")
            provenance=row.get("evidence_provenance") or {}
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"m4_construction_protection_records[{i}].valid_provenance")
            if row.get("project_contract_id") not in (None,context.get("project_contract_id")):errors.append(f"M4_CONSTRUCTION_PROTECTION_{i}_PROJECT_SCOPE_MISMATCH")
            if row.get("model_sha256") not in (None,context.get("building_geometry_sha256")):errors.append(f"M4_CONSTRUCTION_PROTECTION_{i}_MODEL_HASH_MISMATCH")
            expected_methods={plan.get(key) for key in ("material_storage_method","public_utility_protection_method","protected_landscape_method") if plan.get(key)}
            if row.get("covered_protection_methods") and set(row["covered_protection_methods"])!=expected_methods:errors.append(f"M4_CONSTRUCTION_PROTECTION_{i}_METHOD_COVERAGE_MISMATCH")
            if row.get("result")!="PASS":errors.append(f"M4_CONSTRUCTION_PROTECTION_{i}_NOT_ACCEPTED")
            evidence.append(f"m4_protection_record={row.get('record_id')} type={row.get('inspection_type')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_pipe_storage_construction_load(rule, snapshot):
    context=_context(snapshot);rows=context.get("construction_pipe_storage_zones")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["construction_pipe_storage_zones[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["construction_pipe_storage_zones_verified_absent"]) if context.get("construction_pipe_storage_zones_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["construction_pipe_storage_zones_verified_absent"])
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256")
    for i,row in enumerate(rows):
        for key in ("zone_id","footprint_polygon","stack_height_m","declared_total_load_kn","declared_surface_load_kn_m2"):
            if row.get(key) in (None,""):missing.append(f"construction_pipe_storage_zones[{i}].{key}")
        try: footprint=Polygon(row.get("footprint_polygon") or [])
        except Exception: footprint=None
        if footprint is None or not footprint.is_valid or footprint.area<=0:missing.append(f"construction_pipe_storage_zones[{i}].footprint_polygon.valid");continue
        height=row.get("stack_height_m")
        table_applicable=height is not None and float(height)<=1.8+1e-9 and row.get("load_method")=="VOLUMETRIC_TABLE_M6_141"
        if row.get("itemized_loads_included") and row.get("load_method")=="VOLUMETRIC_TABLE_M6_141":errors.append(f"PIPE_STORAGE_{i}_VOLUMETRIC_AND_ITEMIZED_DOUBLE_COUNT")
        if height is not None:
            if table_applicable:
                surface=float(height)*9.0;total=surface*footprint.area
            else:
                alternative=row.get("alternative_load_method_response") or {};alt_provenance=alternative.get("evidence_provenance") or {}
                for key in ("analysis_id","method","calculated_surface_load_kn_m2","calculated_total_load_kn","model_sha256"):
                    if alternative.get(key) in (None,""):missing.append(f"construction_pipe_storage_zones[{i}].alternative_load_method_response.{key}")
                if alternative.get("model_sha256")!=model_hash:errors.append(f"PIPE_STORAGE_{i}_ALTERNATIVE_MODEL_HASH_MISMATCH")
                if alternative.get("status")!="PASS":errors.append(f"PIPE_STORAGE_{i}_ALTERNATIVE_METHOD_NOT_APPROVED")
                if alt_provenance.get("verification_status")!="VALID" or not alt_provenance.get("source_sha256"):missing.append(f"construction_pipe_storage_zones[{i}].alternative_load_method_response.valid_provenance")
                surface=float(alternative.get("calculated_surface_load_kn_m2") or 0);total=float(alternative.get("calculated_total_load_kn") or 0)
            if row.get("declared_surface_load_kn_m2") is not None and abs(float(row["declared_surface_load_kn_m2"])-surface)>.01:errors.append(f"PIPE_STORAGE_{i}_SURFACE_LOAD_MISMATCH")
            if row.get("declared_total_load_kn") is not None and abs(float(row["declared_total_load_kn"])-total)>.01:errors.append(f"PIPE_STORAGE_{i}_TOTAL_LOAD_MISMATCH")
            response=row.get("structural_floor_response") or {};provenance=response.get("evidence_provenance") or {}
            for key in ("analysis_id","model_sha256","reviewed_total_load_kn"):
                if response.get(key) in (None,""):missing.append(f"construction_pipe_storage_zones[{i}].structural_floor_response.{key}")
            if not model_hash:missing.append("building_geometry_sha256")
            if response.get("model_sha256")!=model_hash:errors.append(f"PIPE_STORAGE_{i}_MODEL_HASH_MISMATCH")
            if response.get("status")!="PASS":errors.append(f"PIPE_STORAGE_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
            if response.get("reviewed_total_load_kn") is not None and abs(float(response["reviewed_total_load_kn"])-total)>.01:errors.append(f"PIPE_STORAGE_{i}_REVIEWED_LOAD_MISMATCH")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"construction_pipe_storage_zones[{i}].structural_floor_response.valid_provenance")
            evidence.append(f"pipe_storage={row.get('zone_id')} method={'M6_141_TABLE' if table_applicable else 'ALTERNATIVE'} area_m2={footprint.area:.3f} height_m={float(height):.3f} surface_kn_m2={surface:.3f} total_kn={total:.3f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rain_exposed_wood_density_load(rule, snapshot):
    context=_context(snapshot);rows=context.get("rain_exposed_wood_components")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rain_exposed_wood_components[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["rain_exposed_wood_components_verified_absent"]) if context.get("rain_exposed_wood_components_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["rain_exposed_wood_components_verified_absent"])
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256")
    for i,row in enumerate(rows):
        for key in ("component_id","volume_m3","base_dry_density_kg_m3","moisture_condition","declared_design_mass_kg"):
            if row.get(key) in (None,""):missing.append(f"rain_exposed_wood_components[{i}].{key}")
        condition=row.get("moisture_condition");base=row.get("base_dry_density_kg_m3");volume=row.get("volume_m3")
        if condition not in {"DRY_MAX_15_PERCENT","RAIN_UNPROTECTED","WATER_SATURATED","FRESH_CUT"}:errors.append(f"WOOD_LOAD_{i}_MOISTURE_CONDITION_INVALID")
        if base is not None and volume is not None:
            density=float(base)
            if condition=="RAIN_UNPROTECTED":density+=80
            elif condition=="WATER_SATURATED":density+=120
            elif condition=="FRESH_CUT":density*=1.8
            mass=density*float(volume);load=mass*9.80665/1000
            if row.get("declared_design_mass_kg") is not None and abs(float(row["declared_design_mass_kg"])-mass)>.01:errors.append(f"WOOD_LOAD_{i}_DESIGN_MASS_MISMATCH")
            response=row.get("structural_response") or {};provenance=response.get("evidence_provenance") or {}
            for key in ("analysis_id","model_sha256","reviewed_load_kn"):
                if response.get(key) in (None,""):missing.append(f"rain_exposed_wood_components[{i}].structural_response.{key}")
            if not model_hash:missing.append("building_geometry_sha256")
            if response.get("model_sha256")!=model_hash:errors.append(f"WOOD_LOAD_{i}_MODEL_HASH_MISMATCH")
            if response.get("status")!="PASS":errors.append(f"WOOD_LOAD_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
            if response.get("reviewed_load_kn") is not None and abs(float(response["reviewed_load_kn"])-load)>.001:errors.append(f"WOOD_LOAD_{i}_REVIEWED_LOAD_MISMATCH")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"rain_exposed_wood_components[{i}].structural_response.valid_provenance")
            evidence.append(f"wood={row.get('component_id')} condition={condition} density_kg_m3={density:.2f} mass_kg={mass:.2f} load_kn={load:.4f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_roof_material_volumetric_dead_load(rule, snapshot):
    context=_context(snapshot);rows=context.get("roof_material_volumetric_loads")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["roof_material_volumetric_loads[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["roof_material_volumetric_loads_verified_absent"]) if context.get("roof_material_volumetric_loads_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["roof_material_volumetric_loads_verified_absent"])
    densities={"ALUMINUM":2700,"GRAY_CAST_IRON_RAW":7200,"WHITE_CAST_IRON_RAW":7700,
        "CAST_IRON":7200,"MILD_STEEL":7850,"LEAD":11400,"COPPER":8900,"BRONZE":8500,
        "ZINC":7200,"TIN":7200,"NORMAL_CONCRETE":2400,"REINFORCED_OR_PRESTRESSED_CONCRETE":2500,
        "WET_GRAVEL":2000,"DRY_GRAVEL":1700,"WET_SAND":1800,"DRY_SAND":1550,"DUNE_SAND":1600,
        "WET_SOIL_SAND_CLAY":2100,"MOIST_15_PERCENT_SOIL_SAND_CLAY":1800,"ASPHALT":2200,
        "BITUMEN":1200,"ASBESTOS_ROOF_BOARD":2000,"CORRUGATED_ASBESTOS_SHEET":1600,
        "ASBESTOS_CEMENT_PIPE":1800,"FIBERGLASS_RESIN":1800,"PVC_SHEET":1400}
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256");seen=set()
    for i,row in enumerate(rows):
        prefix=f"roof_material_volumetric_loads[{i}]"
        for key in ("component_id","material_code","volume_m3","declared_mass_kg"):
            if row.get(key) in (None,""):missing.append(f"{prefix}.{key}")
        component=row.get("component_id")
        if component in seen:errors.append(f"ROOF_MATERIAL_{i}_DUPLICATE_COMPONENT_LOAD")
        seen.add(component)
        if row.get("included_in_other_dead_load") is True:errors.append(f"ROOF_MATERIAL_{i}_DOUBLE_COUNTED")
        code=row.get("material_code");volume=row.get("volume_m3")
        if code not in densities:errors.append(f"ROOF_MATERIAL_{i}_UNSUPPORTED_MATERIAL_CODE")
        if volume is not None and float(volume)<=0:errors.append(f"ROOF_MATERIAL_{i}_NONPOSITIVE_VOLUME")
        if code in {"ALUMINUM","GRAY_CAST_IRON_RAW","WHITE_CAST_IRON_RAW","CAST_IRON","MILD_STEEL","LEAD","COPPER","BRONZE","ZINC","TIN"}:
            geometry=row.get("component_geometry") or {};geometry_type=geometry.get("type")
            derived_volume=None
            try:
                if geometry_type=="SOLID_CYLINDER":
                    diameter=float(geometry["diameter_m"]);length=float(geometry["length_m"])
                    if diameter<=0 or length<=0:raise ValueError
                    derived_volume=pi*(diameter/2)**2*length
                elif geometry_type=="HOLLOW_CYLINDER":
                    outer=float(geometry["outer_diameter_m"]);wall=float(geometry["wall_thickness_m"]);length=float(geometry["length_m"])
                    if outer<=0 or length<=0 or wall<=0 or wall*2>=outer:raise ValueError
                    derived_volume=pi*((outer/2)**2-((outer-2*wall)/2)**2)*length
                elif geometry_type=="RECTANGULAR_SOLID":
                    width=float(geometry["width_m"]);height=float(geometry["height_m"]);length=float(geometry["length_m"])
                    if width<=0 or height<=0 or length<=0:raise ValueError
                    derived_volume=width*height*length
                elif geometry_type=="RECTANGULAR_HOLLOW":
                    width=float(geometry["outer_width_m"]);height=float(geometry["outer_height_m"]);wall=float(geometry["wall_thickness_m"]);length=float(geometry["length_m"])
                    if width<=0 or height<=0 or length<=0 or wall<=0 or wall*2>=min(width,height):raise ValueError
                    derived_volume=(width*height-(width-2*wall)*(height-2*wall))*length
            except (KeyError,TypeError,ValueError):
                errors.append(f"ROOF_MATERIAL_{i}_INVALID_TYPED_COMPONENT_GEOMETRY")
            if derived_volume is None:
                missing.append(f"{prefix}.component_geometry.supported_solid_or_hollow_dimensions")
            elif volume is not None and abs(float(volume)-derived_volume)>1e-9:
                errors.append(f"ROOF_MATERIAL_{i}_SOLID_VOLUME_GEOMETRY_MISMATCH")
        if code in densities and volume is not None and float(volume)>0:
            density=densities[code];mass=density*float(volume);load=mass*9.80665/1000
            if row.get("declared_mass_kg") is not None and abs(float(row["declared_mass_kg"])-mass)>.01:errors.append(f"ROOF_MATERIAL_{i}_MASS_MISMATCH")
            response=row.get("structural_response") or {};provenance=response.get("evidence_provenance") or {}
            for key in ("analysis_id","model_sha256","reviewed_load_kn"):
                if response.get(key) in (None,""):missing.append(f"{prefix}.structural_response.{key}")
            if not model_hash:missing.append("building_geometry_sha256")
            if response.get("model_sha256")!=model_hash:errors.append(f"ROOF_MATERIAL_{i}_MODEL_HASH_MISMATCH")
            if response.get("status")!="PASS":errors.append(f"ROOF_MATERIAL_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
            if response.get("reviewed_load_kn") is not None and abs(float(response["reviewed_load_kn"])-load)>.001:errors.append(f"ROOF_MATERIAL_{i}_REVIEWED_LOAD_MISMATCH")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{prefix}.structural_response.valid_provenance")
            evidence.append(f"roof_material={component} code={code} density_kg_m3={density} volume_m3={float(volume):.4f} mass_kg={mass:.2f} load_kn={load:.4f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_roof_covering_surface_dead_load(rule, snapshot):
    context=_context(snapshot);rows=context.get("roof_covering_surface_loads")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["roof_covering_surface_loads[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["roof_covering_surface_loads_verified_absent"]) if context.get("roof_covering_surface_loads_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["roof_covering_surface_loads_verified_absent"])
    surface_masses={"CLAY_ROOF_TILE":70,"BITUMEN_FELT_ONE_LAYER":10,"BITUMEN_FELT_TWO_LAYER":15}
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256");seen=set()
    for i,row in enumerate(rows):
        prefix=f"roof_covering_surface_loads[{i}]"
        for key in ("component_id","covering_code","area_m2","declared_mass_kg"):
            if row.get(key) in (None,""):missing.append(f"{prefix}.{key}")
        component=row.get("component_id")
        if component in seen:errors.append(f"ROOF_COVERING_{i}_DUPLICATE_COMPONENT_LOAD")
        seen.add(component)
        if row.get("included_in_other_dead_load") is True:errors.append(f"ROOF_COVERING_{i}_DOUBLE_COUNTED")
        interpretation=row.get("official_unit_interpretation") or {};provenance=interpretation.get("evidence_provenance") or {}
        for key in ("interpretation_id","unit","authority"):
            if not interpretation.get(key):missing.append(f"{prefix}.official_unit_interpretation.{key}")
        if interpretation.get("unit") not in (None,"KG_M2"):errors.append(f"ROOF_COVERING_{i}_PRINTED_UNIT_ANOMALY_UNRESOLVED")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{prefix}.official_unit_interpretation.valid_provenance")
        code=row.get("covering_code");area=row.get("area_m2")
        if code not in surface_masses:errors.append(f"ROOF_COVERING_{i}_UNSUPPORTED_COVERING_CODE")
        if area is not None and float(area)<=0:errors.append(f"ROOF_COVERING_{i}_NONPOSITIVE_AREA")
        if code in surface_masses and area is not None and float(area)>0 and interpretation.get("unit")=="KG_M2":
            unit_mass=surface_masses[code];mass=unit_mass*float(area);load=mass*9.80665/1000
            if row.get("declared_mass_kg") is not None and abs(float(row["declared_mass_kg"])-mass)>.01:errors.append(f"ROOF_COVERING_{i}_MASS_MISMATCH")
            response=row.get("structural_response") or {};response_provenance=response.get("evidence_provenance") or {}
            for key in ("analysis_id","model_sha256","reviewed_load_kn"):
                if response.get(key) in (None,""):missing.append(f"{prefix}.structural_response.{key}")
            if not model_hash:missing.append("building_geometry_sha256")
            if response.get("model_sha256")!=model_hash:errors.append(f"ROOF_COVERING_{i}_MODEL_HASH_MISMATCH")
            if response.get("status")!="PASS":errors.append(f"ROOF_COVERING_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
            if response.get("reviewed_load_kn") is not None and abs(float(response["reviewed_load_kn"])-load)>.001:errors.append(f"ROOF_COVERING_{i}_REVIEWED_LOAD_MISMATCH")
            if response_provenance.get("verification_status")!="VALID" or not response_provenance.get("source_sha256"):missing.append(f"{prefix}.structural_response.valid_provenance")
            evidence.append(f"roof_covering={component} code={code} unit_mass_kg_m2={unit_mass} area_m2={float(area):.3f} mass_kg={mass:.2f} load_kn={load:.4f} interpretation={interpretation.get('interpretation_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_vertical_rainwater_drift_compatibility(rule, snapshot):
    context=_context(snapshot);rows=context.get("vertical_rainwater_drift_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["vertical_rainwater_drift_interfaces[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["vertical_rainwater_drift_interfaces_verified_absent"]) if context.get("vertical_rainwater_drift_interfaces_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["vertical_rainwater_drift_interfaces_verified_absent"])
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256")
    for i,row in enumerate(rows):
        prefix=f"vertical_rainwater_drift_interfaces[{i}]"
        for key in ("interface_id","storey_height_m","selected_joint_allowance_mm","structural_drift_response"):
            if row.get(key) in (None,""):missing.append(f"{prefix}.{key}")
        if row.get("seismic_interaction_applicable") is None:missing.append(f"{prefix}.seismic_interaction_applicable")
        height=row.get("storey_height_m");response=row.get("structural_drift_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","reviewed_interface_id","relative_displacement_mm","wind_return_period_years"):
            if response.get(key) in (None,""):missing.append(f"{prefix}.structural_drift_response.{key}")
        if not model_hash:missing.append("building_geometry_sha256")
        if response.get("model_sha256")!=model_hash:errors.append(f"RAINWATER_DRIFT_{i}_MODEL_HASH_MISMATCH")
        if response.get("reviewed_interface_id")!=row.get("interface_id"):errors.append(f"RAINWATER_DRIFT_{i}_INTERFACE_ID_MISMATCH")
        if response.get("status")!="PASS":errors.append(f"RAINWATER_DRIFT_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if response.get("wind_return_period_years") not in (None,10):errors.append(f"RAINWATER_DRIFT_{i}_WRONG_WIND_RETURN_PERIOD")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{prefix}.structural_drift_response.valid_provenance")
        if height is not None and response.get("relative_displacement_mm") is not None:
            code_limit=.0025*float(height)*1000
            component_limit=row.get("component_damage_limit_mm")
            allowable=min(code_limit,float(component_limit)) if component_limit is not None else code_limit
            displacement=float(response["relative_displacement_mm"]);joint=row.get("selected_joint_allowance_mm")
            if displacement>allowable+1e-9:errors.append(f"RAINWATER_DRIFT_{i}_STRUCTURAL_DRIFT_EXCEEDS_ALLOWABLE")
            if joint is not None and float(joint)+1e-9<displacement:errors.append(f"RAINWATER_DRIFT_{i}_JOINT_ALLOWANCE_INSUFFICIENT")
            evidence.append(f"drift_interface={row.get('interface_id')} height_m={float(height):.3f} code_limit_mm={code_limit:.3f} allowable_mm={allowable:.3f} displacement_mm={displacement:.3f} joint_allowance_mm={joint}")
        if row.get("seismic_interaction_applicable") is True:
            seismic=row.get("seismic_relative_displacement_response") or {};sp=seismic.get("evidence_provenance") or {}
            for key in ("analysis_id","model_sha256","reviewed_interface_id","relative_displacement_mm","inelastic_deformation_included","p_delta_included"):
                if seismic.get(key) in (None,""):missing.append(f"{prefix}.seismic_relative_displacement_response.{key}")
            if seismic.get("model_sha256")!=model_hash:errors.append(f"RAINWATER_DRIFT_{i}_SEISMIC_MODEL_HASH_MISMATCH")
            if seismic.get("reviewed_interface_id")!=row.get("interface_id"):errors.append(f"RAINWATER_DRIFT_{i}_SEISMIC_INTERFACE_ID_MISMATCH")
            if seismic.get("status")!="PASS":errors.append(f"RAINWATER_DRIFT_{i}_SEISMIC_RESPONSE_NOT_APPROVED")
            if seismic.get("inelastic_deformation_included") is not True or seismic.get("p_delta_included") is not True:
                errors.append(f"RAINWATER_DRIFT_{i}_SEISMIC_REQUIRED_EFFECTS_MISSING")
            if sp.get("verification_status")!="VALID" or not sp.get("source_sha256"):
                missing.append(f"{prefix}.seismic_relative_displacement_response.valid_provenance")
            clearance=row.get("structural_movement_clearance_mm")
            if clearance is None:missing.append(f"{prefix}.structural_movement_clearance_mm")
            elif seismic.get("relative_displacement_mm") is not None and float(clearance)+1e-9<float(seismic["relative_displacement_mm"]):
                errors.append(f"RAINWATER_DRIFT_{i}_SEISMIC_MOVEMENT_CLEARANCE_INSUFFICIENT")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_exposed_pipe_wind_load(rule, snapshot):
    context=_context(snapshot);rows=context.get("exposed_rainwater_pipe_wind_loads")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["exposed_rainwater_pipe_wind_loads[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["exposed_rainwater_pipe_wind_loads_verified_absent"]) if context.get("exposed_rainwater_pipe_wind_loads_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["exposed_rainwater_pipe_wind_loads_verified_absent"])
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256")
    for i,row in enumerate(rows):
        prefix=f"exposed_rainwater_pipe_wind_loads[{i}]"
        for key in ("pipe_id","diameter_m","exposed_length_m","surface_roughness","q_kn_m2","ce","cg","iw","declared_force_kn"):
            if row.get(key) in (None,""):missing.append(f"{prefix}.{key}")
        try:d=float(row.get("diameter_m"));length=float(row.get("exposed_length_m"));q=float(row.get("q_kn_m2"));ce=float(row.get("ce"));cg=float(row.get("cg"));iw=float(row.get("iw"))
        except (TypeError,ValueError):continue
        if min(d,length,q,ce,cg,iw)<=0:errors.append(f"EXPOSED_PIPE_WIND_{i}_NONPOSITIVE_INPUT");continue
        if length/d<=100:errors.append(f"EXPOSED_PIPE_WIND_{i}_FIGURE_APPLICABILITY_LENGTH_DIAMETER_NOT_OVER_100")
        roughness=row.get("surface_roughness")
        threshold=d*sqrt(q*ce)
        if roughness not in {"SMOOTH","MEDIUM_ROUGH"}:errors.append(f"EXPOSED_PIPE_WIND_{i}_UNSUPPORTED_ROUGHNESS");continue
        cf=(.5 if roughness=="SMOOTH" else .7) if threshold>=.167 else 1.2
        area=d*length;force=cf*q*cg*ce*area*iw
        if abs(float(row.get("declared_force_kn") or 0)-force)>.001:errors.append(f"EXPOSED_PIPE_WIND_{i}_FORCE_MISMATCH")
        response=row.get("support_structural_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","reviewed_pipe_id","reviewed_force_kn"):
            if response.get(key) in (None,""):missing.append(f"{prefix}.support_structural_response.{key}")
        if not model_hash:missing.append("building_geometry_sha256")
        if response.get("model_sha256")!=model_hash:errors.append(f"EXPOSED_PIPE_WIND_{i}_MODEL_HASH_MISMATCH")
        if response.get("reviewed_pipe_id")!=row.get("pipe_id"):errors.append(f"EXPOSED_PIPE_WIND_{i}_SUPPORT_PIPE_ID_MISMATCH")
        if response.get("status")!="PASS":errors.append(f"EXPOSED_PIPE_WIND_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if response.get("reviewed_force_kn") is not None and abs(float(response["reviewed_force_kn"])-force)>.001:errors.append(f"EXPOSED_PIPE_WIND_{i}_REVIEWED_FORCE_MISMATCH")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{prefix}.support_structural_response.valid_provenance")
        if row.get("vortex_shedding_applicable") is not True:
            errors.append(f"EXPOSED_PIPE_WIND_{i}_VORTEX_APPLICABILITY_MUST_BE_DERIVED")
        else:
            for key in ("natural_frequency_hz","vortex_reference_width_m","strouhal_number","basic_wind_speed_m_s"):
                if row.get(key) in (None,""):missing.append(f"{prefix}.{key}")
            if all(row.get(key) not in (None,"") for key in
                   ("natural_frequency_hz","vortex_reference_width_m","strouhal_number","basic_wind_speed_m_s")):
                frequency=float(row["natural_frequency_hz"]);width=float(row["vortex_reference_width_m"])
                strouhal=float(row["strouhal_number"]);basic_speed=float(row["basic_wind_speed_m_s"])
                if min(frequency,width,strouhal,basic_speed)<=0:
                    errors.append(f"EXPOSED_PIPE_WIND_{i}_INVALID_VORTEX_INPUT")
                else:
                    critical_speed=frequency*width/strouhal
                    mean_speed=basic_speed*sqrt(ce)
                    negligible=critical_speed>1.25*mean_speed
                    if row.get("declared_vortex_critical_speed_m_s") is None:
                        missing.append(f"{prefix}.declared_vortex_critical_speed_m_s")
                    elif abs(float(row["declared_vortex_critical_speed_m_s"])-critical_speed)>1e-6:
                        errors.append(f"EXPOSED_PIPE_WIND_{i}_VORTEX_CRITICAL_SPEED_MISMATCH")
                    if row.get("declared_vortex_negligible") is not negligible:
                        errors.append(f"EXPOSED_PIPE_WIND_{i}_VORTEX_NEGLIGIBILITY_MISMATCH")
                    if not negligible:
                        dynamic=row.get("vortex_dynamic_response") or {};dp=dynamic.get("evidence_provenance") or {}
                        for key in ("analysis_id","model_sha256","reviewed_pipe_id","fatigue_checked","resonance_checked"):
                            if dynamic.get(key) in (None,""):missing.append(f"{prefix}.vortex_dynamic_response.{key}")
                        if dynamic.get("model_sha256")!=model_hash:errors.append(f"EXPOSED_PIPE_WIND_{i}_VORTEX_MODEL_HASH_MISMATCH")
                        if dynamic.get("reviewed_pipe_id")!=row.get("pipe_id"):errors.append(f"EXPOSED_PIPE_WIND_{i}_VORTEX_PIPE_ID_MISMATCH")
                        if dynamic.get("status")!="PASS" or dynamic.get("fatigue_checked") is not True or dynamic.get("resonance_checked") is not True:
                            errors.append(f"EXPOSED_PIPE_WIND_{i}_VORTEX_DYNAMIC_RESPONSE_NOT_APPROVED")
                        if dp.get("verification_status")!="VALID" or not dp.get("source_sha256"):
                            missing.append(f"{prefix}.vortex_dynamic_response.valid_provenance")
                    evidence.append(f"vortex_pipe={row.get('pipe_id')} critical_speed_m_s={critical_speed:.4f} mean_speed_m_s={mean_speed:.4f} negligible={negligible}")
        evidence.append(f"exposed_pipe={row.get('pipe_id')} l_over_d={length/d:.2f} threshold={threshold:.4f} cf={cf:.2f} area_m2={area:.4f} force_kn={force:.4f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_atmospheric_ice_on_rainwater_components(rule, snapshot):
    context = _context(snapshot)
    rows = context.get("atmospheric_ice_rainwater_components")
    if rows is None:
        return _result(rule, INPUT_REQUIRED, missing=["atmospheric_ice_rainwater_components[]"])
    if not rows:
        return (_result(rule, NOT_APPLICABLE,
                        evidence=["atmospheric_ice_rainwater_components_verified_absent"])
                if context.get("atmospheric_ice_rainwater_components_verified_absent")
                else _result(rule, INPUT_REQUIRED,
                             missing=["atmospheric_ice_rainwater_components_verified_absent"]))
    missing, errors, evidence = [], [], []
    model_hash = context.get("building_geometry_sha256")
    wind_rows = {str(row.get("pipe_id")): row for row in
                 (context.get("exposed_rainwater_pipe_wind_loads") or [])}
    nominal_by_region = {1: 0.0, 2: 0.0, 3: 0.0, 4: 7.5, 5: 12.5, 6: 15.0}
    applicable = 0
    for i, row in enumerate(rows):
        prefix = f"atmospheric_ice_rainwater_components[{i}]"
        if row.get("exposed_to_atmospheric_icing") is None:
            missing.append(f"{prefix}.exposed_to_atmospheric_icing"); continue
        if row.get("exposed_to_atmospheric_icing") is not True:
            evidence.append(f"atmospheric_ice={row.get('component_id')} exposure=false"); continue
        applicable += 1
        for key in ("component_id", "snow_region", "height_above_ground_m",
                    "importance_factor", "circumscribed_diameter_m", "exposed_length_m",
                    "water_unit_weight_kn_m3"):
            if row.get(key) in (None, ""):
                missing.append(f"{prefix}.{key}")
        if row.get("flexible_dynamic_ice_effects_required") is True:
            dynamic=row.get("dynamic_ice_response") or {};dynamic_provenance=dynamic.get("evidence_provenance") or {}
            for key in ("analysis_id","component_id","model_sha256","status","method","load_case_id","fatigue_checked","resonance_checked"):
                if dynamic.get(key) in (None,""):missing.append(f"{prefix}.dynamic_ice_response.{key}")
            if dynamic.get("component_id") not in (None,row.get("component_id")):errors.append(f"ATMOSPHERIC_ICE_{i}_DYNAMIC_RESPONSE_SCOPE_MISMATCH")
            if model_hash and dynamic.get("model_sha256") not in (None,model_hash):errors.append(f"ATMOSPHERIC_ICE_{i}_DYNAMIC_RESPONSE_MODEL_HASH_MISMATCH")
            if dynamic.get("status") not in (None,"PASS"):errors.append(f"ATMOSPHERIC_ICE_{i}_DYNAMIC_RESPONSE_NOT_APPROVED")
            if dynamic.get("fatigue_checked") is not True or dynamic.get("resonance_checked") is not True:errors.append(f"ATMOSPHERIC_ICE_{i}_DYNAMIC_RESPONSE_INCOMPLETE")
            if dynamic_provenance.get("verification_status")!="VALID" or not dynamic_provenance.get("source_sha256"):missing.append(f"{prefix}.dynamic_ice_response.valid_provenance")
        try:
            region = int(row.get("snow_region")); z = float(row.get("height_above_ground_m"))
            importance = float(row.get("importance_factor")); diameter = float(row.get("circumscribed_diameter_m"))
            length = float(row.get("exposed_length_m")); gamma_water = float(row.get("water_unit_weight_kn_m3"))
        except (TypeError, ValueError):
            continue
        if region not in nominal_by_region:
            errors.append(f"ATMOSPHERIC_ICE_{i}_SNOW_REGION_OUT_OF_RANGE"); continue
        if min(z, importance, diameter, length, gamma_water) <= 0:
            errors.append(f"ATMOSPHERIC_ICE_{i}_NONPOSITIVE_INPUT"); continue
        nominal_mm = nominal_by_region[region]
        if row.get("mountainous_extreme_precipitation") is True:
            local = row.get("official_local_nominal_ice_thickness_mm")
            provenance = row.get("official_local_ice_provenance") or {}
            if local is None:
                missing.append(f"{prefix}.official_local_nominal_ice_thickness_mm"); continue
            if provenance.get("verification_status") != "VALID" or not provenance.get("source_sha256"):
                missing.append(f"{prefix}.official_local_ice_provenance.valid_provenance"); continue
            nominal_mm = float(local)
        fz = min((z / 10.0) ** 0.1, 1.4)
        td_m = 2.0 * (nominal_mm / 1000.0) * importance * fz
        ice_area_m2 = pi * td_m * (diameter + td_m)
        ice_volume_m3 = ice_area_m2 * length
        ice_weight_kn = ice_volume_m3 * 0.9 * gamma_water
        iced_diameter_m = diameter + 2.0 * td_m
        if td_m == 0:
            evidence.append(
                f"atmospheric_ice={row.get('component_id')} region={region} nominal_mm=0.000 "
                f"fz={fz:.4f} td_m=0.00000 weight_kn=0.00000 iced_diameter_m={diameter:.5f}"
            )
            continue
        wind_pipe_id = str(row.get("wind_load_pipe_id") or '')
        if not wind_pipe_id:
            missing.append(f"{prefix}.wind_load_pipe_id")
        elif wind_pipe_id not in wind_rows:
            missing.append(f"{prefix}.matching_exposed_rainwater_pipe_wind_load")
        elif abs(float(wind_rows[wind_pipe_id].get("diameter_m") or 0) - iced_diameter_m) > .0001:
            errors.append(f"ATMOSPHERIC_ICE_{i}_ICED_DIAMETER_NOT_CONSUMED_BY_WIND_LOAD")
        response = row.get("support_structural_response") or {}
        provenance = response.get("evidence_provenance") or {}
        for key in ("analysis_id", "model_sha256", "reviewed_ice_weight_kn", "reviewed_iced_diameter_m"):
            if response.get(key) in (None, ""):
                missing.append(f"{prefix}.support_structural_response.{key}")
        if not model_hash:
            missing.append("building_geometry_sha256")
        if response.get("model_sha256") != model_hash:
            errors.append(f"ATMOSPHERIC_ICE_{i}_MODEL_HASH_MISMATCH")
        if response.get("status") != "PASS":
            errors.append(f"ATMOSPHERIC_ICE_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if response.get("reviewed_ice_weight_kn") is not None and abs(float(response["reviewed_ice_weight_kn"]) - ice_weight_kn) > .001:
            errors.append(f"ATMOSPHERIC_ICE_{i}_REVIEWED_WEIGHT_MISMATCH")
        if response.get("reviewed_iced_diameter_m") is not None and abs(float(response["reviewed_iced_diameter_m"]) - iced_diameter_m) > .0001:
            errors.append(f"ATMOSPHERIC_ICE_{i}_REVIEWED_DIAMETER_MISMATCH")
        if provenance.get("verification_status") != "VALID" or not provenance.get("source_sha256"):
            missing.append(f"{prefix}.support_structural_response.valid_provenance")
        evidence.append(
            f"atmospheric_ice={row.get('component_id')} region={region} nominal_mm={nominal_mm:.3f} "
            f"fz={fz:.4f} td_m={td_m:.5f} area_m2={ice_area_m2:.5f} "
            f"volume_m3={ice_volume_m3:.5f} weight_kn={ice_weight_kn:.5f} iced_diameter_m={iced_diameter_m:.5f}"
        )
    if not applicable and not missing:
        return _result(rule, NOT_APPLICABLE, evidence=evidence)
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _m6_roof_cladding_wind_zones(rule, snapshot):
    context=_context(snapshot);rows=context.get("roof_cladding_wind_zones")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["roof_cladding_wind_zones[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["roof_cladding_wind_zones_verified_absent"])
        if context.get("roof_cladding_wind_zones_verified_absent") else
        _result(rule,INPUT_REQUIRED,missing=["roof_cladding_wind_zones_verified_absent"]))
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256")
    canonical_rows=context.get("canonical_roof_wind_interfaces")
    if canonical_rows is None:return _result(rule,INPUT_REQUIRED,missing=["canonical_roof_wind_interfaces[]"])
    canonical_by_id={str(item.get("roof_interface_id")):item for item in canonical_rows
                     if item.get("roof_interface_id") not in (None,"")}
    for i,row in enumerate(rows):
        prefix=f"roof_cladding_wind_zones[{i}]"
        for key in ("roof_area_id","roof_interface_id","roof_form","roof_slope_degrees","smallest_plan_dimension_m",
                    "eave_height_m","declared_edge_strip_width_m","parapet_height_m","roof_polygon",
                    "declared_corner_cgcp","pressure_case_id","suction_case_id"):
            if row.get(key) in (None,""):missing.append(f"{prefix}.{key}")
        canonical=canonical_by_id.get(str(row.get("roof_interface_id")));canonical_roof=None
        if canonical is None:
            errors.append(f"ROOF_WIND_ZONE_{i}_UNKNOWN_CANONICAL_ROOF_INTERFACE")
        else:
            for key in ("roof_area_id","roof_polygon","geometry_model_sha256","source_geometry_id","source_geometry_sha256"):
                if canonical.get(key) in (None,""):missing.append(f"canonical_roof_wind_interfaces[{row.get('roof_interface_id')}].{key}")
            if canonical.get("roof_area_id")!=row.get("roof_area_id"):errors.append(f"ROOF_WIND_ZONE_{i}_CANONICAL_ROOF_AREA_ID_MISMATCH")
            if canonical.get("geometry_model_sha256")!=model_hash:errors.append(f"ROOF_WIND_ZONE_{i}_CANONICAL_MODEL_HASH_MISMATCH")
            try:
                canonical_roof=Polygon(canonical.get("roof_polygon") or []);evaluated_roof=Polygon(row.get("roof_polygon") or [])
                if not canonical_roof.is_valid or canonical_roof.area<=0 or not evaluated_roof.equals(canonical_roof):
                    errors.append(f"ROOF_WIND_ZONE_{i}_CANONICAL_ROOF_GEOMETRY_MISMATCH")
                source_roof=Polygon(_roof(snapshot).get("boundary") or [])
                if not source_roof.is_valid or source_roof.area<=0 or not canonical_roof.equals(source_roof):
                    errors.append(f"ROOF_WIND_ZONE_{i}_SOURCE_ROOF_GEOMETRY_MISMATCH")
                if canonical.get("source_geometry_sha256")!=_polygon_source_sha256(_roof(snapshot).get("boundary") or []):
                    errors.append(f"ROOF_WIND_ZONE_{i}_SOURCE_ROOF_HASH_MISMATCH")
            except Exception:errors.append(f"ROOF_WIND_ZONE_{i}_CANONICAL_ROOF_GEOMETRY_MISMATCH")
        try:
            slope=float(row.get("roof_slope_degrees"));b=float(row.get("smallest_plan_dimension_m"))
            height=float(row.get("eave_height_m"));declared=float(row.get("declared_edge_strip_width_m"))
            parapet=float(row.get("parapet_height_m"));corner=float(row.get("declared_corner_cgcp"))
        except (TypeError,ValueError):continue
        if min(b,height)<=0 or slope<0:errors.append(f"ROOF_WIND_ZONE_{i}_INVALID_GEOMETRY");continue
        wind_basis=row.get("wind_design_basis") or {};wind_provenance=wind_basis.get("evidence_provenance") or {}
        for key in ("basis_id","reviewed_roof_interface_id","reviewed_source_geometry_id","source_clause","maximum_regional_wind_speed_m_s","terrain_roughness_category","geometry_model_sha256"):
            if wind_basis.get(key) in (None,""):missing.append(f"{prefix}.wind_design_basis.{key}")
        if wind_basis.get("geometry_model_sha256")!=model_hash:errors.append(f"ROOF_WIND_ZONE_{i}_WIND_BASIS_MODEL_HASH_MISMATCH")
        if wind_basis.get("reviewed_roof_interface_id")!=row.get("roof_interface_id"):errors.append(f"ROOF_WIND_ZONE_{i}_WIND_BASIS_INTERFACE_ID_MISMATCH")
        if canonical and wind_basis.get("reviewed_source_geometry_id")!=canonical.get("source_geometry_id"):errors.append(f"ROOF_WIND_ZONE_{i}_WIND_BASIS_SOURCE_GEOMETRY_MISMATCH")
        if wind_basis.get("source_clause")!="M6-115":errors.append(f"ROOF_WIND_ZONE_{i}_WIND_BASIS_SOURCE_CLAUSE_INVALID")
        if wind_provenance.get("verification_status")!="VALID" or not wind_provenance.get("source_sha256"):
            missing.append(f"{prefix}.wind_design_basis.valid_provenance")
        edge=max(min(.10*b,.40*height),.04*b,1.0)
        if abs(declared-edge)>1e-6:errors.append(f"ROOF_WIND_ZONE_{i}_EDGE_STRIP_WIDTH_MISMATCH")
        form=row.get("roof_form")
        supported=((slope<7 and form=="LOW_SLOPE") or (slope>7 and form in {"GABLE","HIP"}) or
                   (10<slope<30 and form=="SAWTOOTH") or (3<=slope<=30 and form=="MONOSLOPE"))
        if not supported:errors.append(f"ROOF_WIND_ZONE_{i}_FORM_SLOPE_FIGURE_MISMATCH")
        expected_corner=-4.4 if parapet>=1 else -5.4
        if form=="LOW_SLOPE" and abs(corner-expected_corner)>1e-6:
            errors.append(f"ROOF_WIND_ZONE_{i}_CORNER_COEFFICIENT_MISMATCH")
        if form in {"GABLE","HIP"} and row.get("edge_zone_applied_to_ridge_and_hips") is not True:
            errors.append(f"ROOF_WIND_ZONE_{i}_RIDGE_HIP_EDGE_ZONE_MISSING")
        response=row.get("cladding_structural_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","reviewed_roof_interface_id","reviewed_source_geometry_id","reviewed_component_ids","pressure_case_id","suction_case_id"):
            if response.get(key) in (None,""):missing.append(f"{prefix}.cladding_structural_response.{key}")
        if not model_hash:missing.append("building_geometry_sha256")
        if response.get("model_sha256")!=model_hash:errors.append(f"ROOF_WIND_ZONE_{i}_MODEL_HASH_MISMATCH")
        if response.get("reviewed_roof_interface_id")!=row.get("roof_interface_id"):errors.append(f"ROOF_WIND_ZONE_{i}_STRUCTURAL_INTERFACE_ID_MISMATCH")
        if canonical and response.get("reviewed_source_geometry_id")!=canonical.get("source_geometry_id"):errors.append(f"ROOF_WIND_ZONE_{i}_STRUCTURAL_SOURCE_GEOMETRY_MISMATCH")
        if response.get("pressure_case_id")!=row.get("pressure_case_id") or response.get("suction_case_id")!=row.get("suction_case_id"):
            errors.append(f"ROOF_WIND_ZONE_{i}_PRESSURE_SUCTION_CASE_MISMATCH")
        if response.get("status")!="PASS":errors.append(f"ROOF_WIND_ZONE_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):
            missing.append(f"{prefix}.cladding_structural_response.valid_provenance")
        zones=row.get("wind_zone_polygons");attachments=row.get("rainwater_component_attachments")
        if zones is None:missing.append(f"{prefix}.wind_zone_polygons[]")
        if attachments is None:missing.append(f"{prefix}.rainwater_component_attachments[]")
        zone_shapes={}
        for j,zone in enumerate(zones or []):
            if zone.get("zone_id") in (None,"") or zone.get("cgcp") is None or len(zone.get("polygon") or [])<3:
                missing.append(f"{prefix}.wind_zone_polygons[{j}].zone_id_cgcp_polygon");continue
            shape=Polygon(zone["polygon"])
            if not shape.is_valid or shape.area<=0:errors.append(f"ROOF_WIND_ZONE_{i}_ZONE_{j}_INVALID_POLYGON");continue
            if canonical_roof is not None and not canonical_roof.covers(shape):errors.append(f"ROOF_WIND_ZONE_{i}_ZONE_{j}_OUTSIDE_CANONICAL_ROOF");continue
            zone_shapes[str(zone["zone_id"])]=(shape,float(zone["cgcp"]))
        for j,attachment in enumerate(attachments or []):
            ap=f"{prefix}.rainwater_component_attachments[{j}]"
            for key in ("component_id","roof_interface_id","component_wind_scope","footprint_polygon","selected_zone_id",
                        "effective_projected_area_m2","projected_profile_polygon","projected_area_direction","coefficient_basis",
                        "component_height_above_ground_m","ce_reference_height_m",
                        "q_kn_m2","ce","cg","iw","declared_support_force_kn"):
                if attachment.get(key) in (None,""):missing.append(f"{ap}.{key}")
            if attachment.get("roof_interface_id")!=row.get("roof_interface_id"):
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_INTERFACE_ID_MISMATCH")
            if attachment.get("component_wind_scope") not in {None,"ROOF_CLADDING_ATTACHMENT","ROOF_MOUNTED_RAINWATER_ATTACHMENT_WITH_VERIFIED_COEFFICIENT"}:
                missing.append(f"{ap}.supported_component_specific_wind_method");continue
            coefficient_basis=attachment.get("coefficient_basis") or {}
            if (not isinstance(coefficient_basis,dict) or
                    coefficient_basis.get("source_clause") not in {"M6-119","M6-120","M6-119/M6-120","M6-122/figure-zone EDGE-S"} or
                    coefficient_basis.get("verification_status")!="VALID"):
                missing.append(f"{ap}.coefficient_basis.valid_source_clause")
            if attachment.get("component_height_above_ground_m") is not None and attachment.get("ce_reference_height_m") is not None and abs(float(attachment["component_height_above_ground_m"])-float(attachment["ce_reference_height_m"]))>1e-6:
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_HEIGHT_REFERENCE_MISMATCH")
            footprint=Polygon(attachment.get("footprint_polygon") or []) if len(attachment.get("footprint_polygon") or [])>=3 else None
            if footprint is None:continue
            if not footprint.is_valid or footprint.area<=0:errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_INVALID_FOOTPRINT");continue
            if canonical_roof is not None and not canonical_roof.covers(footprint):
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_OUTSIDE_CANONICAL_ROOF")
            selected=zone_shapes.get(str(attachment.get("selected_zone_id")))
            if selected is None:errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_UNKNOWN_SELECTED_ZONE");continue
            intersecting=[zone_id for zone_id,(shape,_) in zone_shapes.items() if shape.intersection(footprint).area>1e-9]
            if str(attachment.get("selected_zone_id")) not in intersecting:
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_FOOTPRINT_OUTSIDE_SELECTED_ZONE");continue
            try:
                q=float(attachment["q_kn_m2"]);ce=float(attachment["ce"]);cg=float(attachment["cg"]);iw=float(attachment["iw"])
                effective_area=float(attachment["effective_projected_area_m2"])
            except (KeyError,TypeError,ValueError):continue
            if effective_area<=0:errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_NONPOSITIVE_EFFECTIVE_PROJECTED_AREA");continue
            try:projected_profile=Polygon(attachment.get("projected_profile_polygon") or [])
            except Exception:projected_profile=None
            if projected_profile is None or not projected_profile.is_valid or projected_profile.area<=0:
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_INVALID_PROJECTED_PROFILE")
            elif abs(projected_profile.area-effective_area)>1e-6:
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_PROJECTED_AREA_GEOMETRY_MISMATCH")
            if len(intersecting)>1:
                segments=attachment.get("segmented_effective_areas_by_zone")
                if not isinstance(segments,dict):
                    missing.append(f"{ap}.segmented_effective_areas_by_zone");continue
                try:segment_areas={str(k):float(v) for k,v in segments.items()}
                except (TypeError,ValueError):
                    missing.append(f"{ap}.segmented_effective_areas_by_zone.numeric_values");continue
                if set(segment_areas)!=set(intersecting) or abs(sum(segment_areas.values())-effective_area)>1e-6:
                    errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_SEGMENTED_EFFECTIVE_AREA_MISMATCH");continue
                coefficient_area=sum(abs(zone_shapes[zone_id][1])*area for zone_id,area in segment_areas.items())
            else:
                coefficient_area=abs(selected[1])*effective_area
            force=coefficient_area*q*ce*cg*iw
            if abs(float(attachment.get("declared_support_force_kn") or 0)-force)>.001:
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_SUPPORT_FORCE_MISMATCH")
            reviewed=(response.get("reviewed_attachment_forces_kn") or {}).get(str(attachment.get("component_id")))
            if reviewed is None:missing.append(f"{prefix}.cladding_structural_response.reviewed_attachment_forces_kn.{attachment.get('component_id')}")
            elif abs(float(reviewed)-force)>.001:errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_REVIEWED_FORCE_MISMATCH")
            if str(attachment.get("component_id")) not in {str(value) for value in response.get("reviewed_component_ids") or []}:
                errors.append(f"ROOF_WIND_ZONE_{i}_ATTACHMENT_{j}_STRUCTURAL_COMPONENT_ID_MISMATCH")
            evidence.append(f"roof_wind_attachment={attachment.get('component_id')} zone={attachment.get('selected_zone_id')} footprint_area_m2={footprint.area:.4f} effective_projected_area_m2={effective_area:.4f} direction={attachment.get('projected_area_direction')} force_kn={force:.4f}")
        evidence.append(f"roof_wind_zone={row.get('roof_area_id')} form={form} slope_deg={slope:.3f} edge_width_m={edge:.3f} parapet_m={parapet:.3f} corner_cgcp={corner:.3f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_attachment_net_wind_pressure(rule, snapshot):
    c=_context(snapshot);rows=c.get("rainwater_attachment_net_wind_pressures")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_attachment_net_wind_pressures[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["rainwater_attachment_net_wind_pressures_verified_absent"])
        if c.get("rainwater_attachment_net_wind_pressures_verified_absent") else
        _result(rule,INPUT_REQUIRED,missing=["rainwater_attachment_net_wind_pressures_verified_absent"]))
    missing=[];errors=[];evidence=[];model_hash=c.get("building_geometry_sha256")
    canonical_rows=c.get("canonical_roof_wind_interfaces")
    if canonical_rows is None:return _result(rule,INPUT_REQUIRED,missing=["canonical_roof_wind_interfaces[]"])
    canonical_by_id={str(item.get("roof_interface_id")):item for item in canonical_rows
                     if item.get("roof_interface_id") not in (None,"")}
    for i,row in enumerate(rows):
        p=f"rainwater_attachment_net_wind_pressures[{i}]"
        for key in ("component_id","method","iw","q_kn_m2","ce","ct","cg","cp","cd",
                    "internal_pressure_kn_m2","effective_projected_area_m2",
                    "component_wind_scope","pressure_sign_convention","roof_interface_id",
                    "attachment_footprint_polygon","selected_wind_zone_polygon","projected_profile_polygon","wind_zone_response",
                    "declared_external_pressure_kn_m2","declared_net_pressure_kn_m2","declared_net_force_kn"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        if row.get("component_wind_scope") not in {None,"ROOF_CLADDING_ATTACHMENT"}:
            missing.append(f"{p}.supported_free_component_wind_method");continue
        if row.get("pressure_sign_convention") not in {None,"POSITIVE_TOWARD_SURFACE_NEGATIVE_SUCTION"}:
            errors.append(f"NET_WIND_{i}_INVALID_PRESSURE_SIGN_CONVENTION")
        canonical=canonical_by_id.get(str(row.get("roof_interface_id")));canonical_roof=None
        if canonical is None:errors.append(f"NET_WIND_{i}_UNKNOWN_CANONICAL_ROOF_INTERFACE")
        else:
            for key in ("roof_polygon","geometry_model_sha256","source_geometry_id","source_geometry_sha256"):
                if canonical.get(key) in (None,""):missing.append(f"canonical_roof_wind_interfaces[{row.get('roof_interface_id')}].{key}")
            if canonical.get("geometry_model_sha256")!=model_hash:errors.append(f"NET_WIND_{i}_CANONICAL_MODEL_HASH_MISMATCH")
            try:
                canonical_roof=Polygon(canonical.get("roof_polygon") or [])
                if not canonical_roof.is_valid or canonical_roof.area<=0:errors.append(f"NET_WIND_{i}_INVALID_CANONICAL_ROOF_GEOMETRY")
                source_roof=Polygon(_roof(snapshot).get("boundary") or [])
                if not source_roof.is_valid or source_roof.area<=0 or not canonical_roof.equals(source_roof):errors.append(f"NET_WIND_{i}_SOURCE_ROOF_GEOMETRY_MISMATCH")
                if canonical.get("source_geometry_sha256")!=_polygon_source_sha256(_roof(snapshot).get("boundary") or []):errors.append(f"NET_WIND_{i}_SOURCE_ROOF_HASH_MISMATCH")
            except Exception:errors.append(f"NET_WIND_{i}_INVALID_CANONICAL_ROOF_GEOMETRY")
        try:
            footprint=Polygon(row.get("attachment_footprint_polygon") or [])
            zone_polygon=Polygon(row.get("selected_wind_zone_polygon") or [])
            projected_profile=Polygon(row.get("projected_profile_polygon") or [])
        except Exception:footprint=zone_polygon=projected_profile=None
        if footprint is None or zone_polygon is None or projected_profile is None or not all(
                shape.is_valid and shape.area>0 for shape in (footprint,zone_polygon,projected_profile)):
            errors.append(f"NET_WIND_{i}_INVALID_TYPED_GEOMETRY")
        elif not zone_polygon.covers(footprint):
            errors.append(f"NET_WIND_{i}_ATTACHMENT_OUTSIDE_SELECTED_ZONE")
        elif canonical_roof is not None and (not canonical_roof.covers(zone_polygon) or not canonical_roof.covers(footprint)):
            errors.append(f"NET_WIND_{i}_GEOMETRY_OUTSIDE_CANONICAL_ROOF")
        wind_zone_response=row.get("wind_zone_response") or {};wzp=wind_zone_response.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","reviewed_roof_interface_id","reviewed_source_geometry_id","reviewed_component_id","source_clause"):
            if wind_zone_response.get(key) in (None,""):missing.append(f"{p}.wind_zone_response.{key}")
        if wind_zone_response.get("model_sha256")!=model_hash:errors.append(f"NET_WIND_{i}_ZONE_MODEL_HASH_MISMATCH")
        if wind_zone_response.get("reviewed_roof_interface_id")!=row.get("roof_interface_id"):errors.append(f"NET_WIND_{i}_ZONE_INTERFACE_ID_MISMATCH")
        if canonical and wind_zone_response.get("reviewed_source_geometry_id")!=canonical.get("source_geometry_id"):errors.append(f"NET_WIND_{i}_ZONE_SOURCE_GEOMETRY_MISMATCH")
        if wind_zone_response.get("reviewed_component_id")!=row.get("component_id"):errors.append(f"NET_WIND_{i}_ZONE_COMPONENT_ID_MISMATCH")
        if wind_zone_response.get("source_clause") not in {"M6-119","M6-120","M6-119/M6-120"}:errors.append(f"NET_WIND_{i}_ZONE_SOURCE_CLAUSE_INVALID")
        if wzp.get("verification_status")!="VALID" or not wzp.get("source_sha256"):missing.append(f"{p}.wind_zone_response.valid_provenance")
        try:
            iw,q,ce,ct,cg,cp,cd=(float(row[k]) for k in ("iw","q_kn_m2","ce","ct","cg","cp","cd"))
            internal=float(row["internal_pressure_kn_m2"]);area=float(row["effective_projected_area_m2"])
        except (KeyError,TypeError,ValueError):continue
        if area<=0:errors.append(f"NET_WIND_{i}_NONPOSITIVE_EFFECTIVE_AREA");continue
        if projected_profile is not None and projected_profile.is_valid and abs(projected_profile.area-area)>1e-6:
            errors.append(f"NET_WIND_{i}_PROJECTED_AREA_GEOMETRY_MISMATCH")
        external=iw*q*ce*ct*cg*cp*cd
        net=external+internal;force=abs(net)*area
        if abs(float(row.get("declared_external_pressure_kn_m2") or 0)-external)>1e-6:errors.append(f"NET_WIND_{i}_EXTERNAL_PRESSURE_FORMULA_MISMATCH")
        if abs(float(row.get("declared_net_pressure_kn_m2") or 0)-net)>1e-6:errors.append(f"NET_WIND_{i}_ALGEBRAIC_NET_PRESSURE_MISMATCH")
        if abs(float(row.get("declared_net_force_kn") or 0)-force)>1e-6:errors.append(f"NET_WIND_{i}_NET_FORCE_MISMATCH")
        if row.get("method")=="SIMPLIFIED_CSTAR_CORNER":
            if row.get("corner_zone_intersection_verified") is not True:
                missing.append(f"{p}.corner_zone_intersection_verified=true")
            expected=-2.0 if float(row.get("parapet_height_m") or 0)>1 else -2.3
            if abs(cp-expected)>1e-6:errors.append(f"NET_WIND_{i}_CSTAR_CORNER_COEFFICIENT_MISMATCH")
        elif row.get("method")!="DETAILED_EXTERNAL_INTERNAL":errors.append(f"NET_WIND_{i}_UNSUPPORTED_METHOD")
        response=row.get("support_structural_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","reviewed_roof_interface_id","reviewed_component_id","reviewed_net_force_kn"):
            if response.get(key) in (None,""):missing.append(f"{p}.support_structural_response.{key}")
        if response.get("model_sha256")!=model_hash:errors.append(f"NET_WIND_{i}_MODEL_HASH_MISMATCH")
        if response.get("reviewed_roof_interface_id")!=row.get("roof_interface_id"):errors.append(f"NET_WIND_{i}_STRUCTURAL_INTERFACE_ID_MISMATCH")
        if response.get("reviewed_component_id")!=row.get("component_id"):errors.append(f"NET_WIND_{i}_STRUCTURAL_COMPONENT_ID_MISMATCH")
        if response.get("status")!="PASS":errors.append(f"NET_WIND_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if response.get("reviewed_net_force_kn") is not None and abs(float(response["reviewed_net_force_kn"])-force)>1e-6:errors.append(f"NET_WIND_{i}_REVIEWED_FORCE_MISMATCH")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{p}.support_structural_response.valid_provenance")
        evidence.append(f"net_wind={row.get('component_id')} method={row.get('method')} external_kpa={external:.4f} internal_kpa={internal:.4f} net_kpa={net:.4f} area_m2={area:.4f} force_kn={force:.4f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_storage_tank_wind_load(rule, snapshot):
    context = _context(snapshot)
    rows = context.get("rainwater_storage_tank_wind_loads")
    if rows is None:
        return _result(rule, INPUT_REQUIRED, missing=["rainwater_storage_tank_wind_loads[]"])
    if not rows:
        return (_result(rule, NOT_APPLICABLE, evidence=["rainwater_storage_tank_wind_loads_verified_absent"])
                if context.get("rainwater_storage_tank_wind_loads_verified_absent") is True
                else _result(rule, INPUT_REQUIRED,
                             missing=["rainwater_storage_tank_wind_loads_verified_absent"]))
    model_hash = context.get("building_geometry_sha256")
    missing, errors, evidence = [], [], []
    for i, row in enumerate(rows):
        prefix = f"rainwater_storage_tank_wind_loads[{i}]"
        for key in ("tank_id", "tank_shape", "diameter_m", "iw", "q_kn_m2", "ce", "cg",
                    "cf", "cp", "cpi", "declared_projected_area_m2", "declared_force_kn",
                    "declared_external_pressure_kn_m2", "declared_internal_pressure_kn_m2",
                    "declared_net_pressure_kn_m2"):
            if row.get(key) in (None, ""):
                missing.append(f"{prefix}.{key}")
        try:
            diameter = float(row["diameter_m"])
            iw, q, ce, cg = (float(row[key]) for key in ("iw", "q_kn_m2", "ce", "cg"))
            cf, cp, cpi = (float(row[key]) for key in ("cf", "cp", "cpi"))
        except (KeyError, TypeError, ValueError):
            continue
        if diameter <= 0 or min(iw, q, ce, cg) <= 0:
            errors.append(f"RAINWATER_TANK_WIND_{i}_INVALID_GEOMETRY_OR_WIND_BASIS")
            continue
        shape = row.get("tank_shape")
        if shape == "SPHERICAL":
            area = pi * diameter ** 2 / 4.0
            if row.get("surface_roughness") != "LOW":
                errors.append(f"RAINWATER_TANK_WIND_{i}_SPHERE_REQUIRES_LOW_ROUGHNESS")
            if diameter * sqrt(q * ce) <= 0.8:
                errors.append(f"RAINWATER_TANK_WIND_{i}_SPHERE_DSQRTQCE_OUTSIDE_FIGURE_SCOPE")
            if abs(cf - 0.2) > 1e-9:
                errors.append(f"RAINWATER_TANK_WIND_{i}_SPHERE_CF_MISMATCH")
        elif shape == "CYLINDRICAL":
            if row.get("height_m") in (None, ""):
                missing.append(f"{prefix}.height_m")
                continue
            height = float(row["height_m"])
            if height <= 0:
                errors.append(f"RAINWATER_TANK_WIND_{i}_INVALID_CYLINDER_HEIGHT")
                continue
            area = diameter * height
            coefficient_basis = row.get("figure_coefficient_basis") or {}
            if (coefficient_basis.get("source_clause") in (None, "") or
                    coefficient_basis.get("verification_status") != "VALID" or
                    coefficient_basis.get("cf") != row.get("cf") or
                    coefficient_basis.get("cp") != row.get("cp") or
                    coefficient_basis.get("cpi") != row.get("cpi")):
                missing.append(f"{prefix}.figure_coefficient_basis.valid_matching_coefficients")
        else:
            errors.append(f"RAINWATER_TANK_WIND_{i}_UNSUPPORTED_TANK_SHAPE")
            continue
        force = iw * cf * q * cg * ce * area
        external = cp * q * cg * ce
        internal = cpi * q * cg * ce
        net = internal - external
        if abs(float(row.get("declared_projected_area_m2") or 0) - area) > 1e-6:
            errors.append(f"RAINWATER_TANK_WIND_{i}_PROJECTED_AREA_MISMATCH")
        if abs(float(row.get("declared_force_kn") or 0) - force) > 1e-6:
            errors.append(f"RAINWATER_TANK_WIND_{i}_FORCE_MISMATCH")
        if abs(float(row.get("declared_external_pressure_kn_m2") or 0) - external) > 1e-6:
            errors.append(f"RAINWATER_TANK_WIND_{i}_EXTERNAL_PRESSURE_MISMATCH")
        if abs(float(row.get("declared_internal_pressure_kn_m2") or 0) - internal) > 1e-6:
            errors.append(f"RAINWATER_TANK_WIND_{i}_INTERNAL_PRESSURE_MISMATCH")
        if abs(float(row.get("declared_net_pressure_kn_m2") or 0) - net) > 1e-6:
            errors.append(f"RAINWATER_TANK_WIND_{i}_NET_PRESSURE_MISMATCH")
        response = row.get("support_structural_response") or {}
        provenance = response.get("evidence_provenance") or {}
        for key in ("analysis_id", "model_sha256", "reviewed_force_kn", "reviewed_net_pressure_kn_m2"):
            if response.get(key) in (None, ""):
                missing.append(f"{prefix}.support_structural_response.{key}")
        if not model_hash:
            missing.append("building_geometry_sha256")
        if response.get("model_sha256") != model_hash:
            errors.append(f"RAINWATER_TANK_WIND_{i}_MODEL_HASH_MISMATCH")
        if response.get("status") != "PASS":
            errors.append(f"RAINWATER_TANK_WIND_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if response.get("reviewed_force_kn") is not None and abs(float(response["reviewed_force_kn"]) - force) > 1e-6:
            errors.append(f"RAINWATER_TANK_WIND_{i}_REVIEWED_FORCE_MISMATCH")
        if (response.get("reviewed_net_pressure_kn_m2") is not None and
                abs(float(response["reviewed_net_pressure_kn_m2"]) - net) > 1e-6):
            errors.append(f"RAINWATER_TANK_WIND_{i}_REVIEWED_NET_PRESSURE_MISMATCH")
        if provenance.get("verification_status") != "VALID" or not provenance.get("source_sha256"):
            missing.append(f"{prefix}.support_structural_response.valid_provenance")
        evidence.append(
            f"rainwater_tank_wind={row.get('tank_id')} shape={shape} area_m2={area:.5f} "
            f"force_kn={force:.5f} external_kpa={external:.5f} internal_kpa={internal:.5f} "
            f"net_kpa={net:.5f}"
        )
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _m6_rainwater_support_member_wind_load(rule, snapshot):
    context=_context(snapshot);rows=context.get("rainwater_support_member_wind_loads")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_support_member_wind_loads[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["rainwater_support_member_wind_loads_verified_absent"])
        if context.get("rainwater_support_member_wind_loads_verified_absent") else
        _result(rule,INPUT_REQUIRED,missing=["rainwater_support_member_wind_loads_verified_absent"]))
    missing=[];errors=[];evidence=[];model_hash=context.get("building_geometry_sha256")
    k_table={5:.60,10:.65,20:.75,35:.85,50:.90,100:.95,float("inf"):1.0}
    for i,row in enumerate(rows):
        p=f"rainwater_support_member_wind_loads[{i}]"
        for key in ("member_id","member_scope","cross_section_shape","wind_angle_degrees","length_m","windward_width_m","q_kn_m2","ce","cg","iw","k","cn_infinity","ct_infinity","declared_fn_kn","declared_ft_kn"):
            if row.get(key) in (None,""):missing.append(f"{p}.{key}")
        if row.get("member_scope") not in (None,"RAINWATER_SINGLE_OR_COMBINED_STRUCTURAL_SUPPORT"):
            missing.append(f"{p}.supported_figure_A6_4_9_member_scope")
        try:
            length,width,q,ce,cg,iw,k,cn,ct=(float(row[x]) for x in ("length_m","windward_width_m","q_kn_m2","ce","cg","iw","k","cn_infinity","ct_infinity"))
        except (KeyError,TypeError,ValueError):continue
        if min(length,width,q,ce,cg,iw)<=0:errors.append(f"SUPPORT_MEMBER_WIND_{i}_NONPOSITIVE_INPUT");continue
        ratio=length/width;basis=row.get("figure_coefficient_basis") or {}
        if (basis.get("verification_status")!="VALID" or not basis.get("source_sha256") or
                basis.get("source_clause") in (None,"") or basis.get("cross_section_shape")!=row.get("cross_section_shape") or
                basis.get("wind_angle_degrees")!=row.get("wind_angle_degrees") or
                basis.get("cn_infinity")!=row.get("cn_infinity") or basis.get("ct_infinity")!=row.get("ct_infinity")):
            missing.append(f"{p}.figure_coefficient_basis.valid_matching_coefficients")
        expected_k=k_table.get(ratio)
        if expected_k is None:
            if basis.get("verified_k_for_l_over_h")!=row.get("k") or basis.get("l_over_h")!=ratio:
                missing.append(f"{p}.figure_coefficient_basis.verified_k_for_actual_l_over_h")
        elif abs(k-expected_k)>1e-9:errors.append(f"SUPPORT_MEMBER_WIND_{i}_K_TABLE_MISMATCH")
        area=width*length;fn=k*cn*q*cg*ce*area*iw;ft=k*ct*q*cg*ce*area*iw
        if abs(float(row.get("declared_fn_kn") or 0)-fn)>1e-6:errors.append(f"SUPPORT_MEMBER_WIND_{i}_FN_MISMATCH")
        if abs(float(row.get("declared_ft_kn") or 0)-ft)>1e-6:errors.append(f"SUPPORT_MEMBER_WIND_{i}_FT_MISMATCH")
        response=row.get("structural_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","reviewed_fn_kn","reviewed_ft_kn"):
            if response.get(key) in (None,""):missing.append(f"{p}.structural_response.{key}")
        if response.get("model_sha256")!=model_hash:errors.append(f"SUPPORT_MEMBER_WIND_{i}_MODEL_HASH_MISMATCH")
        if response.get("status")!="PASS":errors.append(f"SUPPORT_MEMBER_WIND_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if response.get("reviewed_fn_kn") is not None and abs(float(response["reviewed_fn_kn"])-fn)>1e-6:errors.append(f"SUPPORT_MEMBER_WIND_{i}_REVIEWED_FN_MISMATCH")
        if response.get("reviewed_ft_kn") is not None and abs(float(response["reviewed_ft_kn"])-ft)>1e-6:errors.append(f"SUPPORT_MEMBER_WIND_{i}_REVIEWED_FT_MISMATCH")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{p}.structural_response.valid_provenance")
        evidence.append(f"support_member_wind={row.get('member_id')} shape={row.get('cross_section_shape')} angle_deg={row.get('wind_angle_degrees')} l_over_h={ratio:.3f} area_m2={area:.4f} fn_kn={fn:.4f} ft_kn={ft:.4f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_site_flood_structural_interface(rule, snapshot):
    c=_context(snapshot);rows=c.get("rainwater_site_flood_structural_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_site_flood_structural_interfaces[]"])
    if not rows:return (_result(rule,NOT_APPLICABLE,evidence=["rainwater_site_flood_structural_interfaces_verified_absent"])
        if c.get("rainwater_site_flood_structural_interfaces_verified_absent") else
        _result(rule,INPUT_REQUIRED,missing=["rainwater_site_flood_structural_interfaces_verified_absent"]))
    missing=[];errors=[];evidence=[];model_hash=c.get("building_geometry_sha256")
    for i,row in enumerate(rows):
        p=f"rainwater_site_flood_structural_interfaces[{i}]"
        for key in ("asset_id","asset_footprint_polygon","flood_hazard_polygon","hazard_type","project_stage"):
            if row.get(key) in (None,"",[]):missing.append(f"{p}.{key}")
        try:asset=Polygon(row.get("asset_footprint_polygon") or []);hazard=Polygon(row.get("flood_hazard_polygon") or [])
        except Exception:asset=hazard=None
        if asset is None or hazard is None or not asset.is_valid or not hazard.is_valid or asset.area<=0 or hazard.area<=0:
            errors.append(f"SITE_FLOOD_{i}_INVALID_POLYGON");continue
        overlap=asset.intersection(hazard).area
        declared=row.get("declared_intersection_area_m2")
        if declared is None:missing.append(f"{p}.declared_intersection_area_m2")
        elif abs(float(declared)-overlap)>1e-6:errors.append(f"SITE_FLOOD_{i}_INTERSECTION_AREA_MISMATCH")
        if overlap<=1e-9:
            evidence.append(f"site_flood_asset={row.get('asset_id')} overlap_m2=0 not_applicable=true");continue
        response=row.get("flood_structural_response") or {};prov=response.get("evidence_provenance") or {}
        for key in ("analysis_id","model_sha256","reviewed_asset_id","reviewed_hazard_type"):
            if response.get(key) in (None,""):missing.append(f"{p}.flood_structural_response.{key}")
        if response.get("model_sha256")!=model_hash:errors.append(f"SITE_FLOOD_{i}_MODEL_HASH_MISMATCH")
        if response.get("reviewed_asset_id")!=row.get("asset_id") or response.get("reviewed_hazard_type")!=row.get("hazard_type"):
            errors.append(f"SITE_FLOOD_{i}_RESPONSE_SCOPE_MISMATCH")
        if response.get("status")!="PASS":errors.append(f"SITE_FLOOD_{i}_RESPONSE_NOT_APPROVED")
        if prov.get("verification_status")!="VALID" or not prov.get("source_sha256"):missing.append(f"{p}.flood_structural_response.valid_provenance")
        evidence.append(f"site_flood_asset={row.get('asset_id')} hazard={row.get('hazard_type')} overlap_m2={overlap:.4f} analysis={response.get('analysis_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m6_rainwater_canopy_wind_load(rule,snapshot):
    c=_context(snapshot);rows=c.get("rainwater_canopy_wind_loads")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_canopy_wind_loads[]"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["rainwater_canopy_wind_loads_verified_absent"]) if c.get("rainwater_canopy_wind_loads_verified_absent") else _result(rule,INPUT_REQUIRED,missing=["rainwater_canopy_wind_loads_verified_absent"])
    missing=[];errors=[];evidence=[];mh=c.get("building_geometry_sha256")
    for i,r in enumerate(rows):
        p=f"rainwater_canopy_wind_loads[{i}]"
        for k in ("canopy_id","canopy_type","canopy_projection_polygon","roof_area_m2","blockage_phi","iw","q_kn_m2","ce","ct","cg","cf","cd","cp_net","slope_angle_degrees","declared_force_kn","declared_pressure_kn_m2"):
            if r.get(k) in (None,""):missing.append(f"{p}.{k}")
        try:area,phi,iw,q,ce,ct,cg,cf,cd,cp=(float(r[k]) for k in ("roof_area_m2","blockage_phi","iw","q_kn_m2","ce","ct","cg","cf","cd","cp_net"))
        except (KeyError,TypeError,ValueError):continue
        try:projection=Polygon(r.get("canopy_projection_polygon") or [])
        except Exception:projection=None
        if projection is None or not projection.is_valid or projection.area<=0:
            errors.append(f"CANOPY_WIND_{i}_INVALID_PROJECTION_POLYGON");continue
        if abs(area-projection.area)>1e-6:errors.append(f"CANOPY_WIND_{i}_PROJECTED_AREA_MISMATCH")
        blockage=r.get("blockage_projection_response") or {};bp=blockage.get("evidence_provenance") or {}
        for key in ("wind_direction_id","projection_plane","geometry_model_sha256","source_figure_id","source_printed_page","obstruction_projected_area_m2","reference_under_canopy_projected_area_m2"):
            if blockage.get(key) in (None,""):missing.append(f"{p}.blockage_projection_response.{key}")
        if blockage.get("geometry_model_sha256")!=mh:errors.append(f"CANOPY_WIND_{i}_BLOCKAGE_MODEL_HASH_MISMATCH")
        expected_blockage_figure="M6_A6_4_14" if r.get("canopy_type")=="MONOSLOPE" else "M6_A6_4_15" if r.get("canopy_type")=="DUAL_SLOPE" else None
        expected_blockage_page=152 if r.get("canopy_type")=="MONOSLOPE" else 153 if r.get("canopy_type")=="DUAL_SLOPE" else None
        if blockage.get("source_figure_id")!=expected_blockage_figure or blockage.get("source_printed_page")!=expected_blockage_page or blockage.get("projection_plane")!="VERTICAL_NORMAL_TO_WIND":
            missing.append(f"{p}.blockage_projection_response.verified_source_figure_and_page")
        if bp.get("verification_status")!="VALID" or not bp.get("source_sha256"):
            missing.append(f"{p}.blockage_projection_response.valid_provenance")
        if blockage.get("obstruction_projected_area_m2") is not None and blockage.get("reference_under_canopy_projected_area_m2") is not None:
            obstruction=float(blockage["obstruction_projected_area_m2"]);reference=float(blockage["reference_under_canopy_projected_area_m2"])
            if reference<=0 or obstruction<0 or obstruction>reference:errors.append(f"CANOPY_WIND_{i}_INVALID_DIRECTIONAL_BLOCKAGE_AREAS")
            else:
                calculated_phi=obstruction/reference
                if abs(phi-calculated_phi)>1e-6:errors.append(f"CANOPY_WIND_{i}_BLOCKAGE_PROJECTION_MISMATCH")
        if area<=0 or not 0<=phi<=1:errors.append(f"CANOPY_WIND_{i}_INVALID_GEOMETRY_OR_BLOCKAGE");continue
        typ=r.get("canopy_type");cases=set(r.get("evaluated_cases") or [])
        required={"I","II"} if typ=="MONOSLOPE" else {"I_BOTH_WINGS","II_BOTH_WINGS","I_ONE_WING","II_ONE_WING"} if typ=="DUAL_SLOPE" else set()
        if not required:errors.append(f"CANOPY_WIND_{i}_UNSUPPORTED_TYPE")
        elif not required.issubset(cases):errors.append(f"CANOPY_WIND_{i}_REQUIRED_CASES_MISSING")
        basis=r.get("figure_coefficient_basis") or {}
        expected_figure="M6_A6_4_14" if typ=="MONOSLOPE" else "M6_A6_4_15" if typ=="DUAL_SLOPE" else None
        if (basis.get("verification_status")!="VALID" or not basis.get("source_sha256") or basis.get("canopy_type")!=typ or
                basis.get("blockage_phi")!=r.get("blockage_phi") or basis.get("figure_id")!=expected_figure or
                basis.get("printed_page")!=(152 if typ=="MONOSLOPE" else 153) or
                basis.get("coefficient_semantics")!="FIGURE_CF_AND_CPNET_WITH_GENERAL_FACTORS_SEPARATE" or
                basis.get("cf")!=r.get("cf") or basis.get("cp_net")!=r.get("cp_net") or
                set(basis.get("evaluated_cases") or [])!=cases or basis.get("slope_angle_degrees")!=r.get("slope_angle_degrees")):
            missing.append(f"{p}.figure_coefficient_basis.valid_matching_geometry")
        case_coefficients=basis.get("case_coefficients") or {}
        if set(case_coefficients)!=required:missing.append(f"{p}.figure_coefficient_basis.complete_case_coefficients")
        case_results={}
        for case in required:
            values=case_coefficients.get(case) or {}
            if values.get("cf") is None or values.get("cp_net") is None:
                missing.append(f"{p}.figure_coefficient_basis.case_coefficients.{case}");continue
            case_results[case]={"force":iw*q*ce*ct*cg*float(values["cf"])*cd*area,
                                "pressure":iw*q*ce*ct*cg*float(values["cp_net"])*cd}
        governing=r.get("governing_case")
        if governing not in case_results:missing.append(f"{p}.governing_case")
        elif case_results:
            expected_governing=max(sorted(case_results),key=lambda case:max(abs(case_results[case]["force"]),abs(case_results[case]["pressure"])))
            if governing!=expected_governing:errors.append(f"CANOPY_WIND_{i}_GOVERNING_CASE_MISMATCH")
            if abs(cf-float(case_coefficients[governing]["cf"]))>1e-9 or abs(cp-float(case_coefficients[governing]["cp_net"]))>1e-9:errors.append(f"CANOPY_WIND_{i}_GOVERNING_COEFFICIENT_MISMATCH")
        force=iw*q*ce*ct*cg*cf*cd*area;pressure=iw*q*ce*ct*cg*cp*cd
        if abs(float(r.get("declared_force_kn") or 0)-force)>1e-6:errors.append(f"CANOPY_WIND_{i}_FORCE_MISMATCH")
        if abs(float(r.get("declared_pressure_kn_m2") or 0)-pressure)>1e-6:errors.append(f"CANOPY_WIND_{i}_PRESSURE_MISMATCH")
        resp=r.get("structural_response") or {};prov=resp.get("evidence_provenance") or {}
        for k in ("analysis_id","model_sha256","reviewed_force_kn","reviewed_pressure_kn_m2"):
            if resp.get(k) in (None,""):missing.append(f"{p}.structural_response.{k}")
        if resp.get("model_sha256")!=mh:errors.append(f"CANOPY_WIND_{i}_MODEL_HASH_MISMATCH")
        if resp.get("status")!="PASS":errors.append(f"CANOPY_WIND_{i}_STRUCTURAL_RESPONSE_NOT_APPROVED")
        if resp.get("reviewed_force_kn") is not None and abs(float(resp["reviewed_force_kn"])-force)>1e-6:errors.append(f"CANOPY_WIND_{i}_REVIEWED_FORCE_MISMATCH")
        if resp.get("reviewed_pressure_kn_m2") is not None and abs(float(resp["reviewed_pressure_kn_m2"])-pressure)>1e-6:errors.append(f"CANOPY_WIND_{i}_REVIEWED_PRESSURE_MISMATCH")
        if prov.get("verification_status")!="VALID" or not prov.get("source_sha256"):missing.append(f"{p}.structural_response.valid_provenance")
        evidence.append(f"canopy_wind={r.get('canopy_id')} type={typ} phi={phi:.3f} area_m2={area:.3f} force_kn={force:.4f} pressure_kpa={pressure:.4f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_outdoor_rainwater_equipment_installation(rule, snapshot):
    context = _context(snapshot)
    rows = context.get("outdoor_rainwater_equipment_installations")
    if rows is None:
        return _result(rule, INPUT_REQUIRED, missing=["outdoor_rainwater_equipment_installations[]"])
    if not rows:
        return (_result(rule, NOT_APPLICABLE, evidence=["outdoor_rainwater_equipment_verified_absent"])
                if context.get("outdoor_rainwater_equipment_verified_absent")
                else _result(rule, INPUT_REQUIRED, missing=["outdoor_rainwater_equipment_verified_absent"]))
    model_hash = context.get("building_geometry_sha256")
    missing, errors, evidence = [], [], []
    valid_spaces = {"ROOF", "TERRACE", "BALCONY", "SEMI_OPEN"}
    for i, row in enumerate(rows):
        prefix = f"outdoor_rainwater_equipment_installations[{i}]"
        for key in ("equipment_id", "space_type", "equipment_footprint", "open_space_polygon",
                    "attachment_points", "architecture_response", "anchorage_response"):
            if row.get(key) in (None, "", []): missing.append(f"{prefix}.{key}")
        if row.get("space_type") not in valid_spaces:
            errors.append(f"OUTDOOR_EQUIPMENT_{i}_INVALID_SPACE_TYPE")
        try:
            footprint = Polygon(row.get("equipment_footprint") or [])
            open_space = Polygon(row.get("open_space_polygon") or [])
        except Exception:
            footprint = open_space = None
        if footprint is None or footprint.is_empty or not footprint.is_valid or footprint.area <= 0:
            errors.append(f"OUTDOOR_EQUIPMENT_{i}_INVALID_FOOTPRINT")
        if open_space is None or open_space.is_empty or not open_space.is_valid or open_space.area <= 0:
            errors.append(f"OUTDOOR_EQUIPMENT_{i}_INVALID_OPEN_SPACE_POLYGON")
        if footprint is not None and open_space is not None and footprint.is_valid and open_space.is_valid:
            if not open_space.covers(footprint):
                errors.append(f"OUTDOOR_EQUIPMENT_{i}_OUTSIDE_DECLARED_OPEN_SPACE")
            for j, point in enumerate(row.get("attachment_points") or []):
                if len(point) < 2 or not footprint.covers(Point(float(point[0]), float(point[1]))):
                    errors.append(f"OUTDOOR_EQUIPMENT_{i}_ATTACHMENT_{j}_OUTSIDE_FOOTPRINT")
        for response_name in ("architecture_response", "anchorage_response"):
            response = row.get(response_name) or {}
            provenance = response.get("evidence_provenance") or {}
            for key in ("analysis_id", "model_sha256", "reviewed_equipment_id"):
                if response.get(key) in (None, ""): missing.append(f"{prefix}.{response_name}.{key}")
            if not model_hash: missing.append("building_geometry_sha256")
            if response.get("model_sha256") != model_hash:
                errors.append(f"OUTDOOR_EQUIPMENT_{i}_{response_name.upper()}_MODEL_HASH_MISMATCH")
            if response.get("reviewed_equipment_id") != row.get("equipment_id"):
                errors.append(f"OUTDOOR_EQUIPMENT_{i}_{response_name.upper()}_EQUIPMENT_MISMATCH")
            if response.get("status") != "PASS":
                errors.append(f"OUTDOOR_EQUIPMENT_{i}_{response_name.upper()}_NOT_APPROVED")
            if provenance.get("verification_status") != "VALID" or not provenance.get("source_sha256"):
                missing.append(f"{prefix}.{response_name}.valid_provenance")
        evidence.append(
            f"outdoor_equipment={row.get('equipment_id')} space={row.get('space_type')} "
            f"footprint_area_m2={(footprint.area if footprint is not None and footprint.is_valid else 0):.3f} "
            f"attachments={len(row.get('attachment_points') or [])}"
        )
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _m4_heavy_equipment_removal_route(rule, snapshot):
    context = _context(snapshot)
    rows = context.get("rainwater_heavy_equipment_removal_routes")
    if rows is None:
        return _result(rule, INPUT_REQUIRED, missing=["rainwater_heavy_equipment_removal_routes[]"])
    if not rows:
        return (_result(rule, NOT_APPLICABLE, evidence=["rainwater_heavy_equipment_verified_absent"])
                if context.get("rainwater_heavy_equipment_verified_absent")
                else _result(rule, INPUT_REQUIRED, missing=["rainwater_heavy_equipment_verified_absent"]))
    missing, errors, evidence = [], [], []
    tolerance = float(rule["parameters"]["geometry_tolerance_m"])
    for i, row in enumerate(rows):
        prefix = f"rainwater_heavy_equipment_removal_routes[{i}]"
        for key in ("equipment_id", "equipment_footprint", "equipment_width_m", "equipment_height_m",
                    "transport_envelope_model", "equipment_orientation_locked",
                    "selected_path", "exit_polygon", "clearance_corridor_polygon", "clearance_segments"):
            if row.get(key) in (None, "", []): missing.append(f"{prefix}.{key}")
        if row.get("obstruction_inventory_complete") is not True:
            missing.append(f"{prefix}.obstruction_inventory_complete")
        try:
            footprint = Polygon(row.get("equipment_footprint") or [])
            path = LineString(row.get("selected_path") or [])
            exit_polygon = Polygon(row.get("exit_polygon") or [])
            corridor = Polygon(row.get("clearance_corridor_polygon") or [])
        except Exception:
            footprint = exit_polygon = corridor = path = None
        if footprint is None or footprint.is_empty or not footprint.is_valid or footprint.area <= 0:
            errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_INVALID_EQUIPMENT_FOOTPRINT")
        if path is None or path.is_empty or not path.is_valid or path.length <= 0:
            errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_INVALID_SELECTED_PATH")
        if exit_polygon is None or exit_polygon.is_empty or not exit_polygon.is_valid or exit_polygon.area <= 0:
            errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_INVALID_EXIT_POLYGON")
        if corridor is None or corridor.is_empty or not corridor.is_valid or corridor.area <= 0:
            errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_INVALID_CLEARANCE_CORRIDOR")
        if footprint is not None and path is not None and footprint.is_valid and path.is_valid:
            if not footprint.buffer(tolerance).covers(Point(path.coords[0])):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_PATH_NOT_CONNECTED_TO_EQUIPMENT")
        if exit_polygon is not None and path is not None and exit_polygon.is_valid and path.is_valid:
            if not exit_polygon.buffer(tolerance).covers(Point(path.coords[-1])):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_PATH_NOT_CONNECTED_TO_EXIT")
        width, height = row.get("equipment_width_m"), row.get("equipment_height_m")
        if width is not None and float(width) <= 0: errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_NONPOSITIVE_EQUIPMENT_WIDTH")
        if height is not None and float(height) <= 0: errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_NONPOSITIVE_EQUIPMENT_HEIGHT")
        swept = None
        transport_model = row.get("transport_envelope_model")
        if transport_model != "TRANSLATING_CAPSULE_NO_ROTATION":
            missing.append(f"{prefix}.supported_transport_envelope_model")
        if row.get("equipment_orientation_locked") is not True:
            missing.append(f"{prefix}.equipment_orientation_locked_true")
        if path is not None and path.is_valid and len(path.coords) > 2:
            directions=[]
            for start,end in zip(path.coords,path.coords[1:]):
                dx,dy=float(end[0])-float(start[0]),float(end[1])-float(start[1])
                length=(dx*dx+dy*dy)**.5
                if length>tolerance:directions.append((dx/length,dy/length))
            if any(abs(a[0]*b[1]-a[1]*b[0])>1e-8 for a,b in zip(directions,directions[1:])):
                missing.append(f"{prefix}.rectangular_turning_sweep_analysis")
        if path is not None and path.is_valid and width is not None and float(width) > 0 and footprint is not None and footprint.is_valid:
            origin=path.coords[0]
            translated=[translate(footprint,xoff=float(point[0])-float(origin[0]),yoff=float(point[1])-float(origin[1])) for point in path.coords]
            swept=unary_union([shape for pair in zip(translated,translated[1:]) for shape in (pair[0],pair[1],unary_union(pair).convex_hull)])
            if corridor is not None and corridor.is_valid and not corridor.buffer(tolerance).covers(swept):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_SWEPT_ENVELOPE_OUTSIDE_CORRIDOR")
            for j, polygon in enumerate(row.get("obstruction_polygons") or []):
                try:
                    obstruction = Polygon(polygon)
                except Exception:
                    obstruction = None
                if obstruction is None or obstruction.is_empty or not obstruction.is_valid:
                    errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_INVALID_OBSTRUCTION_{j}")
                elif swept.intersects(obstruction):
                    errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_SWEPT_ENVELOPE_INTERSECTS_OBSTRUCTION_{j}")
        covered_until = 0.0
        segments = sorted(row.get("clearance_segments") or [], key=lambda item: float(item.get("start_distance_m", 0)))
        for j, segment in enumerate(segments):
            for key in ("start_distance_m", "end_distance_m", "clear_width_m", "clear_height_m"):
                if segment.get(key) in (None, ""): missing.append(f"{prefix}.clearance_segments[{j}].{key}")
            if any(segment.get(key) in (None, "") for key in ("start_distance_m", "end_distance_m")):
                continue
            start, end = float(segment["start_distance_m"]), float(segment["end_distance_m"])
            if start > covered_until + tolerance:
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_CLEARANCE_SEGMENT_GAP_BEFORE_{j}")
            if end <= start or start < -tolerance or (path is not None and path.is_valid and end > path.length + tolerance):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_INVALID_CLEARANCE_SEGMENT_{j}")
            covered_until = max(covered_until, end)
            if width is not None and segment.get("clear_width_m") is not None and float(segment["clear_width_m"]) + tolerance < float(width):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_SEGMENT_{j}_WIDTH_INSUFFICIENT")
            if height is not None and segment.get("clear_height_m") is not None and float(segment["clear_height_m"]) + tolerance < float(height):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_SEGMENT_{j}_HEIGHT_INSUFFICIENT")
        if path is not None and path.is_valid and covered_until + tolerance < path.length:
            errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_CLEARANCE_SEGMENTS_DO_NOT_COVER_PATH")
        for j, sample in enumerate(row.get("clearance_samples") or []):
            for key in ("point", "clear_width_m", "clear_height_m"):
                if sample.get(key) in (None, "", []): missing.append(f"{prefix}.clearance_samples[{j}].{key}")
            point = sample.get("point") or []
            if path is not None and path.is_valid and len(point) >= 2:
                if path.distance(Point(float(point[0]), float(point[1]))) > tolerance:
                    errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_SAMPLE_{j}_NOT_ON_PATH")
            if width is not None and sample.get("clear_width_m") is not None and float(sample["clear_width_m"]) + tolerance < float(width):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_SAMPLE_{j}_WIDTH_INSUFFICIENT")
            if height is not None and sample.get("clear_height_m") is not None and float(sample["clear_height_m"]) + tolerance < float(height):
                errors.append(f"HEAVY_EQUIPMENT_ROUTE_{i}_SAMPLE_{j}_HEIGHT_INSUFFICIENT")
        if path is not None and path.is_valid:
            evidence.append(f"heavy_equipment={row.get('equipment_id')} removal_path_m={path.length:.3f} equipment_width_m={width} equipment_height_m={height} transport_model={transport_model} swept_area_m2={(swept.area if swept is not None else 0):.3f} clearance_segments={len(segments)} samples={len(row.get('clearance_samples') or [])}")
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _m4_rainwater_pollution_prevention_interface(rule, snapshot):
    context=_context(snapshot);rows=context.get("rainwater_pollution_prevention_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_pollution_prevention_interfaces[]"])
    if not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["no_actual_waste_or_sewage_interface"])
                if context.get("rainwater_pollution_prevention_interfaces_verified_absent") is True
                else _result(rule,INPUT_REQUIRED,missing=["rainwater_pollution_prevention_interfaces_verified_absent"]))
    model_hash=context.get("building_geometry_sha256")
    if not model_hash:return _result(rule,INPUT_REQUIRED,missing=["building_geometry_sha256"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"rainwater_pollution_prevention_interfaces[{i}]";route_points=row.get("rainwater_route_points") or [];sources=row.get("waste_or_sewage_source_polygons")
        for key in ("interface_id","rainwater_route_points","waste_or_sewage_source_polygons"):
            if row.get(key) in (None,"",[]):missing.append(f"{p}.{key}")
        if len(route_points)<2 or not sources:continue
        try: route=LineString(route_points);polygons=[Polygon(value) for value in sources]
        except Exception:errors.append(f"POLLUTION_{i}_INVALID_GEOMETRY");continue
        if not route.is_valid or any(not shape.is_valid or shape.is_empty for shape in polygons):errors.append(f"POLLUTION_{i}_INVALID_GEOMETRY");continue
        response=row.get("environmental_health_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("response_id","model_sha256","status","minimum_separation_m"):
            if response.get(key) in (None,""):missing.append(f"{p}.environmental_health_response.{key}")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{p}.environmental_health_response.valid_provenance")
        if response.get("model_sha256") not in (None,model_hash):errors.append(f"POLLUTION_{i}_MODEL_HASH_MISMATCH")
        if response.get("status") not in (None,"APPROVED"):errors.append(f"POLLUTION_{i}_OWNER_RESPONSE_NOT_APPROVED")
        if response.get("minimum_separation_m") is not None:
            minimum=float(response["minimum_separation_m"]);actual=min(route.distance(shape) for shape in polygons)
            if minimum<0:errors.append(f"POLLUTION_{i}_NEGATIVE_MINIMUM_SEPARATION")
            elif actual+1e-7<minimum:errors.append(f"POLLUTION_{i}_SEPARATION_BELOW_OWNER_REQUIREMENT")
            evidence.append(f"pollution_interface={row.get('interface_id')} separation_m={actual:.3f} required_m={minimum:.3f}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


def _m4_rainwater_site_projection_interface(rule, snapshot):
    context=_context(snapshot);rows=context.get("rainwater_site_projection_interfaces")
    if rows is None:return _result(rule,INPUT_REQUIRED,missing=["rainwater_site_projection_interfaces[]"])
    if not rows:
        return (_result(rule,NOT_APPLICABLE,evidence=["no_actual_rainwater_site_projection_interface"])
                if context.get("rainwater_site_projection_interfaces_verified_absent") is True
                else _result(rule,INPUT_REQUIRED,missing=["rainwater_site_projection_interfaces_verified_absent"]))
    model_hash=context.get("building_geometry_sha256")
    if not model_hash:return _result(rule,INPUT_REQUIRED,missing=["building_geometry_sha256"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        p=f"rainwater_site_projection_interfaces[{i}]"
        if row.get("interface_kind")=="BURIED_COMPONENT_PROPERTY_BOUNDARY":
            for key in ("interface_id","component_polygon","property_polygon"):
                if row.get(key) in (None,"",[]):missing.append(f"{p}.{key}")
            if row.get("public_way_polygons") is None:missing.append(f"{p}.public_way_polygons")
            if row.get("public_way_inventory_complete") is not True:missing.append(f"{p}.public_way_inventory_complete")
            try:
                component=Polygon(row.get("component_polygon") or []);property_shape=Polygon(row.get("property_polygon") or [])
                public_ways=[Polygon(value) for value in row.get("public_way_polygons") or []]
            except Exception:errors.append(f"SITE_PROJECTION_{i}_INVALID_BURIED_PROPERTY_GEOMETRY");continue
            if not component.is_valid or component.is_empty or not property_shape.is_valid or property_shape.is_empty or any(not shape.is_valid for shape in public_ways):
                errors.append(f"SITE_PROJECTION_{i}_INVALID_BURIED_PROPERTY_GEOMETRY")
            elif not property_shape.covers(component):errors.append(f"SITE_PROJECTION_{i}_BURIED_COMPONENT_OUTSIDE_PROPERTY")
            if any(component.intersection(shape).area>1e-9 for shape in public_ways):errors.append(f"SITE_PROJECTION_{i}_BURIED_COMPONENT_IN_PUBLIC_WAY")
            response=row.get("urban_structural_authority_response") or {};provenance=response.get("evidence_provenance") or {}
            for key in ("response_id","model_sha256","status","interface_id"):
                if response.get(key) in (None,""):missing.append(f"{p}.urban_structural_authority_response.{key}")
            if response.get("model_sha256") not in (None,model_hash):errors.append(f"SITE_PROJECTION_{i}_OWNER_MODEL_HASH_MISMATCH")
            if response.get("interface_id") not in (None,row.get("interface_id")):errors.append(f"SITE_PROJECTION_{i}_OWNER_INTERFACE_MISMATCH")
            if response.get("status") not in (None,"APPROVED"):errors.append(f"SITE_PROJECTION_{i}_OWNER_RESPONSE_NOT_APPROVED")
            if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{p}.urban_structural_authority_response.valid_provenance")
            evidence.append(f"buried_property_interface={row.get('interface_id')} component_area_m2={component.area:.3f}")
            continue
        for key in ("interface_id","projection_polygon","building_footprint_polygon","adjacency_type","underside_elevation_m","reference_ground_elevation_m"):
            if row.get(key) in (None,"",[]):missing.append(f"{p}.{key}")
        for key in ("light_vent_patio_polygons","power_line_corridor_polygons"):
            if row.get(key) is None:missing.append(f"{p}.{key}")
        if row.get("light_vent_patio_inventory_complete") is not True:missing.append(f"{p}.light_vent_patio_inventory_complete")
        if row.get("power_line_corridor_inventory_complete") is not True:missing.append(f"{p}.power_line_corridor_inventory_complete")
        try:
            projection=Polygon(row.get("projection_polygon") or []);building=Polygon(row.get("building_footprint_polygon") or [])
            patios=[Polygon(value) for value in row.get("light_vent_patio_polygons") or []];power=[Polygon(value) for value in row.get("power_line_corridor_polygons") or []]
        except Exception:errors.append(f"SITE_PROJECTION_{i}_INVALID_GEOMETRY");continue
        if not projection.is_valid or projection.is_empty or not building.is_valid or building.is_empty or any(not shape.is_valid for shape in patios+power):errors.append(f"SITE_PROJECTION_{i}_INVALID_GEOMETRY");continue
        outside=projection.difference(building)
        if outside.is_empty or projection.boundary.intersection(building.boundary).length<=1e-9:
            errors.append(f"SITE_PROJECTION_{i}_NOT_BOUND_TO_BUILDING_LIMIT");depth=0.0
        else:
            exterior_points=[]
            geometries=list(outside.geoms) if hasattr(outside,"geoms") else [outside]
            for geometry in geometries:
                exterior_points.extend(list(geometry.exterior.coords))
            depth=max(Point(point).distance(building.boundary) for point in exterior_points)
        clearance=float(row["underside_elevation_m"])-float(row["reference_ground_elevation_m"]);adjacency=row.get("adjacency_type")
        if depth>0.8000001:errors.append(f"SITE_PROJECTION_{i}_DEPTH_EXCEEDS_0_80_M")
        if adjacency=="PUBLIC_WAY":
            if clearance+1e-7<3.5:errors.append(f"SITE_PROJECTION_{i}_PUBLIC_WAY_CLEARANCE_BELOW_3_50_M")
            for key in ("public_way_type","public_way_width_m","carriageway_edge_line","public_way_polygon"):
                if row.get(key) in (None,"",[]):missing.append(f"{p}.{key}")
            if row.get("public_way_polygon"):
                try:public_way=Polygon(row["public_way_polygon"])
                except Exception:errors.append(f"SITE_PROJECTION_{i}_INVALID_PUBLIC_WAY_POLYGON");public_way=None
                if public_way is not None and (not public_way.is_valid or not public_way.covers(outside)):errors.append(f"SITE_PROJECTION_{i}_OUTSIDE_DECLARED_PUBLIC_WAY")
            if row.get("carriageway_edge_line"):
                try:edge_distance=outside.distance(LineString(row["carriageway_edge_line"]))
                except Exception:errors.append(f"SITE_PROJECTION_{i}_INVALID_CARRIAGEWAY_EDGE");edge_distance=None
                if edge_distance is not None and edge_distance+1e-7<.8:errors.append(f"SITE_PROJECTION_{i}_CARRIAGEWAY_DISTANCE_BELOW_0_80_M")
            prohibited=row.get("public_way_type")=="HIGHWAY" or (row.get("public_way_width_m") is not None and float(row["public_way_width_m"])<12)
            exception=row.get("approved_urban_exception") or {}
            if prohibited and not exception:errors.append(f"SITE_PROJECTION_{i}_PROHIBITED_WAY_WITHOUT_APPROVED_EXCEPTION")
            elif prohibited:
                for key in ("approval_id","authority","status","source_sha256","model_sha256","interface_id"):
                    if exception.get(key) in (None,""):missing.append(f"{p}.approved_urban_exception.{key}")
                if exception.get("status")!="APPROVED" or exception.get("model_sha256")!=model_hash or exception.get("interface_id")!=row.get("interface_id"):errors.append(f"SITE_PROJECTION_{i}_INVALID_URBAN_EXCEPTION")
        elif adjacency=="ADJACENT_PROPERTY":
            if clearance+1e-7<2.7:errors.append(f"SITE_PROJECTION_{i}_PROPERTY_CLEARANCE_BELOW_2_70_M")
            boundary=row.get("adjacent_property_boundary_line")
            if not boundary:missing.append(f"{p}.adjacent_property_boundary_line")
            else:
                try:boundary_distance=outside.distance(LineString(boundary))
                except Exception:errors.append(f"SITE_PROJECTION_{i}_INVALID_PROPERTY_BOUNDARY");boundary_distance=None
                if boundary_distance is not None and boundary_distance+1e-7<.8:errors.append(f"SITE_PROJECTION_{i}_PROPERTY_DISTANCE_BELOW_0_80_M")
        else:errors.append(f"SITE_PROJECTION_{i}_UNSUPPORTED_ADJACENCY_TYPE")
        if any(projection.intersection(shape).area>1e-9 for shape in patios):errors.append(f"SITE_PROJECTION_{i}_OCCUPIES_LIGHT_VENT_PATIO")
        if any(projection.intersection(shape).area>1e-9 for shape in power):errors.append(f"SITE_PROJECTION_{i}_OCCUPIES_POWER_LINE_CORRIDOR")
        response=row.get("urban_structural_authority_response") or {};provenance=response.get("evidence_provenance") or {}
        for key in ("response_id","model_sha256","status","interface_id"):
            if response.get(key) in (None,""):missing.append(f"{p}.urban_structural_authority_response.{key}")
        if response.get("model_sha256") not in (None,model_hash):errors.append(f"SITE_PROJECTION_{i}_OWNER_MODEL_HASH_MISMATCH")
        if response.get("interface_id") not in (None,row.get("interface_id")):errors.append(f"SITE_PROJECTION_{i}_OWNER_INTERFACE_MISMATCH")
        if response.get("status") not in (None,"APPROVED"):errors.append(f"SITE_PROJECTION_{i}_OWNER_RESPONSE_NOT_APPROVED")
        if provenance.get("verification_status")!="VALID" or not provenance.get("source_sha256"):missing.append(f"{p}.urban_structural_authority_response.valid_provenance")
        evidence.append(f"site_projection={row.get('interface_id')} depth_m={depth:.3f} clearance_m={clearance:.3f} adjacency={adjacency}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)


VALIDATORS={
    "flat_roof_surface_slope":_flat_roof_surface_slope,
    "main_roof_min_two_drains_stacks":_main_roof_min_two,
    "rainwater_sanitary_separation":_system_separation,
    "emergency_shaft_provision":_emergency_shaft,
    "secondary_route_discharge_separation":_secondary,
    "official_rainfall_basis":_rainfall,
    "emergency_path_blockage_case":_emergency_blockage,
    "drain_strainer_watertight":_drain_detail,
    "horizontal_pipe_slope":_horizontal_slope,
    "stack_dn_and_use":_stack,
    "no_downstream_diameter_reduction":_no_reduction,
    "appendix7_capacity_method":_appendix,
    "external_structural_dependency":_structural,
    "plan_calc_riser_schedule_identity":_identity,
    "full_column_pressure":_full_column_pressure,
    "forbidden_joints":_forbidden_joints,
    "cleanout_locations_spacing_size":_cleanouts,
    "environmental_fire_protection":_environmental_protection,
    "pipe_supports":_supports,
    "upper_roof_discharge":_upper_roof_discharge,
    "full_head_leak_test":_leak_test,
    "material_certificate_marking":_material_certificate_marking,
    "appendix7_effective_area_multilevel":_appendix7_effective_area,
    "appendix7_complete_sizing":_appendix7_complete_sizing,
    "trench_burial":_trench_burial,
    "architectural_waterproofing_interface":_architectural_waterproofing_interface,
    "basement_entry_runoff_protection":_basement_entry_runoff_protection,
    "shaft_access_private_route":_shaft_access_private_route,
    "suspended_ceiling_clearance_separation":_suspended_ceiling_clearance_separation,
    "pitched_roof_property_safety":_pitched_roof_property_safety,
    "exterior_space_drainage":_exterior_space_drainage,
    "parking_surface_runoff":_parking_surface_runoff,
    "installation_protection_penetrations":_installation_protection_penetrations,
    "nonpotable_separation_backflow":_nonpotable_separation_backflow,
    "documentation_and_stage_closeout":_documentation_and_stage_closeout,
    "roof_equipment_overflow":_roof_equipment_overflow,
    "remaining_material_route_support":_remaining_material_route_support,
    "adjacent_system_conditional_protection":_adjacent_system_conditional_protection,
    "owner_module_compliance_dependency":_owner_module_compliance_dependency,
    "roof_access_parapet_geometry":_roof_access_parapet_geometry,
    "entrance_landing_threshold":_entrance_landing_threshold,
    "rain_on_snow_load_case":_rain_on_snow_load_case,
    "roof_service_live_loads":_roof_service_live_loads,
    "material_standard_joint_detail":_material_standard_joint_detail,
    "material_support_installation_detail":_material_support_installation_detail,
    "potable_outlet_air_gap":_potable_outlet_air_gap,
    "lrfd_rainwater_load_combinations":_lrfd_rainwater_load_combinations,
    "asd_rainwater_load_combinations":_asd_rainwater_load_combinations,
    "primary_blockage_rain_load_and_ponding":_primary_blockage_rain_load_and_ponding,
    "roof_snow_load_basis":_roof_snow_load_basis,
    "rooftop_snow_drift_geometry":_rooftop_snow_drift_geometry,
    "fluid_load_combination_extensions":_fluid_load_combination_extensions,
    "heavy_rooftop_equipment_structural_placement":_heavy_rooftop_equipment_structural_placement,
    "roof_live_load_reduction":_roof_live_load_reduction,
    "special_use_roof_live_load_reduction":_special_use_roof_live_load_reduction,
    "m6_rainwater_equipment_vibration_isolation":_m6_rainwater_equipment_vibration_isolation,
    "m6_buried_rainwater_geotechnical_structural_interface":_m6_buried_rainwater_geotechnical_structural_interface,
    "m6_rainwater_construction_stage_load":_m6_rainwater_construction_stage_load,
    "m6_rainwater_machinery_impact_load":_m6_rainwater_machinery_impact_load,
    "m6_rainwater_serviceability_movement_interface":_m6_rainwater_serviceability_movement_interface,
    "m6_rainwater_flood_ice_load_combination_extensions":_m6_rainwater_flood_ice_load_combination_extensions,
    "m4_occupied_space_rainwater_clearance":_m4_occupied_space_rainwater_clearance,
    "m4_rainwater_egress_width_obstruction":_m4_rainwater_egress_width_obstruction,
    "m6_buried_h_load_combination_extensions":_m6_buried_h_load_combination_extensions,
    "m4_visible_rainwater_facade_coordination":_m4_visible_rainwater_facade_coordination,
    "m4_main_entrance_runoff_elevation_interface":_m4_main_entrance_runoff_elevation_interface,
    "m4_pedestrian_ramp_runoff_interface":_m4_pedestrian_ramp_runoff_interface,
    "roof_serviceability_deflection":_roof_serviceability_deflection,
    "m4_rainwater_maintenance_access_geometry":_m4_rainwater_maintenance_access_geometry,
    "m4_parking_ramp_slope_geometry":_m4_parking_ramp_slope_geometry,
    "m4_parking_service_clearance_geometry":_m4_parking_service_clearance_geometry,
    "m4_patio_natural_ventilation_dependency":_m4_patio_natural_ventilation_dependency,
    "m4_exterior_intermediary_finish_durability":_m4_exterior_intermediary_finish_durability,
    "m4_external_light_air_conduit_exclusive_use":_m4_external_light_air_conduit_exclusive_use,
    "m4_parking_ramp_nonslip_surface":_m4_parking_ramp_nonslip_surface,
    "m4_light_air_conduit_traffic_guard_dependency":_m4_light_air_conduit_traffic_guard_dependency,
    "m4_light_air_conduit_semi_open_finish_dependency":_m4_light_air_conduit_semi_open_finish_dependency,
    "m4_under_open_space_parking_dependency":_m4_under_open_space_parking_dependency,
    "m4_basement_parking_light_ventilation_dependency":_m4_basement_parking_light_ventilation_dependency,
    "m4_transparent_roof_cleaning_safety":_m4_transparent_roof_cleaning_safety,
    "m4_emergency_access_rainwater_interface":_m4_emergency_access_rainwater_interface,
    "m4_rainwater_acoustic_interface":_m4_rainwater_acoustic_interface,
    "m4_stage_documents_materials_site_protection":_m4_stage_documents_materials_site_protection,
    "m6_pipe_storage_construction_load":_m6_pipe_storage_construction_load,
    "m6_rain_exposed_wood_density_load":_m6_rain_exposed_wood_density_load,
    "m6_roof_material_volumetric_dead_load":_m6_roof_material_volumetric_dead_load,
    "m6_roof_covering_surface_dead_load":_m6_roof_covering_surface_dead_load,
    "m6_vertical_rainwater_drift_compatibility":_m6_vertical_rainwater_drift_compatibility,
    "m6_exposed_pipe_wind_load":_m6_exposed_pipe_wind_load,
    "m6_atmospheric_ice_on_rainwater_components":_m6_atmospheric_ice_on_rainwater_components,
    "m6_roof_cladding_wind_zones":_m6_roof_cladding_wind_zones,
    "m6_rainwater_attachment_net_wind_pressure":_m6_rainwater_attachment_net_wind_pressure,
    "m6_rainwater_storage_tank_wind_load":_m6_rainwater_storage_tank_wind_load,
    "m6_rainwater_support_member_wind_load":_m6_rainwater_support_member_wind_load,
    "m6_rainwater_site_flood_structural_interface":_m6_rainwater_site_flood_structural_interface,
    "m6_rainwater_canopy_wind_load":_m6_rainwater_canopy_wind_load,
    "m4_outdoor_rainwater_equipment_installation":_m4_outdoor_rainwater_equipment_installation,
    "m4_heavy_equipment_removal_route":_m4_heavy_equipment_removal_route,
    "m4_rainwater_pollution_prevention_interface":_m4_rainwater_pollution_prevention_interface,
    "m4_rainwater_site_projection_interface":_m4_rainwater_site_projection_interface,
    "discharge_boundary_destination":_discharge_boundary_destination,
    "permanent_rainwater_dead_load":_permanent_rainwater_dead_load,
}


def evaluate_rainwater_rules(snapshot, *, llm_suggestions=None):
    integrity=validate_rulebook_module()
    if integrity["status"]!="PASS":
        return {"status":"FAIL","release_allowed":False,"errors":integrity["errors"],"evaluations":[]}
    working=deepcopy(snapshot or {})
    nonfinite=_nonfinite_numeric_paths(working)
    if nonfinite:
        return {"schema":"planha-rainwater-rule-evaluation/1.0",
                "module_id":integrity["module_id"],"module_version":integrity["module_version"],
                "dependency_identity":integrity["dependency_identity"],"status":"FAIL",
                "release_allowed":False,"counts":{"FAIL":1},
                "unresolved_source_controls":integrity["unresolved_control_count"],
                "errors":[f"NONFINITE_NUMERIC_INPUT:{path}" for path in nonfinite],
                "evaluations":[],"llm_suggestions_ignored":bool(llm_suggestions),
                "external_evidence_required":[]}
    results=[]
    for rule in rule_rows():
        validator=VALIDATORS.get(rule["validator"])
        if validator is None:
            results.append(_result(rule, INPUT_REQUIRED, missing=[f"validator:{rule['validator']}"],
                                   message_fa="کنترل اجرایی این قاعده هنوز تکمیل نشده است."))
        else:
            results.append(validator(rule, working))
    counts=Counter(row["status"] for row in results)
    unresolved=integrity["unresolved_control_count"]
    status=FAIL if counts[FAIL] else (INPUT_REQUIRED if counts[INPUT_REQUIRED] or unresolved else PASS)
    return {
        "schema":"planha-rainwater-rule-evaluation/1.0",
        "module_id":integrity["module_id"],"module_version":integrity["module_version"],
        "dependency_identity":integrity["dependency_identity"],
        "status":status,"release_allowed":False,
        "counts":dict(counts),"unresolved_source_controls":unresolved,
        "llm_suggestions_ignored":bool(llm_suggestions),
        "evaluations":results,
        "external_evidence_required":[
            "official one-hour rainfall and return period","structural rain-load R and ponding review",
            "approved product/material data","physical watertightness test","permit and responsible-engineer approval"],
    }
