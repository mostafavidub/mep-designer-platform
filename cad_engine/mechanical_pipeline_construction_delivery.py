"""Fail-closed construction-document package for Mechanical steps 14-19."""
from __future__ import annotations

from .annotation_solver import solve_annotations


CAD_ENTITY_TYPES={"BLOCK","DIMENSION","HATCH","LEADER","CALLOUT","SECTION_MARKER",
                  "DETAIL_MARKER","EQUIPMENT_SYMBOL","FITTING_SYMBOL","REDUCER_SYMBOL"}
SCHEDULE_FIELDS={"tag","level","room","type","manufacturer","model","capacity","flow",
                 "power","connection_size","status"}


def validate_parametric_detail_register(details, plan_references, manufacturer_database):
    if not details:return {"status":"INPUT_REQUIRED","missing_inputs":["PARAMETRIC_DETAILS"],"details":[]}
    registered={row.get("catalogue_id") for row in (manufacturer_database or {}).get("records") or []}
    references={row.get("detail_id") for row in plan_references or [] if row.get("source_plan_id")}
    errors=[];missing=[];rows=[]
    for result in details:
        detail=(result or {}).get("detail") or {}; detail_id=detail.get("detail_id") or "UNKNOWN"
        if (result or {}).get("status")!="PASS":
            missing.append(f"DETAIL_NOT_FINAL:{detail_id}");continue
        identity=detail.get("identity") or {}
        for key in ("source_plan_id","source_pmm_id","source_calc_id"):
            if not identity.get(key):missing.append(f"{detail_id}:{key}")
        catalogue_id=identity.get("manufacturer_catalogue_id")
        if catalogue_id and catalogue_id not in registered:errors.append(f"{detail_id}:UNKNOWN_CATALOGUE_ID")
        if detail_id not in references:errors.append(f"{detail_id}:NOT_REFERENCED_ON_PLAN")
        if (result.get("qa") or {}).get("label_only") is not False:errors.append(f"{detail_id}:LABEL_ONLY")
        rows.append(detail)
    status="FAIL" if errors else ("INPUT_REQUIRED" if missing else "PASS")
    return {"status":status,"errors":sorted(errors),"missing_inputs":sorted(missing),"details":rows,
            "plan_reference_count":len(references),"policy":"Detail ID -> Plan/PMM/Calc/Catalogue identity"}


def validate_cad_construction_inventory(inventory, required_types):
    required=set(required_types or [])
    unknown=sorted(required-CAD_ENTITY_TYPES)
    if unknown:return {"status":"FAIL","errors":["UNKNOWN_CAD_ENTITY_TYPE:"+",".join(unknown)]}
    if not required:return {"status":"INPUT_REQUIRED","missing_inputs":["REQUIRED_CAD_ENTITY_TYPES"]}
    missing=[];invalid=[]
    for entity_type in sorted(required):
        value=(inventory or {}).get(entity_type)
        if value is None:missing.append(entity_type)
        elif isinstance(value,bool) or not isinstance(value,int) or value<0:invalid.append(entity_type)
        elif value==0:missing.append(entity_type)
    status="FAIL" if invalid else ("INPUT_REQUIRED" if missing else "PASS")
    return {"status":status,"errors":["INVALID_CAD_ENTITY_COUNT:"+x for x in invalid],
            "missing_inputs":["CAD_ENTITY_NOT_MATERIALIZED:"+x for x in missing],
            "inventory":{key:(inventory or {}).get(key) for key in sorted(required)},
            "policy":"Construction entities are scope-driven; reference entity counts are not targets"}


def build_drawing_index(manifest_sheets, dxf_layouts):
    required={"code","title","revision","status"};missing=[];rows=[]
    for index,sheet in enumerate(manifest_sheets or []):
        absent=sorted(key for key in required if not (sheet or {}).get(key))
        missing.extend(f"manifest[{index}].{key}" for key in absent)
        if not absent:rows.append({key:sheet[key] for key in ("code","title","revision","status")})
    if not manifest_sheets:missing.append("MANIFEST_SHEETS")
    if not dxf_layouts:missing.append("DXF_LAYOUTS")
    if missing:return {"status":"INPUT_REQUIRED","missing_inputs":sorted(missing),"rows":rows}
    manifest_codes=[row["code"] for row in rows]; layouts=list(dxf_layouts)
    errors=[]
    if len(manifest_codes)!=len(set(manifest_codes)):errors.append("DUPLICATE_MANIFEST_SHEET")
    if len(layouts)!=len(set(layouts)):errors.append("DUPLICATE_DXF_LAYOUT")
    missing_layouts=sorted(set(manifest_codes)-set(layouts));unindexed=sorted(set(layouts)-set(manifest_codes))
    if missing_layouts:errors.append("MANIFEST_SHEET_WITHOUT_LAYOUT:"+",".join(missing_layouts))
    if unindexed:errors.append("DXF_LAYOUT_WITHOUT_INDEX:"+",".join(unindexed))
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"rows":rows,
            "manifest_count":len(manifest_codes),"index_count":len(rows),"layout_count":len(layouts),
            "identity":"manifest sheets == index sheets == DXF layouts"}


def build_final_equipment_schedule(equipment_rows):
    if not equipment_rows:return {"status":"INPUT_REQUIRED","missing_inputs":["EQUIPMENT_SCHEDULE_ROWS"],"rows":[]}
    rows=[];missing=[];errors=[]
    for index,item in enumerate(equipment_rows):
        absent=sorted(key for key in SCHEDULE_FIELDS if (item or {}).get(key) in (None,""))
        missing.extend(f"equipment[{index}].{key}" for key in absent)
        if absent:continue
        if str(item["level"]).upper().startswith(("PLAN-","LEVEL-ID-")):errors.append(f"{item['tag']}:INTERNAL_LEVEL_EXPOSED")
        if item["status"]!="PASS":errors.append(f"{item['tag']}:STATUS_{item['status']}")
        rows.append({key:item[key] for key in sorted(SCHEDULE_FIELDS)})
    status="FAIL" if errors else ("INPUT_REQUIRED" if missing else "PASS")
    return {"status":status,"errors":sorted(errors),"missing_inputs":sorted(missing),"rows":rows,
            "columns":["Tag","Level","Room","Type","Manufacturer","Model","Capacity","Flow","Power","Connection Size","Status"]}


def build_construction_delivery(payload):
    details=validate_parametric_detail_register(payload.get("details") or [],payload.get("plan_detail_references") or [],
                                                payload.get("manufacturer_database") or {})
    cad=validate_cad_construction_inventory(payload.get("cad_inventory") or {},payload.get("required_cad_entity_types") or [])
    index=build_drawing_index(payload.get("manifest_sheets") or [],payload.get("dxf_layouts") or [])
    schedule=build_final_equipment_schedule(payload.get("equipment_schedule") or [])
    request=payload.get("annotation_solver") or {}
    annotations=solve_annotations(request.get("plan") or {},request.get("requests") or [],request.get("config") or {})
    phases={"parametric_details":details,"cad_materialization":cad,"drawing_index":index,
            "equipment_schedule":schedule,"annotations":annotations}
    failed=[name for name,result in phases.items() if result.get("status")=="FAIL"]
    unresolved=[name for name,result in phases.items() if result.get("status")!="PASS" and name not in failed]
    return {"status":"FAIL" if failed else ("INPUT_REQUIRED" if unresolved else "PASS"),"phases":phases,
            "errors":[f"{name}:{phases[name].get('status')}" for name in failed+unresolved],
            "release_allowed":not failed and not unresolved}
