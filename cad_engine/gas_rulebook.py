"""Source-backed executable M17-1403 gas-meter placement rules."""
from math import isfinite

from .executable_rulebook import GAS_ROOT, load_rulebook_module, rule_rows, validate_rulebook_module

PASS, FAIL, INPUT_REQUIRED, NOT_APPLICABLE = "PASS", "FAIL", "INPUT_REQUIRED", "NOT_APPLICABLE"

def _finite(value):
    try: return isfinite(float(value))
    except (TypeError, ValueError): return False

def _result(rule, status, *, evidence=(), missing=(), errors=()):
    return {"rule_id":rule["rule_id"],"rule_version":rule["version"],"status":status,
            "source_ids":sorted({x for s in rule["sources"] for x in s["source_ids"]}),
            "evidence":list(evidence),"missing_inputs":sorted(set(missing)),
            "errors":sorted(set(errors)),"llm_override_allowed":False}

def _inventory(snapshot):
    gas=(snapshot or {}).get("gas") or {}
    return gas.get("meters"), gas.get("meter_inventory_complete")

def _meter_height(rule, snapshot):
    rows,complete=_inventory(snapshot)
    if rows is None or complete is None: return _result(rule,INPUT_REQUIRED,missing=["gas.meters","gas.meter_inventory_complete"])
    if complete is not True: return _result(rule,INPUT_REQUIRED,missing=["gas.meter_inventory_complete"])
    if not rows: return _result(rule,NOT_APPLICABLE,evidence=["complete gas-meter inventory contains zero rows"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        kind=row.get("location_class"); height=row.get("replacement_pipe_height_cm")
        if kind not in {"NORMAL","PARKING_OR_VEHICLE_TRAFFIC"}: missing.append(f"gas.meters[{i}].location_class")
        if not _finite(height) or float(height)<0: missing.append(f"gas.meters[{i}].replacement_pipe_height_cm"); continue
        evidence.append(f"meter[{i}] class={kind} replacement-pipe-height={float(height):g}cm")
        if kind=="NORMAL" and not 180<=float(height)<=240: errors.append(f"GAS_METER_HEIGHT_OUTSIDE_180_240_CM:{i}")
        if kind=="PARKING_OR_VEHICLE_TRAFFIC" and float(height)!=220: errors.append(f"GAS_METER_PARKING_HEIGHT_NOT_220_CM:{i}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _meter_clearances(rule, snapshot):
    rows,complete=_inventory(snapshot)
    if rows is None or complete is None:return _result(rule,INPUT_REQUIRED,missing=["gas.meters","gas.meter_inventory_complete"])
    if complete is not True:return _result(rule,INPUT_REQUIRED,missing=["gas.meter_inventory_complete"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["complete gas-meter inventory contains zero rows"])
    specs=(("clearance_to_live_electric_wire_cm",10,"GAS_METER_ELECTRIC_WIRE_CLEARANCE_LOW"),
           ("clearance_to_electric_meter_cm",50,"GAS_METER_ELECTRIC_METER_CLEARANCE_LOW"),
           ("clearance_to_gas_appliance_m",1,"GAS_METER_GAS_APPLIANCE_CLEARANCE_LOW"))
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        for field,minimum,code in specs:
            value=row.get(field)
            if not _finite(value) or float(value)<0: missing.append(f"gas.meters[{i}].{field}"); continue
            evidence.append(f"meter[{i}] {field}={float(value):g} minimum={minimum:g}")
            if float(value)<minimum: errors.append(f"{code}:{i}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _combustion_air_known_ach(rule, snapshot):
    gas=(snapshot or {}).get("gas") or {}; rows=gas.get("combustion_air_spaces")
    complete=gas.get("combustion_air_space_inventory_complete")
    if rows is None or complete is None:return _result(rule,INPUT_REQUIRED,missing=["gas.combustion_air_spaces","gas.combustion_air_space_inventory_complete"])
    if complete is not True:return _result(rule,INPUT_REQUIRED,missing=["gas.combustion_air_space_inventory_complete"])
    applicable=[];missing=[]
    for i,row in enumerate(rows):
        method=row.get("selected_method")
        if method=="KNOWN_ACH_ROOM_VOLUME": applicable.append((i,row))
        elif method=="OTHER_M17_COMBUSTION_AIR_METHOD":
            if not row.get("alternate_method_evidence_id"):
                missing.append(f"gas.combustion_air_spaces[{i}].alternate_method_evidence_id")
        else: missing.append(f"gas.combustion_air_spaces[{i}].selected_method")
    if missing:return _result(rule,INPUT_REQUIRED,missing=missing)
    if not applicable:return _result(rule,NOT_APPLICABLE,evidence=["all declared spaces use another source-backed M17 combustion-air method"])
    errors=[];evidence=[]
    for i,row in applicable:
        values={k:row.get(k) for k in ("room_volume_m3","ach","nonfan_input_kcal_h","fan_input_kcal_h")}
        bad=[k for k,v in values.items() if not _finite(v) or float(v)<0]
        if bad:
            missing.extend(f"gas.combustion_air_spaces[{i}].{k}" for k in bad);continue
        ach=float(values["ach"])
        if ach<0.6:
            errors.append(f"GAS_COMBUSTION_AIR_KNOWN_ACH_METHOD_BELOW_0_6:{i}");continue
        required=(2.35/ach)*(float(values["nonfan_input_kcal_h"])/1000)+(1.68/ach)*(float(values["fan_input_kcal_h"])/1000)
        provided=float(values["room_volume_m3"])
        evidence.append(f"space[{i}] required={required:.6f}m3 provided={provided:g}m3 ach={ach:g}")
        if provided+1e-9<required:errors.append(f"GAS_COMBUSTION_AIR_ROOM_VOLUME_LOW:{i}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _flue_design_documentation(rule, snapshot):
    gas=(snapshot or {}).get("gas") or {}; rows=gas.get("flue_designs");complete=gas.get("flue_design_inventory_complete")
    if rows is None or complete is None:return _result(rule,INPUT_REQUIRED,missing=["gas.flue_designs","gas.flue_design_inventory_complete"])
    if complete is not True:return _result(rule,INPUT_REQUIRED,missing=["gas.flue_design_inventory_complete"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["complete inventory contains no flued gas appliance"])
    missing=[];evidence=[]
    for i,row in enumerate(rows):
        for field in ("appliance_id","diameter_mm","material","route_polyline","capacity_calculation_id"):
            value=row.get(field)
            if value in (None,"") or field=="diameter_mm" and (not _finite(value) or float(value)<=0) or field=="route_polyline" and (not isinstance(value,list) or len(value)<2):
                missing.append(f"gas.flue_designs[{i}].{field}")
        if row.get("capacity_calculation_status")!="ENGINEER_APPROVED":
            missing.append(f"gas.flue_designs[{i}].capacity_calculation_status")
        evidence.append(f"flue[{i}] appliance={row.get('appliance_id')} diameter={row.get('diameter_mm')}mm route-points={len(row.get('route_polyline') or [])}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing)
    return _result(rule,PASS,evidence=evidence)

def _combustion_air_opening_geometry(rule, snapshot):
    gas=(snapshot or {}).get("gas") or {};rows=gas.get("combustion_air_openings");complete=gas.get("combustion_air_opening_inventory_complete")
    if rows is None or complete is None:return _result(rule,INPUT_REQUIRED,missing=["gas.combustion_air_openings","gas.combustion_air_opening_inventory_complete"])
    if complete is not True:return _result(rule,INPUT_REQUIRED,missing=["gas.combustion_air_opening_inventory_complete"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["complete inventory contains no combustion-air openings"])
    missing=[];errors=[];evidence=[];fractions={"METAL_GRILLE":.75,"WOOD_GRILLE":.25,"NO_GRILLE":1.0}
    for i,row in enumerate(rows):
        material=row.get("grille_material")
        if material not in fractions:missing.append(f"gas.combustion_air_openings[{i}].grille_material");continue
        fields=("gross_area_mm2","declared_free_area_mm2","required_free_area_mm2")
        bad=[f for f in fields if not _finite(row.get(f)) or float(row.get(f))<0]
        if bad:missing.extend(f"gas.combustion_air_openings[{i}].{f}" for f in bad);continue
        gross=float(row["gross_area_mm2"]);free=float(row["declared_free_area_mm2"]);required=float(row["required_free_area_mm2"])
        if material!="NO_GRILLE":
            dim=row.get("louver_min_dimension_mm")
            if not _finite(dim) or float(dim)<0:missing.append(f"gas.combustion_air_openings[{i}].louver_min_dimension_mm")
            elif float(dim)<7:errors.append(f"GAS_COMBUSTION_AIR_LOUVER_DIMENSION_LOW:{i}")
        if row.get("takes_air_directly_from_outdoors") is True:
            height=row.get("outdoor_inlet_bottom_above_ground_mm")
            if not _finite(height) or float(height)<0:missing.append(f"gas.combustion_air_openings[{i}].outdoor_inlet_bottom_above_ground_mm")
            elif float(height)<300:errors.append(f"GAS_COMBUSTION_AIR_OUTDOOR_INLET_HEIGHT_LOW:{i}")
        elif row.get("takes_air_directly_from_outdoors") is not False:
            missing.append(f"gas.combustion_air_openings[{i}].takes_air_directly_from_outdoors")
        maximum=gross*fractions[material]
        evidence.append(f"opening[{i}] gross={gross:g}mm2 free={free:g}mm2 required={required:g}mm2 cap={maximum:g}mm2")
        if free>maximum+1e-9:errors.append(f"GAS_COMBUSTION_AIR_FREE_AREA_OVERSTATED:{i}")
        if free+1e-9<required:errors.append(f"GAS_COMBUSTION_AIR_FREE_AREA_LOW:{i}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

def _combustion_air_duct_geometry(rule, snapshot):
    gas=(snapshot or {}).get("gas") or {};rows=gas.get("combustion_air_ducts");complete=gas.get("combustion_air_duct_inventory_complete")
    if rows is None or complete is None:return _result(rule,INPUT_REQUIRED,missing=["gas.combustion_air_ducts","gas.combustion_air_duct_inventory_complete"])
    if complete is not True:return _result(rule,INPUT_REQUIRED,missing=["gas.combustion_air_duct_inventory_complete"])
    if not rows:return _result(rule,NOT_APPLICABLE,evidence=["complete inventory contains no combustion-air ducts"])
    missing=[];errors=[];evidence=[]
    for i,row in enumerate(rows):
        shape=row.get("shape");free=row.get("free_area_mm2");opening=row.get("connected_opening_free_area_mm2")
        if shape not in {"RECTANGULAR","ROUND","OTHER_VERIFIED"}:missing.append(f"gas.combustion_air_ducts[{i}].shape")
        if not _finite(free) or float(free)<0:missing.append(f"gas.combustion_air_ducts[{i}].free_area_mm2")
        if not _finite(opening) or float(opening)<0:missing.append(f"gas.combustion_air_ducts[{i}].connected_opening_free_area_mm2")
        room_ids=row.get("served_room_ids");roles=row.get("served_opening_roles")
        if not isinstance(room_ids,list) or len(room_ids)!=1:errors.append(f"GAS_COMBUSTION_AIR_DUCT_NOT_DEDICATED_TO_ONE_ROOM:{i}")
        if not isinstance(roles,list) or len(roles)!=1 or roles[0] not in {"HIGH","LOW","SINGLE"}:errors.append(f"GAS_COMBUSTION_AIR_DUCT_SERVES_MULTIPLE_OPENING_ROLES:{i}")
        if shape=="RECTANGULAR":
            side=row.get("minimum_side_mm")
            if not _finite(side) or float(side)<0:missing.append(f"gas.combustion_air_ducts[{i}].minimum_side_mm")
            elif float(side)<80:errors.append(f"GAS_COMBUSTION_AIR_DUCT_SIDE_LOW:{i}")
        if _finite(free) and _finite(opening):
            evidence.append(f"duct[{i}] free={float(free):g}mm2 opening={float(opening):g}mm2")
            if float(free)<10000:errors.append(f"GAS_COMBUSTION_AIR_DUCT_AREA_BELOW_10000_MM2:{i}")
            if float(free)+1e-9<float(opening):errors.append(f"GAS_COMBUSTION_AIR_DUCT_BELOW_OPENING_AREA:{i}")
    if missing:return _result(rule,INPUT_REQUIRED,evidence=evidence,missing=missing,errors=errors)
    return _result(rule,FAIL if errors else PASS,evidence=evidence,errors=errors)

VALIDATORS={"gas_meter_replacement_pipe_height":_meter_height,
            "gas_meter_electrical_and_appliance_clearances":_meter_clearances,
            "gas_combustion_air_known_ach_room_volume":_combustion_air_known_ach,
            "gas_flue_design_documentation":_flue_design_documentation,
            "gas_combustion_air_opening_geometry":_combustion_air_opening_geometry,
            "gas_combustion_air_duct_geometry":_combustion_air_duct_geometry}

def load_gas_rulebook():
    module=load_rulebook_module(GAS_ROOT); integrity=validate_rulebook_module(module)
    if integrity["status"]!="PASS":raise ValueError("gas Rulebook integrity failed: "+",".join(integrity["errors"]))
    return module

def evaluate_gas_rulebook(snapshot):
    module=load_gas_rulebook();results=[VALIDATORS[r["validator"]](r,snapshot) for r in rule_rows(module)]
    status=FAIL if any(r["status"]==FAIL for r in results) else INPUT_REQUIRED if any(r["status"]==INPUT_REQUIRED for r in results) else PASS
    return {"module_id":module["manifest"]["module_id"],"module_version":module["manifest"]["version"],"results":results,"status":status}

def gas_design_profile():
    module=load_gas_rulebook();rows={r["validator"]:r for r in rule_rows(module)}
    return {"module_version":module["manifest"]["version"],
            "meter_height":rows["gas_meter_replacement_pipe_height"]["parameters"],
            "meter_clearances":rows["gas_meter_electrical_and_appliance_clearances"]["parameters"],
            "combustion_air_known_ach":rows["gas_combustion_air_known_ach_room_volume"]["parameters"],
            "flue_design_documentation":rows["gas_flue_design_documentation"]["parameters"],
            "combustion_air_openings":rows["gas_combustion_air_opening_geometry"]["parameters"],
            "combustion_air_ducts":rows["gas_combustion_air_duct_geometry"]["parameters"],
            "authority":"M17-1403","source_ids":["M17-G-001","M17-G-002","M17-G-003","M17-G-004","M17-G-005","M17-G-006"]}
