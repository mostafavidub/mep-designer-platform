"""Three-way reconciliation: Source Dimension ↔ Geometry ↔ Planha Intent."""
from __future__ import annotations
import math


def _pair(row):
    a=str(((row or {}).get("reference_a") or {}).get("reference",{}).get("id") or ((row or {}).get("reference_a") or {}).get("id") or "")
    b=str(((row or {}).get("reference_b") or {}).get("reference",{}).get("id") or ((row or {}).get("reference_b") or {}).get("id") or "")
    return tuple(sorted((a,b)))

def _intent_pair(row):
    a=str(((row or {}).get("reference_a") or {}).get("id") or ((row or {}).get("reference_a") or {}).get("element_id") or "")
    b=str(((row or {}).get("reference_b") or {}).get("id") or ((row or {}).get("reference_b") or {}).get("element_id") or "")
    return tuple(sorted((a,b)))


PROFILE_VISIBLE={
 "ARCHITECTURAL_FLOOR_PLAN":{"PROPERTY","SETBACK","BUILDING_OVERALL","GRID","STRUCTURAL_SET_OUT","WALL_SETOUT","SHAFT","STAIR_CORE","CODE_CLEARANCE","OPENING"},
 "MECHANICAL_PLAN":{"BUILDING_OVERALL","GRID","STRUCTURAL_SET_OUT","SHAFT","STAIR_CORE","CODE_CLEARANCE"},
 "ROOF_PLAN":{"BUILDING_OVERALL","GRID","SHAFT","STAIR_CORE"},
 "PARKING_PLAN":{"BUILDING_OVERALL","GRID","STRUCTURAL_SET_OUT","SHAFT","STAIR_CORE","CODE_CLEARANCE"},
 "DETAIL":set(),
}


SOURCE_ROLE_BY_TYPE={
 "PROPERTY":"CHECK","SETBACK":"SETOUT","BUILDING_OVERALL":"CHECK","GRID":"SETOUT",
 "STRUCTURAL_SET_OUT":"SETOUT","WALL_SETOUT":"SETOUT","SHAFT":"SETOUT",
 "STAIR_CORE":"SETOUT","CODE_CLEARANCE":"CHECK","OPENING":"SETOUT",
}

def _unwrap_source_ref(binding):
    if not isinstance(binding,dict):return None
    ref=binding.get("reference") if isinstance(binding.get("reference"),dict) else binding
    rid=str(ref.get("id") or "")
    if not rid:return None
    return {
      "id":rid,"element_id":str(ref.get("element_id") or rid),
      "subfeature":str(ref.get("subfeature") or ref.get("kind") or "PLAN_EDGE"),
      "priority":int(ref.get("priority",50)),"confidence":float(ref.get("confidence",1.0)),
      "datum_class":ref.get("datum_class"),"source":ref.get("source","source_dimension_binding"),
    }

def source_regeneration_intents(source_registry,profile):
    visible=PROFILE_VISIBLE.get(profile,set());rows=[];review=[]
    for src in (source_registry or {}).get("records") or []:
        stype=src.get("semantic_type")
        if stype not in visible:continue
        if src.get("conflict"):
            if src.get("critical"):review.append({"source_dimension_id":src.get("id"),"reason":src.get("conflict")})
            continue
        if src.get("override_status")=="NON_NUMERIC_OVERRIDE":
            continue
        ra=_unwrap_source_ref(src.get("reference_a"));rb=_unwrap_source_ref(src.get("reference_b"))
        if not ra or not rb:
            if src.get("critical"):review.append({"source_dimension_id":src.get("id"),"reason":"STABLE_SOURCE_REFERENCE_REQUIRED"})
            continue
        p1=src.get("reference_point_a") or src.get("p1");p2=src.get("reference_point_b") or src.get("p2")
        if not p1 or not p2:continue
        rows.append({
          "id":"SRC-"+str(src.get("id")),"purpose":stype,"role":SOURCE_ROLE_BY_TYPE.get(stype,"SETOUT"),
          "drawing_profile":profile,"priority_class":"P0" if src.get("critical") else "P2",
          "required":bool(src.get("critical")),"reference_a":ra,"reference_b":rb,
          "world_p1":tuple(p1),"world_p2":tuple(p2),"world_base":src.get("dimension_line_point"),
          "measured_value":float(src.get("measured_value") or src.get("raw_measurement") or 0.0),
          "engineering_value_m":src.get("measured_value_m"),"display_value":src.get("displayed_value"),
          "source_kind":"SOURCE_REGENERATED","source_dimension_id":src.get("id"),
          "orientation":src.get("source_orientation"),"datum_class":ra.get("datum_class") if ra.get("datum_class")==rb.get("datum_class") else None,
          "axis_deg":src.get("source_angle_deg"),"evidence":("source_dimension_registry","semantic_binding"),
        })
    return {"status":"HUMAN_REVIEW_REQUIRED" if review else "PASS","intents":rows,"human_review":review}


def reconcile_source_dimensions(source_registry,planha_intents,tolerance_m=1e-6,profile=None):
    intents=list(planha_intents or []);rows=[];visible=PROFILE_VISIBLE.get(profile)
    for src in (source_registry or {}).get("records") or []:
        sid=src.get("id");stype=src.get("semantic_type")
        if src.get("conflict"):
            status="CONFLICT"
        elif src.get("override_status")=="NON_NUMERIC_OVERRIDE":
            status="PRESERVED_AS_EVIDENCE"
        elif visible is not None and stype not in visible:
            status="SUPPRESSED_IN_VIEW"
        else:
            explicit=[i for i in intents if str(i.get("source_dimension_id") or "")==str(sid)]
            if explicit:
                sm=src.get("measured_value_m")
                same=any(sm is not None and i.get("engineering_value_m") is not None and abs(float(sm)-float(i["engineering_value_m"]))<=tolerance_m for i in explicit)
                status="REGENERATED" if same else "CONFLICT"
            else:
                pair=_pair(src)
                matches=[i for i in intents if pair!=("","") and _intent_pair(i)==pair]
                if not matches:
                    status="PRESERVED_AS_EVIDENCE" if not src.get("critical") else "UNKNOWN"
                else:
                    sm=src.get("measured_value_m")
                    same=any(sm is not None and i.get("engineering_value_m") is not None and abs(float(sm)-float(i["engineering_value_m"]))<=tolerance_m for i in matches)
                    status="VERIFIED" if same else "CONFLICT"
        rows.append({"source_dimension_id":sid,"semantic_type":stype,"status":status,
                     "critical":bool(src.get("critical")),"source_measurement_m":src.get("measured_value_m"),
                     "source_display_text":src.get("source_display_text"),"reference_pair":_pair(src)})
    human=[r for r in rows if r["critical"] and r["status"] in {"UNKNOWN","CONFLICT"}]
    states=("VERIFIED","REGENERATED","PRESERVED_AS_EVIDENCE","SUPPRESSED_IN_VIEW","CONFLICT","UNKNOWN")
    return {"status":"HUMAN_REVIEW_REQUIRED" if human else "PASS","rows":rows,"human_review":human,
            "counts":{k:sum(1 for r in rows if r["status"]==k) for k in states}}
