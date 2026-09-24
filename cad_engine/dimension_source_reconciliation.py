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
