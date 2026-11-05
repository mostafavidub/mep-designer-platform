"""Executable M16 sanitary drainage and vent Rulebook module."""
from __future__ import annotations

from math import isfinite

from .executable_rulebook import SANITARY_ROOT, load_rulebook_module, rule_rows, validate_rulebook_module

PASS, FAIL, INPUT_REQUIRED, NOT_APPLICABLE = "PASS", "FAIL", "INPUT_REQUIRED", "NOT_APPLICABLE"


def _finite(value):
    try: return isfinite(float(value))
    except (TypeError, ValueError): return False


def _result(rule, status, *, evidence=(), missing=(), errors=()):
    return {"rule_id":rule["rule_id"],"rule_version":rule["version"],"status":status,
            "source_ids":sorted({v for s in rule["sources"] for v in s["source_ids"]}),
            "evidence":list(evidence),"missing_inputs":sorted(set(missing)),
            "errors":sorted(set(errors)),"llm_override_allowed":False}


def _trap_dn(rule, snapshot):
    rows = ((snapshot or {}).get("sanitary") or {}).get("traps")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["sanitary.traps"])
    table=rule["parameters"]["minimum_dn_mm"]; missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        fixture=str(row.get("fixture_type") or ""); dn=row.get("dn_mm")
        if fixture not in table: missing.append(f"sanitary.traps[{i}].supported_fixture_type")
        elif not _finite(dn) or float(dn)<=0: missing.append(f"sanitary.traps[{i}].dn_mm")
        else:
            minimum=float(table[fixture]); evidence.append(f"trap[{i}] DN{float(dn):g} min=DN{minimum:g}")
            if float(dn)<minimum: errors.append(f"TRAP_DN_LOW:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _slope_velocity(rule, snapshot):
    rows=((snapshot or {}).get("sanitary") or {}).get("horizontal_segments")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["sanitary.horizontal_segments"])
    p=rule["parameters"]; missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        dn,slope,velocity=row.get("dn_mm"),row.get("slope_percent"),row.get("velocity_m_s")
        if not all(_finite(v) for v in (dn,slope,velocity)) or float(dn)<=0:
            missing.append(f"sanitary.horizontal_segments[{i}].numeric_geometry_and_velocity"); continue
        dn=float(dn); slope=float(slope); velocity=float(velocity)
        if dn<=65: minimum=p["minimum_slope_percent"]["dn_le_65"]
        elif 80<=dn<=150: minimum=p["minimum_slope_percent"]["dn_80_to_150"]
        elif dn>=200: minimum=p["minimum_slope_percent"]["dn_ge_200"]
        else:
            missing.append(f"sanitary.horizontal_segments[{i}].supported_nominal_dn_band"); continue
        evidence.append(f"segment[{i}] DN{dn:g} slope={slope:g}% min={minimum:g}% velocity={velocity:g}m/s")
        if slope<minimum: errors.append(f"HORIZONTAL_SLOPE_LOW:{i}")
        if slope>float(p["maximum_slope_percent"]): errors.append(f"HORIZONTAL_SLOPE_ABOVE_4_PERCENT:{i}")
        if velocity<float(p["minimum_velocity_m_s"]): errors.append(f"HORIZONTAL_VELOCITY_LOW:{i}")
        if row.get("reverse_slope") is True: errors.append(f"HORIZONTAL_REVERSE_SLOPE:{i}")
        elif row.get("reverse_slope") is None: missing.append(f"sanitary.horizontal_segments[{i}].reverse_slope")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _termination(rule, snapshot):
    rows=((snapshot or {}).get("vent") or {}).get("terminations")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["vent.terminations"])
    p=rule["parameters"]; missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        required=("horizontal_to_opening_m","vertical_above_opening_m","directly_below_opening","wall_exit")
        for key in required:
            if row.get(key) is None: missing.append(f"vent.terminations[{i}].{key}")
        if missing: continue
        h=row["horizontal_to_opening_m"]; v=row["vertical_above_opening_m"]
        if not _finite(h) or not _finite(v): missing.append(f"vent.terminations[{i}].opening_clearance_geometry"); continue
        if row["directly_below_opening"] is True: errors.append(f"VENT_DIRECTLY_BELOW_OPENING:{i}")
        if float(h)<p["opening_horizontal_m"] and float(v)<p["opening_vertical_above_m"]:
            errors.append(f"VENT_OPENING_CLEARANCE_LOW:{i}")
        if row["wall_exit"] is True:
            for key in ("horizontal_to_property_m","height_above_ground_m","under_balcony_or_canopy"):
                if row.get(key) is None: missing.append(f"vent.terminations[{i}].{key}")
            if _finite(row.get("horizontal_to_property_m")) and float(row["horizontal_to_property_m"])<p["wall_property_horizontal_m"]: errors.append(f"VENT_PROPERTY_CLEARANCE_LOW:{i}")
            if _finite(row.get("height_above_ground_m")) and float(row["height_above_ground_m"])<p["wall_height_above_ground_m"]: errors.append(f"VENT_HEIGHT_ABOVE_GROUND_LOW:{i}")
            if row.get("under_balcony_or_canopy") is True: errors.append(f"VENT_UNDER_BALCONY_OR_CANOPY:{i}")
        evidence.append(f"termination[{i}] opening_h={float(h):g}m opening_above={float(v):g}m")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _trap_vent_distance(rule, snapshot):
    rows=((snapshot or {}).get("vent") or {}).get("fixture_connections")
    if rows is None: return _result(rule, INPUT_REQUIRED, missing=["vent.fixture_connections"])
    if not rows: return _result(rule, NOT_APPLICABLE, evidence=["fixture_connections=0"])
    table=rule["parameters"]["rows"]; missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        dn,slope,distance=row.get("waste_dn_mm"),row.get("waste_slope_percent"),row.get("trap_weir_to_vent_m")
        if not all(_finite(v) for v in (dn,slope,distance)):
            missing.append(f"vent.fixture_connections[{i}].numeric_geometry"); continue
        key=f"{float(dn):g}@{float(slope):g}"; selected=table.get(key)
        if not selected: missing.append(f"vent.fixture_connections[{i}].exact_supported_dn_slope_row"); continue
        maximum=float(selected["maximum_m"]); evidence.append(f"connection[{i}] {key}% distance={float(distance):g}m max={maximum:g}m")
        if float(distance)>maximum: errors.append(f"TRAP_VENT_DISTANCE_HIGH:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _fixture_dfu(rule, snapshot):
    rows=((snapshot or {}).get("sanitary") or {}).get("fixtures")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["sanitary.fixtures"])
    table=rule["parameters"]["fixture_dfu"]; missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        fixture=str(row.get("fixture_type") or ""); count=row.get("count"); declared=row.get("declared_total_dfu")
        if fixture not in table: missing.append(f"sanitary.fixtures[{i}].supported_fixture_type"); continue
        if not _finite(count) or float(count)<=0 or not float(count).is_integer(): missing.append(f"sanitary.fixtures[{i}].count"); continue
        if not _finite(declared): missing.append(f"sanitary.fixtures[{i}].declared_total_dfu"); continue
        expected=float(table[fixture])*int(float(count)); evidence.append(f"fixtures[{i}] {fixture} count={int(float(count))} DFU={expected:g}")
        if abs(float(declared)-expected)>1e-9: errors.append(f"FIXTURE_DFU_TOTAL_MISMATCH:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _branch_stack_capacity(rule, snapshot):
    rows=((snapshot or {}).get("sanitary") or {}).get("sizing_segments")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["sanitary.sizing_segments"])
    table=rule["parameters"]["maximum_dfu_by_dn"]; missing=[]; errors=[]; evidence=[]
    keys={"HORIZONTAL_BRANCH":"horizontal_branch","STACK_PER_FLOOR":"stack_per_floor",
          "STACK_UP_TO_3_FLOORS":"stack_up_to_3_floors","STACK_OVER_3_FLOORS":"stack_over_3_floors"}
    for i,row in enumerate(rows):
        kind=str(row.get("segment_kind") or ""); dn=row.get("dn_mm"); load=row.get("calculated_dfu")
        if kind not in keys: missing.append(f"sanitary.sizing_segments[{i}].supported_segment_kind"); continue
        dnkey=f"{float(dn):g}" if _finite(dn) else ""; selected=table.get(dnkey)
        if not selected or selected.get(keys[kind]) is None: missing.append(f"sanitary.sizing_segments[{i}].supported_dn_capacity"); continue
        if not _finite(load) or float(load)<0: missing.append(f"sanitary.sizing_segments[{i}].calculated_dfu"); continue
        maximum=float(selected[keys[kind]]); evidence.append(f"segment[{i}] {kind} DN{dnkey} load={float(load):g} max={maximum:g}DFU")
        if float(load)>maximum: errors.append(f"SANITARY_SEGMENT_CAPACITY_EXCEEDED:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _cleanout(rule, snapshot):
    sanitary=(snapshot or {}).get("sanitary") or {}; rows=sanitary.get("cleanouts")
    if rows is None or sanitary.get("cleanout_inventory_complete") is None:
        return _result(rule, INPUT_REQUIRED, missing=["sanitary.cleanouts","sanitary.cleanout_inventory_complete"])
    if sanitary["cleanout_inventory_complete"] is not True:
        return _result(rule, FAIL, errors=["CLEANOUT_INVENTORY_INCOMPLETE"])
    required={"HIGHEST_HORIZONTAL_BRANCH","DIRECTION_CHANGE_OVER_45","STACK_BASE","WATER_TEST_ACCESS","BUILDING_EXIT"}
    present={str(r.get("location_type") or "") for r in rows}; missing=[]; errors=[]; evidence=[]
    if not required.issubset(present): errors.append("REQUIRED_CLEANOUT_LOCATION_MISSING")
    for i,row in enumerate(rows):
        pipe,opening,clearance=row.get("pipe_dn_mm"),row.get("cleanout_dn_mm"),row.get("opposite_wall_clearance_mm")
        if not all(_finite(v) for v in (pipe,opening,clearance)):
            missing.append(f"sanitary.cleanouts[{i}].numeric_size_and_clearance"); continue
        minimum=min(float(pipe),100.0)
        if float(opening)<minimum: errors.append(f"CLEANOUT_DN_LOW:{i}")
        if float(clearance)<450.0: errors.append(f"CLEANOUT_CLEARANCE_LOW:{i}")
        if row.get("location_type")=="MAIN_HORIZONTAL_INTERVAL" and (not _finite(row.get("distance_from_previous_m")) or float(row["distance_from_previous_m"])>30): errors.append(f"CLEANOUT_SPACING_HIGH:{i}")
        evidence.append(f"cleanout[{i}] pipe=DN{float(pipe):g} opening=DN{float(opening):g} clearance={float(clearance):g}mm")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _vent_minimum_size(rule, snapshot):
    rows=((snapshot or {}).get("vent") or {}).get("sizing_segments")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["vent.sizing_segments"])
    standard=rule["parameters"]["nominal_dn_series_mm"]; missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        waste,vent,length=row.get("waste_dn_mm"),row.get("vent_dn_mm"),row.get("length_m")
        if not all(_finite(v) for v in (waste,vent,length)) or float(waste)<=0 or float(vent)<=0 or float(length)<0:
            missing.append(f"vent.sizing_segments[{i}].numeric_geometry"); continue
        base=max(32.0,float(waste)/2.0); required=next((float(v) for v in standard if float(v)>=base),None)
        if required is None: missing.append(f"vent.sizing_segments[{i}].supported_nominal_dn"); continue
        if float(length)>12:
            idx=standard.index(int(required)) if int(required) in standard else -1
            if idx<0 or idx+1>=len(standard): missing.append(f"vent.sizing_segments[{i}].next_nominal_dn"); continue
            required=float(standard[idx+1])
        evidence.append(f"vent[{i}] waste=DN{float(waste):g} length={float(length):g}m required=DN{required:g}")
        if float(vent)<required: errors.append(f"VENT_DN_LOW:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _main_horizontal_capacity(rule, snapshot):
    rows=((snapshot or {}).get("sanitary") or {}).get("main_horizontal_segments")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["sanitary.main_horizontal_segments"])
    table=rule["parameters"]["maximum_dfu_by_dn_and_slope_percent"]; missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        dn,slope,load=row.get("dn_mm"),row.get("slope_percent"),row.get("calculated_dfu")
        if not all(_finite(v) for v in (dn,slope,load)) or float(load)<0:
            missing.append(f"sanitary.main_horizontal_segments[{i}].numeric_sizing_inputs"); continue
        selected=table.get(f"{float(dn):g}",{}).get(f"{float(slope):g}")
        if selected is None:
            missing.append(f"sanitary.main_horizontal_segments[{i}].exact_supported_dn_slope_row"); continue
        maximum=float(selected); evidence.append(f"main[{i}] DN{float(dn):g} slope={float(slope):g}% load={float(load):g} max={maximum:g}DFU")
        if float(load)>maximum: errors.append(f"MAIN_HORIZONTAL_CAPACITY_EXCEEDED:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _vent_stack_capacity(rule, snapshot):
    rows=((snapshot or {}).get("vent") or {}).get("stack_sizing_segments")
    if not rows: return _result(rule, INPUT_REQUIRED, missing=["vent.stack_sizing_segments"])
    table=rule["parameters"]["maximum_length_ft_by_waste_in_dfu_and_vent_in"]
    missing=[]; errors=[]; evidence=[]
    for i,row in enumerate(rows):
        waste,load,vent,length=(row.get("waste_diameter_in"),row.get("connected_dfu"),
                                row.get("vent_diameter_in"),row.get("developed_length_ft"))
        if not all(_finite(v) for v in (waste,load,vent,length)) or min(map(float,(waste,load,vent,length)))<=0:
            missing.append(f"vent.stack_sizing_segments[{i}].positive_numeric_source_units"); continue
        selected=table.get(f"{float(waste):g}@{float(load):g}",{}).get(f"{float(vent):g}")
        if selected is None:
            missing.append(f"vent.stack_sizing_segments[{i}].exact_supported_table_row"); continue
        maximum=float(selected); evidence.append(f"vent_stack[{i}] waste={float(waste):g}in DFU={float(load):g} vent={float(vent):g}in length={float(length):g}ft max={maximum:g}ft")
        if float(length)>maximum: errors.append(f"VENT_STACK_LENGTH_EXCEEDED:{i}")
    if missing: return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


VALIDATORS={"trap_minimum_dn":_trap_dn,"horizontal_slope_velocity":_slope_velocity,
            "vent_termination_clearance":_termination,"trap_vent_distance":_trap_vent_distance,
            "fixture_dfu":_fixture_dfu,"branch_stack_dfu_capacity":_branch_stack_capacity,
            "cleanout_inventory":_cleanout,"vent_minimum_size":_vent_minimum_size,
            "main_horizontal_dfu_capacity":_main_horizontal_capacity,
            "vent_stack_dfu_length_capacity":_vent_stack_capacity}


def load_sanitary_vent_rulebook():
    module=load_rulebook_module(SANITARY_ROOT); integrity=validate_rulebook_module(module)
    if integrity["status"]!="PASS": raise ValueError("sanitary/vent Rulebook integrity failed: "+",".join(integrity["errors"]))
    return module


def evaluate_sanitary_vent_rulebook(snapshot):
    module=load_sanitary_vent_rulebook(); results=[VALIDATORS[r["validator"]](r,snapshot) for r in rule_rows(module)]
    status=FAIL if any(r["status"]==FAIL for r in results) else INPUT_REQUIRED if any(r["status"]==INPUT_REQUIRED for r in results) else PASS
    return {"module_id":module["manifest"]["module_id"],"module_version":module["manifest"]["version"],"results":results,"status":status}


def sanitary_vent_design_profile():
    module=load_sanitary_vent_rulebook(); rows={r["validator"]:r for r in rule_rows(module)}
    return {"module_version":module["manifest"]["version"],
            "trap_minimum_dn_mm":rows["trap_minimum_dn"]["parameters"]["minimum_dn_mm"],
            "horizontal_slope":rows["horizontal_slope_velocity"]["parameters"],
            "trap_vent_distance":rows["trap_vent_distance"]["parameters"]["rows"],
            "fixture_dfu":rows["fixture_dfu"]["parameters"]["fixture_dfu"],
            "branch_stack_capacity":rows["branch_stack_dfu_capacity"]["parameters"]["maximum_dfu_by_dn"],
            "main_horizontal_capacity":rows["main_horizontal_dfu_capacity"]["parameters"]["maximum_dfu_by_dn_and_slope_percent"],
            "vent_minimum_size":rows["vent_minimum_size"]["parameters"],
            "vent_stack_capacity":rows["vent_stack_dfu_length_capacity"]["parameters"]["maximum_length_ft_by_waste_in_dfu_and_vent_in"],
            "authority":"M16-1396","source_ids":[f"M16-SV-{i:03d}" for i in range(1,11)]}


def materialize_vent_plan_riser_schedule(doc, result, origin=(0.0, 0.0)):
    """Materialize calculation-bound plan, riser and schedule primitives."""
    msp=doc.modelspace(); ox,oy=map(float,origin)
    layers=("PLANHA-M-VENT-PLAN","PLANHA-M-VENT-RISER","PLANHA-M-VENT-SCHEDULE")
    for layer in layers:
        if layer not in doc.layers: doc.layers.add(layer)
    rows=[]
    for index,route in enumerate(result.get("routes") or []):
        points=route.get("plan_path")
        if not isinstance(points,list) or len(points)<2:
            return {"status":"INPUT_REQUIRED","missing_inputs":[f"{route.get('route_id')}:plan_path"]}
        msp.add_lwpolyline([(ox+float(p[0]),oy+float(p[1])) for p in points],dxfattribs={"layer":layers[0]})
        x=ox+20+index*2; levels=route.get("riser_levels") or []
        if len(levels)<2:return {"status":"INPUT_REQUIRED","missing_inputs":[f"{route.get('route_id')}:riser_levels"]}
        msp.add_line((x,oy+float(levels[0])),(x,oy+float(levels[-1])),dxfattribs={"layer":layers[1]})
        label=f"{route['route_id']} DN{route['selected_vent_dn_mm']:g} {route['calc_id']}"
        msp.add_text(label,dxfattribs={"layer":layers[2],"insert":(ox+30,oy-index*1.5),"height":0.3})
        rows.append(label)
    return {"status":"PASS","plan_entities":len(rows),"riser_entities":len(rows),"schedule_rows":rows}
