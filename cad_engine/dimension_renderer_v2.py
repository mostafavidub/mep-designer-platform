"""Planha-owned Dimension Engine v2 CAD renderer and exact-file identity check."""
from __future__ import annotations
import math
import ezdxf

APPID_V2="PLANHA_DIMENSION_V2"
LAYER_V2="PLANHA-DIM-V2"


def _ensure(doc):
    if LAYER_V2 not in doc.layers:doc.layers.add(LAYER_V2,color=2)
    try:doc.appids.get(APPID_V2)
    except Exception:doc.appids.add(APPID_V2)
    if "PLANHA-DIM-V2" not in doc.dimstyles:
        doc.dimstyles.new("PLANHA-DIM-V2",dxfattribs={"dimtxt":.08,"dimasz":.06,"dimexo":.02,"dimexe":.04,"dimgap":.03})


def materialize_v2_intents(doc,msp,placed_intents):
    _ensure(doc);rows=[]
    for row in placed_intents or []:
        try:
            dim=msp.add_linear_dim(base=row["render_base"],p1=row["render_p1"],p2=row["render_p2"],
                angle=float(row.get("axis_deg",0.0)),text=str(row.get("display_value") or ""),
                dimstyle="PLANHA-DIM-V2",dxfattribs={"layer":LAYER_V2})
            entity=dim.dimension
            ra=str((row.get("reference_a") or {}).get("id") or (row.get("reference_a") or {}).get("element_id") or "")
            rb=str((row.get("reference_b") or {}).get("id") or (row.get("reference_b") or {}).get("element_id") or "")
            trace=[(1000,"SEMANTIC_DIMENSION_V2"),(1000,str(row.get("id"))),(1000,str(row.get("purpose"))),
                   (1000,str(row.get("role"))),(1000,ra),(1000,rb),(1000,str(row.get("rule_id") or "")),
                   (1000,str(row.get("datum_class") or "")),(1040,float(row.get("measured_value") or 0.0))]
            if row.get("engineering_value_m") is not None:trace.append((1040,float(row["engineering_value_m"])))
            entity.set_xdata(APPID_V2,trace);dim.render()
            rows.append({"intent_id":row.get("id"),"handle":str(getattr(entity.dxf,"handle","") or ""),"reference_a_id":ra,
                         "reference_b_id":rb,"purpose":row.get("purpose"),"role":row.get("role"),
                         "measured_value":float(row.get("measured_value") or 0.0),"engineering_value_m":row.get("engineering_value_m")})
        except Exception as exc:
            rows.append({"intent_id":row.get("id"),"error":"RENDER_FAILURE:"+str(exc)})
    return rows


def validate_v2_exact_file(path,materialized):
    doc=ezdxf.readfile(path);by_handle={str(getattr(e.dxf,"handle","") or ""):e for e in doc.modelspace().query("DIMENSION")}
    errors=[]
    for row in materialized or []:
        if row.get("error"):errors.append(row["error"]);continue
        e=by_handle.get(row.get("handle"))
        if e is None:errors.append("V2_DIMENSION_MISSING:"+str(row.get("intent_id")));continue
        try:data=e.get_xdata(APPID_V2)
        except Exception:data=[]
        strings=[v for code,v in data if code==1000];doubles=[float(v) for code,v in data if code==1040]
        if len(strings)<8 or strings[0]!="SEMANTIC_DIMENSION_V2" or strings[1]!=str(row.get("intent_id")):
            errors.append("V2_TRACEABILITY_MISSING:"+str(row.get("intent_id")));continue
        if strings[4]!=str(row.get("reference_a_id")) or strings[5]!=str(row.get("reference_b_id")):
            errors.append("V2_REFERENCE_CHANGED:"+str(row.get("intent_id")))
        if not doubles or abs(doubles[0]-float(row.get("measured_value") or 0.0))>1e-9:
            errors.append("V2_MEASUREMENT_CHANGED:"+str(row.get("intent_id")))
        ev=row.get("engineering_value_m")
        if ev is not None and (len(doubles)<2 or abs(doubles[1]-float(ev))>1e-9):
            errors.append("V2_ENGINEERING_VALUE_CHANGED:"+str(row.get("intent_id")))
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"exact_file_reopened":True,
            "checked":len(materialized or [])}
