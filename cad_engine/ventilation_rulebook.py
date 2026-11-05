"""Source-backed executable M14 ventilation and exhaust rules."""
from math import isfinite

from .executable_rulebook import VENTILATION_ROOT, load_rulebook_module, rule_rows, validate_rulebook_module

PASS, FAIL, INPUT_REQUIRED, NOT_APPLICABLE = "PASS", "FAIL", "INPUT_REQUIRED", "NOT_APPLICABLE"
OUTSIDE_AIR_USAGES = {"RESIDENTIAL_ROOM", "OFFICE_ROOM", "OFFICE_CONFERENCE", "OFFICE_RECEPTION",
    "HOTEL_BEDROOM", "HOTEL_LOBBY", "HOTEL_CONFERENCE", "ASSEMBLY_HALL", "MOSQUE", "CINEMA",
    "THEATER", "RESTAURANT_DINING", "CAFE", "RETAIL_FLOOR", "RETAIL_BASEMENT", "RETAIL_STORAGE",
    "DRY_CLEANING", "LAUNDRY_STORAGE", "GYM_SPECTATOR", "GYM_SPORTS", "INDOOR_POOL",
    "CLASSROOM", "LABORATORY", "LIBRARY", "WORKSHOP", "LOCKER_ROOM", "CORRIDOR"}
KNOWN_SPACE_USAGES = ({"RESIDENTIAL_KITCHEN", "RESIDENTIAL_BATHROOM_OR_TOILET",
                       "PRIVATE_PARKING", "COMMON_PARKING", "VERIFIED_OUT_OF_SCOPE"} | OUTSIDE_AIR_USAGES)

def _finite(value):
    try: return isfinite(float(value))
    except (TypeError, ValueError): return False

def _result(rule, status, *, evidence=(), missing=(), errors=()):
    return {"rule_id":rule["rule_id"], "rule_version":rule["version"], "status":status,
            "source_ids":sorted({x for s in rule["sources"] for x in s["source_ids"]}),
            "evidence":list(evidence), "missing_inputs":sorted(set(missing)),
            "errors":sorted(set(errors)), "llm_override_allowed":False}

def _residential_exhaust(rule, snapshot):
    vent=(snapshot or {}).get("ventilation") or {}; rows=vent.get("spaces"); complete=vent.get("space_inventory_complete")
    if rows is None or complete is None: return _result(rule, INPUT_REQUIRED, missing=["ventilation.spaces","ventilation.space_inventory_complete"])
    if complete is not True: return _result(rule, INPUT_REQUIRED, missing=["ventilation.space_inventory_complete"])
    supported={"RESIDENTIAL_KITCHEN","RESIDENTIAL_BATHROOM_OR_TOILET"}
    unknown=[i for i,r in enumerate(rows) if r.get("usage") not in KNOWN_SPACE_USAGES]
    if unknown:
        return _result(rule, INPUT_REQUIRED,
                       missing=[f"ventilation.spaces[{i}].usage" for i in unknown])
    applicable=[(i,r) for i,r in enumerate(rows) if r.get("usage") in supported]
    if not applicable: return _result(rule, NOT_APPLICABLE, evidence=["complete inventory has no supported residential exhaust spaces"])
    required={"RESIDENTIAL_KITCHEN":50.0,"RESIDENTIAL_BATHROOM_OR_TOILET":25.0}; missing=[]; errors=[]; evidence=[]
    for i,row in applicable:
        value=row.get("design_exhaust_lps"); need=required[row["usage"]]
        if not _finite(value) or float(value)<0: missing.append(f"ventilation.spaces[{i}].design_exhaust_lps"); continue
        evidence.append(f"{row.get('space_id',i)} required={need:g}L/s={need*3.6:g}m3/h provided={float(value):g}L/s")
        if float(value)<need: errors.append(f"VENTILATION_EXHAUST_FLOW_LOW:{row.get('space_id',i)}")
    if missing: return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

def _parking_rates(rule, snapshot):
    vent=(snapshot or {}).get("ventilation") or {};rows=vent.get("spaces");complete=vent.get("space_inventory_complete")
    if rows is None or complete is not True:
        return _result(rule,INPUT_REQUIRED,missing=["ventilation.spaces","ventilation.space_inventory_complete"])
    unknown=[i for i,row in enumerate(rows) if row.get("usage") not in KNOWN_SPACE_USAGES]
    if unknown:return _result(rule,INPUT_REQUIRED,missing=[f"ventilation.spaces[{i}].usage" for i in unknown])
    applicable=[(i,row) for i,row in enumerate(rows) if row.get("usage") in {"PRIVATE_PARKING","COMMON_PARKING"}]
    if not applicable:return _result(rule,NOT_APPLICABLE,evidence=["complete inventory has no private or common parking"])
    params=rule["parameters"];missing=[];errors=[];evidence=[]
    for i,row in applicable:
        sid=row.get("space_id",i);usage=row["usage"]
        basis="vehicle_count" if usage=="PRIVATE_PARKING" else "floor_area_m2"
        value=row.get(basis);provided=row.get("design_ventilation_lps")
        if not _finite(value) or float(value)<=0:missing.append(f"ventilation.spaces[{i}].{basis}");continue
        if not _finite(provided) or float(provided)<0:missing.append(f"ventilation.spaces[{i}].design_ventilation_lps");continue
        required=(float(value)*float(params["private_parking_lps_per_vehicle"]) if usage=="PRIVATE_PARKING"
                  else float(value)*float(params["common_parking_lps_per_m2"]))
        evidence.append(f"{sid} basis={basis}:{float(value):g} required={required:g}L/s provided={float(provided):g}L/s")
        if float(provided)<required:errors.append(f"VENTILATION_PARKING_FLOW_LOW:{sid}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _enclosed_parking_co_control(rule, snapshot):
    vent=(snapshot or {}).get("ventilation") or {};rows=vent.get("spaces");complete=vent.get("space_inventory_complete")
    if rows is None or complete is not True:
        return _result(rule,INPUT_REQUIRED,missing=["ventilation.spaces","ventilation.space_inventory_complete"])
    parking=[(i,row) for i,row in enumerate(rows) if row.get("usage") in {"PRIVATE_PARKING","COMMON_PARKING"}]
    missing_enclosure=[f"ventilation.spaces[{i}].enclosure" for i,row in parking if row.get("enclosure") not in {"ENCLOSED","OPEN"}]
    if missing_enclosure:return _result(rule,INPUT_REQUIRED,missing=missing_enclosure)
    applicable=[(i,row) for i,row in parking if row.get("enclosure")=="ENCLOSED"]
    if not applicable:return _result(rule,NOT_APPLICABLE,evidence=["no enclosed parking or garage in complete inventory"])
    params=rule["parameters"];missing=[];errors=[];evidence=[]
    for i,row in applicable:
        sid=row.get("space_id",i);area=row.get("floor_area_m2");full=row.get("full_system_capacity_lps")
        minimum=row.get("minimum_controlled_capacity_lps");setpoint=row.get("co_control_setpoint_ppm")
        for key,value in (("floor_area_m2",area),("full_system_capacity_lps",full),
                          ("minimum_controlled_capacity_lps",minimum),("co_control_setpoint_ppm",setpoint)):
            if not _finite(value) or float(value)<0:missing.append(f"ventilation.spaces[{i}].{key}")
        for key in ("automatic_operation_enabled","pollutant_control_enabled"):
            if row.get(key) is not True:missing.append(f"ventilation.spaces[{i}].{key}")
        if any(f"ventilation.spaces[{i}]." in item for item in missing):continue
        required_full=float(area)*float(params["full_capacity_lps_per_m2"])
        required_min=float(area)*float(params["minimum_controlled_capacity_lps_per_m2"])
        evidence.append(f"{sid} area={float(area):g}m2 full={float(full):g}/{required_full:g}L/s minimum={float(minimum):g}/{required_min:g}L/s CO-setpoint={float(setpoint):g}ppm")
        if float(full)<required_full:errors.append(f"VENTILATION_PARKING_FULL_CAPACITY_LOW:{sid}")
        if float(minimum)<required_min:errors.append(f"VENTILATION_PARKING_MINIMUM_CONTROLLED_CAPACITY_LOW:{sid}")
        if float(setpoint)>=float(params["maximum_co_ppm_exclusive"]):errors.append(f"VENTILATION_PARKING_CO_SETPOINT_NOT_BELOW_25PPM:{sid}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _outside_air_rates(rule, snapshot):
    vent=(snapshot or {}).get("ventilation") or {};rows=vent.get("spaces");complete=vent.get("space_inventory_complete")
    if rows is None or complete is not True:
        return _result(rule,INPUT_REQUIRED,missing=["ventilation.spaces","ventilation.space_inventory_complete"])
    unknown=[i for i,row in enumerate(rows) if row.get("usage") not in KNOWN_SPACE_USAGES]
    if unknown:return _result(rule,INPUT_REQUIRED,missing=[f"ventilation.spaces[{i}].usage" for i in unknown])
    applicable=[(i,row) for i,row in enumerate(rows) if row.get("usage") in OUTSIDE_AIR_USAGES]
    if not applicable:return _result(rule,NOT_APPLICABLE,evidence=["complete inventory has no supported single-basis outside-air spaces"])
    rates=rule["parameters"]["rates_by_usage"];missing=[];errors=[];evidence=[]
    for i,row in applicable:
        sid=row.get("space_id",i);rate=rates[row["usage"]];basis=rate["basis"]
        input_field="occupant_count" if basis=="PER_PERSON" else "floor_area_m2"
        value=row.get(input_field);provided=row.get("design_outside_air_lps")
        if not _finite(value) or float(value)<=0:missing.append(f"ventilation.spaces[{i}].{input_field}");continue
        if not _finite(provided) or float(provided)<0:missing.append(f"ventilation.spaces[{i}].design_outside_air_lps");continue
        required=float(value)*float(rate["lps_per_unit"])
        evidence.append(f"{sid} usage={row['usage']} basis={basis}:{float(value):g} required={required:g}L/s provided={float(provided):g}L/s")
        if float(provided)<required:errors.append(f"VENTILATION_OUTSIDE_AIR_FLOW_LOW:{sid}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _intake_separation(rule, snapshot):
    vent=(snapshot or {}).get("ventilation") or {}; rows=vent.get("outside_air_intakes"); complete=vent.get("outside_air_intake_inventory_complete")
    if rows is None or complete is None: return _result(rule, INPUT_REQUIRED, missing=["ventilation.outside_air_intakes","ventilation.outside_air_intake_inventory_complete"])
    if complete is not True: return _result(rule, INPUT_REQUIRED, missing=["ventilation.outside_air_intake_inventory_complete"])
    supported={"HAZARDOUS_OR_CONTAMINATED","RESIDENTIAL_KITCHEN_OR_BATH_EXHAUST","NO_NEARBY_EXHAUST"}
    unknown=[i for i,r in enumerate(rows) if r.get("nearest_exhaust_class") not in supported]
    if unknown:
        return _result(rule, INPUT_REQUIRED,
                       missing=[f"ventilation.outside_air_intakes[{i}].nearest_exhaust_class" for i in unknown])
    applicable=[(i,r) for i,r in enumerate(rows)
                if r.get("nearest_exhaust_class") == "HAZARDOUS_OR_CONTAMINATED"]
    if not applicable: return _result(rule, NOT_APPLICABLE, evidence=["no hazardous/contaminated exhaust adjacent to declared intakes"])
    missing=[]; errors=[]; evidence=[]
    for i,row in applicable:
        horizontal=row.get("horizontal_distance_m"); below=row.get("intake_below_exhaust_m")
        if not _finite(horizontal) or float(horizontal)<0: missing.append(f"ventilation.outside_air_intakes[{i}].horizontal_distance_m")
        if not _finite(below) or float(below)<0: missing.append(f"ventilation.outside_air_intakes[{i}].intake_below_exhaust_m")
        if _finite(horizontal) and _finite(below) and float(horizontal)>=0 and float(below)>=0:
            evidence.append(f"intake[{i}] horizontal={float(horizontal):g}m below={float(below):g}m")
            if float(horizontal)<3 and float(below)<1: errors.append(f"VENTILATION_OUTSIDE_AIR_INTAKE_SEPARATION_LOW:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)

VALIDATORS={"ventilation_residential_exhaust_rates":_residential_exhaust,
            "ventilation_outside_air_intake_separation":_intake_separation,
            "ventilation_parking_rates":_parking_rates,
            "ventilation_enclosed_parking_co_control":_enclosed_parking_co_control,
            "ventilation_outside_air_rates":_outside_air_rates}

def load_ventilation_rulebook():
    module=load_rulebook_module(VENTILATION_ROOT); integrity=validate_rulebook_module(module)
    if integrity["status"]!="PASS": raise ValueError("ventilation Rulebook integrity failed: "+",".join(integrity["errors"]))
    return module

def evaluate_ventilation_rulebook(snapshot):
    module=load_ventilation_rulebook(); results=[VALIDATORS[r["validator"]](r,snapshot) for r in rule_rows(module)]
    status=FAIL if any(r["status"]==FAIL for r in results) else INPUT_REQUIRED if any(r["status"]==INPUT_REQUIRED for r in results) else PASS
    return {"module_id":module["manifest"]["module_id"],"module_version":module["manifest"]["version"],"results":results,"status":status}

def ventilation_design_profile():
    module=load_ventilation_rulebook(); rows={r["validator"]:r for r in rule_rows(module)}
    rates=rows["ventilation_residential_exhaust_rates"]["parameters"]
    return {"module_version":module["manifest"]["version"],"residential_exhaust_rates":rates,
            "parking_rates":rows["ventilation_parking_rates"]["parameters"],
            "enclosed_parking_co_control":rows["ventilation_enclosed_parking_co_control"]["parameters"],
            "outside_air_rates":rows["ventilation_outside_air_rates"]["parameters"],
            "outside_air_intake_separation":rows["ventilation_outside_air_intake_separation"]["parameters"],
            "authority":"M14-1391","source_ids":["M14-V-001","M14-V-002","M14-V-003","M14-V-004"]}

def design_ventilation_from_rulebook(spaces, outside_air_intakes, design_basis):
    """Calculate exact M14 duties and explicit-basis round-duct candidates."""
    from .hvac_calculations import size_round_duct
    required={"max_duct_velocity_m_s","candidate_round_duct_diameters_mm"}
    missing=sorted(required-set(design_basis or {}))
    if missing:return {"status":INPUT_REQUIRED,"missing_inputs":missing,"spaces":[],"intakes":[]}
    profile=ventilation_design_profile();rates=profile["residential_exhaust_rates"];parking=profile["parking_rates"]
    rate_by_usage={"RESIDENTIAL_KITCHEN":float(rates["residential_kitchen_lps_per_room"]),
                   "RESIDENTIAL_BATHROOM_OR_TOILET":float(rates["residential_bathroom_or_toilet_lps_per_room"])}
    rows=[];source_spaces=[];errors=[];needed=[]
    for index,space in enumerate(spaces or []):
        sid=str(space.get("space_id") or f"SPACE-{index}");usage=str(space.get("usage") or "")
        if usage in rate_by_usage:
            flow=rate_by_usage[usage]
        elif usage=="PRIVATE_PARKING":
            count=space.get("vehicle_count")
            if not _finite(count) or float(count)<=0:needed.append(f"{sid}:vehicle_count");continue
            flow=float(count)*float(parking["private_parking_lps_per_vehicle"])
        elif usage=="COMMON_PARKING":
            area=space.get("floor_area_m2")
            if not _finite(area) or float(area)<=0:needed.append(f"{sid}:floor_area_m2");continue
            flow=float(area)*float(parking["common_parking_lps_per_m2"])
        elif usage in OUTSIDE_AIR_USAGES:
            rate=profile["outside_air_rates"]["rates_by_usage"][usage]
            field="occupant_count" if rate["basis"]=="PER_PERSON" else "floor_area_m2"
            value=space.get(field)
            if not _finite(value) or float(value)<=0:needed.append(f"{sid}:{field}");continue
            flow=float(value)*float(rate["lps_per_unit"])
        else:needed.append(f"{sid}:supported_usage");continue
        source_space={"space_id":sid,"usage":usage,"design_exhaust_lps":flow,
                      "design_ventilation_lps":flow}
        if usage in {"PRIVATE_PARKING","COMMON_PARKING"}:
            source_space.update({key:space.get(key) for key in ("vehicle_count","floor_area_m2","enclosure",
                "automatic_operation_enabled","pollutant_control_enabled","co_control_setpoint_ppm")})
            if space.get("enclosure")=="ENCLOSED" and _finite(space.get("floor_area_m2")):
                area=float(space["floor_area_m2"]);control=profile["enclosed_parking_co_control"]
                source_space["full_system_capacity_lps"]=max(flow,area*float(control["full_capacity_lps_per_m2"]))
                source_space["minimum_controlled_capacity_lps"]=area*float(control["minimum_controlled_capacity_lps_per_m2"])
                flow=source_space["full_system_capacity_lps"]
        elif usage in OUTSIDE_AIR_USAGES:
            source_space.update({"design_outside_air_lps":flow,
                                 "occupant_count":space.get("occupant_count"),
                                 "floor_area_m2":space.get("floor_area_m2")})
        duct=size_round_duct(flow,design_basis["max_duct_velocity_m_s"],design_basis["candidate_round_duct_diameters_mm"])
        if duct["status"]!="PASS":errors.append(f"{sid}:no_compliant_round_duct")
        rule_id=("IR-M14-1391-T14.4.2-PARKING-VENTILATION-RATES" if usage in {"PRIVATE_PARKING","COMMON_PARKING"}
                 else "IR-M14-1391-T14.4.2-OUTSIDE-AIR-RATES" if usage in OUTSIDE_AIR_USAGES
                 else "IR-M14-1391-T14.4.2-RESIDENTIAL-EXHAUST-RATES")
        rows.append({"space_id":sid,"usage":usage,"required_exhaust_lps":flow,"required_exhaust_m3h":flow*3.6,
                     "duct_sizing":duct,"rule_id":rule_id,
                     "release_allowed":False})
        source_spaces.append(source_space)
    intake_rows=[]
    for index,row in enumerate(outside_air_intakes or []):
        iid=str(row.get("intake_id") or f"INTAKE-{index}");ip=row.get("point_xyz");ep=row.get("nearest_exhaust_point_xyz")
        if not isinstance(ip,(list,tuple)) or len(ip)!=3 or not isinstance(ep,(list,tuple)) or len(ep)!=3:
            needed.append(f"{iid}:intake_and_exhaust_points_xyz");continue
        horizontal=((float(ip[0])-float(ep[0]))**2+(float(ip[1])-float(ep[1]))**2)**0.5
        below=max(0.0,float(ep[2])-float(ip[2]))
        intake_rows.append({"intake_id":iid,"nearest_exhaust_class":row.get("nearest_exhaust_class"),
                            "horizontal_distance_m":horizontal,"intake_below_exhaust_m":below})
    snapshot={"ventilation":{"space_inventory_complete":True,"spaces":source_spaces,
             "outside_air_intake_inventory_complete":True,"outside_air_intakes":intake_rows}}
    evaluated=evaluate_ventilation_rulebook(snapshot)
    all_missing=sorted(set(needed+[x for r in evaluated["results"] for x in r["missing_inputs"]]))
    all_errors=sorted(set(errors+[x for r in evaluated["results"] for x in r["errors"]]))
    status=FAIL if all_errors else INPUT_REQUIRED if all_missing else PASS
    return {"status":status,"missing_inputs":all_missing,"errors":all_errors,"spaces":rows,"intakes":intake_rows,
            "rule_results":evaluated["results"],"rulebook_module_version":profile["module_version"],
            "coverage_limit":"M14_VERIFIED_SINGLE_BASIS_AND_EXHAUST_ROWS_ONLY"}

def design_residential_ventilation_from_rulebook(spaces, outside_air_intakes, design_basis):
    """Backward-compatible entrypoint; supported scope now includes verified parking rows."""
    return design_ventilation_from_rulebook(spaces,outside_air_intakes,design_basis)
