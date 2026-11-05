"""Deterministic M4/M6/M16 rainwater applicability and validation engine."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from shapely.geometry import LineString, Point, Polygon

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
        for key in ("component_id","empty_component_mass_kg","water_full_mass_kg","support_reaction_id","structural_review"):
            if row.get(key) in (None,""):missing.append(f"structural_rainwater_loads[{i}].{key}")
        empty=row.get("empty_component_mass_kg"); full=row.get("water_full_mass_kg")
        if empty is not None and float(empty)<0:errors.append(f"STRUCTURAL_LOAD_{i}_NEGATIVE_EMPTY_MASS")
        if empty is not None and full is not None and float(full)<float(empty):errors.append(f"STRUCTURAL_LOAD_{i}_FULL_MASS_BELOW_EMPTY_MASS")
        review=row.get("structural_review") or {}
        if not isinstance(review,dict) or not review.get("approval_id"):missing.append(f"structural_rainwater_loads[{i}].structural_review.approval_id")
        elif review.get("status")!="APPROVED":errors.append(f"STRUCTURAL_LOAD_{i}_REVIEW_NOT_APPROVED")
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
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
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
    rows=_context(snapshot).get("rainwater_installation_interfaces")
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
                "evaluated_cases","governing_case_id","structural_analysis_id"):
        if row.get(key) in (None,"",{}):missing.append(f"structural_rainwater_load_combinations.{key}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    compatible={"FORCE":{"kN"},"MOMENT":{"kN_m"},"STRESS":{"kPa","MPa"},"PRESSURE":{"kPa","MPa"}}
    if row["effect_type"] not in compatible or row["effect_unit"] not in compatible.get(row["effect_type"],set()):
        return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_load_combinations.compatible_effect_type_and_unit"])
    if row["capacity_mode"]!="SYMMETRIC_ABSOLUTE":
        return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_load_combinations.signed_capacity_envelope"])
    D,L,Lr,S,R,W,E=(float(effects[k]) for k in required)
    cases={"LRFD-1":1.4*D,"LRFD-2-LR":1.2*D+1.6*L+.5*Lr,"LRFD-2-S":1.2*D+1.6*L+.5*S,"LRFD-2-R":1.2*D+1.6*L+.5*R,
        "LRFD-3-LR-L":1.2*D+1.6*Lr+L,"LRFD-3-S-L":1.2*D+1.6*S+L,"LRFD-3-R-L":1.2*D+1.6*R+L}
    for sign,label in ((1,"POS"),(-1,"NEG")):
        cases.update({f"LRFD-3-LR-W-{label}":1.2*D+1.6*Lr+sign*.8*W,
            f"LRFD-3-S-W-{label}":1.2*D+1.6*S+sign*.8*W,f"LRFD-3-R-W-{label}":1.2*D+1.6*R+sign*.8*W,
            f"LRFD-4-LR-W-{label}":1.2*D+sign*1.6*W+L+.5*Lr,
            f"LRFD-4-S-W-{label}":1.2*D+sign*1.6*W+L+.5*S,f"LRFD-4-R-W-{label}":1.2*D+sign*1.6*W+L+.5*R,
            f"LRFD-5-E-{label}":1.2*D+sign*E+L+.2*S,f"LRFD-6-W-{label}":.9*D+sign*1.6*W,
            f"LRFD-7-E-{label}":.9*D+sign*E})
    declared=row["evaluated_cases"];errors=[]
    for case_id,effect in cases.items():
        if case_id not in declared:errors.append("LOAD_COMBINATION_MISSING:"+case_id)
        elif abs(float(declared[case_id])-effect)>1e-6:errors.append("LOAD_COMBINATION_MISMATCH:"+case_id)
    governing=max(cases,key=lambda key:abs(cases[key]))
    if row["governing_case_id"]!=governing:errors.append("GOVERNING_LOAD_COMBINATION_MISMATCH")
    if float(row["design_capacity_abs"])<abs(cases[governing]):errors.append("DESIGN_CAPACITY_BELOW_GOVERNING_EFFECT")
    return _result(rule,FAIL if errors else PASS,evidence=[f"governing={governing}",f"effect={cases[governing]:.6g}{row['effect_unit']}",f"analysis={row['structural_analysis_id']}"],errors=errors)


def _asd_rainwater_load_combinations(rule, snapshot):
    row=_context(snapshot).get("structural_rainwater_asd_combinations")
    if not row:return _result(rule,INPUT_REQUIRED,missing=["structural_rainwater_asd_combinations"])
    effects=row.get("load_effects") or {};required=("D","L","Lr","S","R","W","E")
    missing=[f"structural_rainwater_asd_combinations.load_effects.{key}" for key in required if effects.get(key) is None]
    for key in ("effect_type","effect_unit","direction_convention","capacity_mode","allowable_capacity_abs",
                "evaluated_cases","governing_case_id","structural_analysis_id","allowable_stress_increase"):
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
                    "thermal_factor_ch","slope_factor_cs","declared_balanced_roof_snow_pr_kn_m2",
                    "declared_snow_unit_weight_kn_m3","declared_balanced_snow_height_m",
                    "exposure_geometry_analysis_id","roof_slope_degrees","surface_slippery",
                    "unobstructed_slide","adequate_fall_space"):
            if row.get(key) in (None,""):missing.append(f"roof_snow_load_basis[{i}].{key}")
        if any(row.get(k) is None for k in ("ground_snow_load_ps_kn_m2","importance_factor_is","exposure_factor_cn","thermal_factor_ch","slope_factor_cs","declared_balanced_roof_snow_pr_kn_m2","declared_snow_unit_weight_kn_m3","declared_balanced_snow_height_m","roof_slope_degrees","surface_slippery","unobstructed_slide","adequate_fall_space")):continue
        ch=float(row["thermal_factor_ch"]);alpha=float(row["roof_slope_degrees"])
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
        evidence.append(f"roof={row.get('roof_area_id')} Pr={pr:.6g}kN/m2 gamma={gamma:.6g}kN/m3 hb={hb:.6g}m geometry={row.get('exposure_geometry_analysis_id')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
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
                    "printed_reference_anomaly_acknowledged"):
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
            for key in ("approval_id","approver_role","status","source_clause","source_printed_page","source_document_sha256","structural_model_sha256"):
                if interpretation.get(key) in (None,""):missing.append(f"rooftop_snow_drift_features[{i}].structural_interpretation.{key}")
            if interpretation.get("approver_role") not in (None,"STRUCTURAL_ENGINEER"):errors.append(f"DRIFT_{i}_INTERPRETATION_APPROVER_INVALID")
            if interpretation.get("status") not in (None,"APPROVED"):errors.append(f"DRIFT_{i}_INTERPRETATION_NOT_APPROVED")
            if interpretation.get("source_clause") not in (None,"6-7-10 -> relation 6-7-5"):errors.append(f"DRIFT_{i}_INTERPRETATION_SOURCE_CLAUSE_MISMATCH")
            if interpretation.get("source_printed_page") not in (None,61):errors.append(f"DRIFT_{i}_INTERPRETATION_SOURCE_PAGE_MISMATCH")
        expected_height=float(row["declared_max_drift_height_m"])
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
        for key in ("roof_area_id","special_use_type","unreduced_l0_kn_m2","declared_design_live_load_kn_m2","structural_model_sha256"):
            if row.get(key) in (None,""):missing.append(f"special_use_roof_live_load_reductions[{i}].{key}")
        calc=row.get("section_6_5_5_calculation")
        if not isinstance(calc,dict):missing.append(f"special_use_roof_live_load_reductions[{i}].section_6_5_5_calculation");continue
        for key in ("calculation_id","method_clause","tributary_area_m2","result_kn_m2","status","model_sha256","engineer_approval_id"):
            if calc.get(key) in (None,""):missing.append(f"special_use_roof_live_load_reductions[{i}].section_6_5_5_calculation.{key}")
        if calc.get("method_clause") not in (None,"6-5-5"):errors.append(f"SPECIAL_ROOF_{i}_WRONG_REDUCTION_METHOD")
        if calc.get("model_sha256") and row.get("structural_model_sha256") and calc["model_sha256"]!=row["structural_model_sha256"]:errors.append(f"SPECIAL_ROOF_{i}_MODEL_MISMATCH")
        if calc.get("status") not in (None,"APPROVED"):errors.append(f"SPECIAL_ROOF_{i}_CALCULATION_NOT_APPROVED")
        if calc.get("result_kn_m2") is not None and row.get("declared_design_live_load_kn_m2") is not None and float(row["declared_design_live_load_kn_m2"])<float(calc["result_kn_m2"]):errors.append(f"SPECIAL_ROOF_{i}_DESIGN_LOAD_BELOW_APPROVED_RESULT")
        evidence.append(f"roof={row.get('roof_area_id')} use={row.get('special_use_type')} calc={(calc or {}).get('calculation_id')} model={row.get('structural_model_sha256')}")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
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
    "roof_serviceability_deflection":_roof_serviceability_deflection,
    "m4_rainwater_maintenance_access_geometry":_m4_rainwater_maintenance_access_geometry,
    "m4_parking_ramp_slope_geometry":_m4_parking_ramp_slope_geometry,
    "discharge_boundary_destination":_discharge_boundary_destination,
    "permanent_rainwater_dead_load":_permanent_rainwater_dead_load,
}


def evaluate_rainwater_rules(snapshot, *, llm_suggestions=None):
    integrity=validate_rulebook_module()
    if integrity["status"]!="PASS":
        return {"status":"FAIL","release_allowed":False,"errors":integrity["errors"],"evaluations":[]}
    working=deepcopy(snapshot or {})
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
