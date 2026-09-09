"""Provenance-locked manufacturer catalogue and calculation-driven selector."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import math


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


def _official_record(record: dict, required: set[str]) -> tuple[list[str], list[str]]:
    missing = sorted(required - set(record))
    sheet = record.get("datasheet") or {}
    missing += [f"datasheet.{key}" for key in ("official_url", "revision", "sha256") if not sheet.get(key)]
    errors = []
    if sheet.get("sha256") and len(sheet["sha256"]) != 64: errors.append("datasheet.sha256")
    return sorted(set(missing)), errors


def select_radiators(room_loads: list[dict], catalogue: list[dict], design_temperatures: dict) -> dict:
    required_temps = {"supply_c", "return_c", "room_c"}
    if required_temps - set(design_temperatures or {}):
        return {"status":"INPUT_REQUIRED","missing_inputs":sorted(required_temps-set(design_temperatures or {})),"radiators":[]}
    required = {"manufacturer","model","output_w_per_section","height_mm","depth_mm","section_width_mm",
                "rated_supply_c","rated_return_c","rated_room_c","datasheet"}
    valid=[]; rejected=[]
    for record in catalogue or []:
        missing,errors=_official_record(record,required)
        if missing or errors:
            rejected.append({"model":record.get("model"),"status":"INPUT_REQUIRED" if missing else "FAIL",
                             "errors":missing+errors})
        elif any(float(record[f"rated_{key}"])!=float(design_temperatures[key])
                 for key in ("supply_c","return_c","room_c")):
            rejected.append({"model":record.get("model"),"status":"FAIL","errors":["design_temperature_mismatch"]})
        else: valid.append(record)
    if not valid:
        return {"status":"INPUT_REQUIRED","missing_inputs":["OFFICIAL_RADIATOR_AT_DESIGN_TEMPERATURES"],
                "radiators":[],"evaluations":rejected}
    rows=[]
    for room in room_loads or []:
        required_room={"room_id","pmm_id","calc_id","heating_w"}
        if required_room-set(room):
            return {"status":"INPUT_REQUIRED","missing_inputs":sorted(required_room-set(room)),"radiators":[]}
        if float(room["heating_w"]) <= 0:
            return {"status":"FAIL","errors":[f"{room['room_id']}:NON_POSITIVE_HEAT_LOSS"],"radiators":[]}
        candidates=[]
        for record in valid:
            sections=math.ceil(float(room["heating_w"])/float(record["output_w_per_section"]))
            candidates.append((sections*float(record["output_w_per_section"]),record["manufacturer"],record["model"],sections,record))
        _,_,_,sections,chosen=min(candidates)
        rows.append({"radiator_id":room.get("radiator_id") or f"RAD-{room['room_id']}","room_id":room["room_id"],
                     "required_output_w":float(room["heating_w"]),"manufacturer":chosen["manufacturer"],"model":chosen["model"],
                     "sections":sections,"selected_output_w":sections*float(chosen["output_w_per_section"]),
                     "selection_margin_percent":round((sections*float(chosen["output_w_per_section"])/float(room["heating_w"])-1)*100,2),
                     "dimensions_mm":{"width":sections*float(chosen["section_width_mm"]),"height":chosen["height_mm"],"depth":chosen["depth_mm"]},
                     "room_calc_id":room["calc_id"],"source_pmm_ids":[room["pmm_id"]],
                     "design_water_temperatures_c":{"supply":float(design_temperatures["supply_c"]),
                                                    "return":float(design_temperatures["return_c"]),
                                                    "room":float(design_temperatures["room_c"])},
                     "datasheet":chosen["datasheet"],"selection_type":"MANUFACTURER_MODEL","status":"PASS"})
    return {"status":"PASS","radiators":rows,"evaluations":rejected,"claim":"MANUFACTURER_CONFIRMED"}


def select_package(requirements: dict, catalogue: list[dict]) -> dict:
    required_inputs={"space_heating_kw","dhw_kw","simultaneous_factor"}
    missing=sorted(required_inputs-set(requirements or {}))
    if missing: return {"status":"INPUT_REQUIRED","missing_inputs":missing,"selection":None}
    design_combined=float(requirements["space_heating_kw"])+float(requirements["dhw_kw"])*float(requirements["simultaneous_factor"])
    required={"manufacturer","model","space_heating_capacity_kw","dhw_capacity_kw","combined_capacity_kw",
              "gas_consumption_m3h","dimensions_mm","connections","datasheet"}
    passing=[]; evaluations=[]
    for record in catalogue or []:
        absent,errors=_official_record(record,required)
        if absent or errors:
            evaluations.append({"model":record.get("model"),"status":"INPUT_REQUIRED" if absent else "FAIL","errors":absent+errors}); continue
        failures=[]
        if float(record["space_heating_capacity_kw"])<float(requirements["space_heating_kw"]): failures.append("space_heating")
        if float(record["dhw_capacity_kw"])<float(requirements["dhw_kw"]): failures.append("dhw")
        if float(record["combined_capacity_kw"])<design_combined: failures.append("combined")
        evaluations.append({"model":record["model"],"status":"FAIL" if failures else "PASS","errors":failures})
        if not failures: passing.append(record)
    if not passing:
        return {"status":"INPUT_REQUIRED","missing_inputs":["COMPLIANT_OFFICIAL_PACKAGE"],"selection":None,"evaluations":evaluations}
    chosen=min(passing,key=lambda x:(float(x["combined_capacity_kw"]),x["manufacturer"],x["model"]))
    return {"status":"PASS","selection":{**chosen,"design_combined_kw":round(design_combined,3)},
            "evaluations":evaluations,"claim":"MANUFACTURER_CONFIRMED"}


def select_split_system(cooling_design: dict, idu_catalogue: list[dict], odu_catalogue: list[dict], routes: list[dict], odu_site: dict | None = None) -> dict:
    """Select exact IDUs and a compatible ODU after route and condensate checks."""
    if cooling_design.get('status')!='PASS':
        return {'status':'INPUT_REQUIRED','missing_inputs':['PASS_COOLING_DESIGN'],'idus':[],'odu':None}
    idu_required={'manufacturer','model','capacity_btu_h','airflow_cfm','liquid_size_mm','gas_size_mm',
                  'max_pipe_length_m','max_elevation_m','service_clearance_mm','datasheet'}
    odu_required={'manufacturer','model','nominal_capacity_btu_h','airflow_cfm','min_connected_ratio','max_connected_ratio',
                  'max_total_pipe_length_m','max_elevation_m','service_clearance_mm','datasheet'}
    valid_idus=[]; valid_odus=[]; missing=[]; evaluations=[]
    for record in idu_catalogue or []:
        absent,errors=_official_record(record,idu_required)
        if absent or errors:evaluations.append({'type':'IDU','model':record.get('model'),'errors':absent+errors})
        else:valid_idus.append(record)
    for record in odu_catalogue or []:
        absent,errors=_official_record(record,odu_required)
        if absent or errors:evaluations.append({'type':'ODU','model':record.get('model'),'errors':absent+errors})
        else:valid_odus.append(record)
    if not valid_idus:missing.append('OFFICIAL_IDU_CATALOGUE')
    if not valid_odus:missing.append('OFFICIAL_ODU_CATALOGUE')
    site=odu_site or {}
    if 'service_clearance_mm' not in site:missing.append('odu_site:service_clearance_mm')
    duties=[]
    if cooling_design.get('rooms'):
        duties=[{'selection_id':row['room_id'],'room_id':row['room_id'],'zone_id':row['zone_id'],
                 'design_load_btu_h':row['calculated_load_btu_h'],'calc_id':row.get('calc_id'),
                 'source_pmm_ids':row.get('source_pmm_ids') or ([row['pmm_id']] if row.get('pmm_id') else [])}
                for row in cooling_design['rooms']]
    else:
        duties=[{'selection_id':row['zone_id'],'room_id':None,'zone_id':row['zone_id'],
                 'design_load_btu_h':row['design_load_btu_h'],'calc_id':row.get('calc_id'),
                 'source_pmm_ids':row.get('source_pmm_ids') or []} for row in cooling_design.get('zones') or []]
    route_by_id={(row.get('room_id') or row.get('zone_id')):row for row in routes or []}; selections=[]
    for duty in duties:
        selection_id=duty['selection_id']; route=route_by_id.get(selection_id)
        if not route:missing.append(f"route:{selection_id}");continue
        for key in ('length_m','elevation_m','condensate_drain','service_clearance_mm'):
            if key not in route:missing.append(f"route:{selection_id}:{key}")
        candidates=[r for r in valid_idus if float(r['capacity_btu_h'])>=float(duty['design_load_btu_h'])]
        candidates=[r for r in candidates if float(route.get('length_m',1e99))<=float(r['max_pipe_length_m'])
                    and float(route.get('elevation_m',1e99))<=float(r['max_elevation_m'])
                    and route.get('condensate_drain') is True
                    and float(route.get('service_clearance_mm',0))>=float(r['service_clearance_mm'])]
        if not candidates:missing.append(f"COMPLIANT_IDU:{selection_id}");continue
        chosen=min(candidates,key=lambda r:(float(r['capacity_btu_h']),r['manufacturer'],r['model']))
        selections.append({'idu_id':f"IDU-{selection_id}",'room_id':duty['room_id'],'zone_id':duty['zone_id'],
          'calculated_load_btu_h':duty['design_load_btu_h'],
          'selected_capacity_btu_h':float(chosen['capacity_btu_h']),
          'selection_margin_percent':round((float(chosen['capacity_btu_h'])/float(duty['design_load_btu_h'])-1)*100,2),
          'manufacturer':chosen['manufacturer'],'model':chosen['model'],'airflow_cfm':float(chosen['airflow_cfm']),
          'liquid_size_mm':float(chosen['liquid_size_mm']),'gas_size_mm':float(chosen['gas_size_mm']),
          'route_length_m':float(route['length_m']),'elevation_m':float(route['elevation_m']),
          'condensate_drain':True,'calc_id':duty['calc_id'],'source_pmm_ids':duty['source_pmm_ids'],
          'datasheet':chosen['datasheet'],'selection_type':'MANUFACTURER_MODEL','status':'PASS'})
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'idus':selections,'odu':None,
                       'evaluations':evaluations}
    connected=sum(row['selected_capacity_btu_h'] for row in selections)
    odu_candidates=[]
    for record in valid_odus:
        ratio=connected/float(record['nominal_capacity_btu_h'])
        if (float(record['min_connected_ratio'])<=ratio<=float(record['max_connected_ratio'])
            and sum(row['route_length_m'] for row in selections)<=float(record['max_total_pipe_length_m'])
            and max((row['elevation_m'] for row in selections),default=0)<=float(record['max_elevation_m'])
            and float(site.get('service_clearance_mm',0))>=float(record['service_clearance_mm'])):
            odu_candidates.append((float(record['nominal_capacity_btu_h']),record,ratio))
    if not odu_candidates:return {'status':'INPUT_REQUIRED','missing_inputs':['COMPLIANT_ODU'],'idus':selections,'odu':None}
    _,odu,ratio=min(odu_candidates,key=lambda x:(x[0],x[1]['manufacturer'],x[1]['model']))
    return {'status':'PASS','idus':selections,'odu':{**odu,'connected_capacity_btu_h':connected,
            'connected_ratio':round(ratio,4)},'claim':'MANUFACTURER_CONFIRMED'}


def select_exhaust_fans(exhaust_design: dict, catalogue: list[dict]) -> dict:
    if exhaust_design.get('status')!='PASS':
        return {'status':'INPUT_REQUIRED','missing_inputs':['PASS_EXHAUST_DESIGN'],'fans':[],'unserved_room_ids':[]}
    required={'manufacturer','model','airflow_cfm','esp_pa','dimensions_mm','sound_db','service_clearance_mm','datasheet'}
    valid=[];evaluations=[]
    for record in catalogue or []:
        absent,errors=_official_record(record,required)
        if absent or errors:evaluations.append({'model':record.get('model'),'errors':absent+errors})
        else:valid.append(record)
    if not valid:return {'status':'INPUT_REQUIRED','missing_inputs':['OFFICIAL_EXHAUST_FAN_CATALOGUE'],
                         'fans':[],'unserved_room_ids':[],'evaluations':evaluations}
    fans=[];unserved=[]
    for room in exhaust_design.get('rooms') or []:
        candidates=[r for r in valid if float(r['airflow_cfm'])>=float(room['required_cfm']) and
                    float(r['esp_pa'])>=float(room['required_esp_pa'])]
        if not candidates:unserved.append(room['room_id']);continue
        chosen=min(candidates,key=lambda r:(float(r['airflow_cfm']),float(r['esp_pa']),r['manufacturer'],r['model']))
        fans.append({'room_id':room['room_id'],'required_cfm':room['required_cfm'],'required_esp_pa':room['required_esp_pa'],
                     'manufacturer':chosen['manufacturer'],'model':chosen['model'],'selected_cfm':float(chosen['airflow_cfm']),
                     'selected_esp_pa':float(chosen['esp_pa']),'calc_id':room['calc_id'],'datasheet':chosen['datasheet'],'status':'PASS'})
    return {'status':'PASS' if not unserved else 'FAIL','fans':fans,'unserved_room_ids':sorted(unserved),
            'errors':[f'UNSERVED_EXHAUST_ROOM:{x}' for x in sorted(unserved)]}
