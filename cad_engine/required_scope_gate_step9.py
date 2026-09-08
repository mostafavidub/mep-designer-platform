"""Step 9 — required mechanical scope completeness.

Explicit septic or fire-water scope must never disappear silently from a
mechanical release. The current production authority engine does not yet issue
those systems, so explicit requirements fail closed before CAD generation.
The exact-file validator remains future-proof defense in depth: text/notes
alone never prove that a required system was actually drawn.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import re

import ezdxf

VERSION = "required-scope-step9/1"
SUPPORTED_RELEASE_SYSTEMS = {
    "WATER", "SANITARY_VENT", "HEATING", "GAS", "SPLIT_AC", "EXHAUST", "ROOF_RAINWATER"
}
TRUE_TOKENS = {"1","true","yes","y","required","on","بله","بلی","دارد","لازم","الزامی"}
FALSE_TOKENS = {"0","false","no","n","not required","off","خیر","نه","ندارد","لازم نیست","غیرالزامی"}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("ي","ی").replace("ك","ک").replace("\u200c"," ")).strip()


def _flag(value: Any) -> bool | None:
    if isinstance(value,bool): return value
    if value in (None,"",[]): return None
    if isinstance(value,(int,float)):
        if value==1: return True
        if value==0: return False
    text=_norm(value).lower()
    if text in TRUE_TOKENS: return True
    if text in FALSE_TOKENS: return False
    return None


def _manifest_rows(answers: dict[str,Any]) -> list[dict[str,Any]]:
    raw=(answers or {}).get("_approved_drawing_manifest")
    if isinstance(raw,dict): raw=raw.get("sheets") or raw.get("manifest") or raw.get("approved_manifest") or []
    return [row for row in (raw or []) if isinstance(row,dict)]


def required_scope(answers: dict[str,Any] | None) -> dict[str,Any]:
    a=dict(answers or {}); required=set(); evidence=[]
    septic_flag=_flag(a.get("septic_required"))
    if septic_flag is True:
        required.add("SEPTIC"); evidence.append({"system":"SEPTIC","source":"septic_required","value":a.get("septic_required")})
    sanitary_text=" ".join(_norm(a.get(k)) for k in ("sanitary_discharge","sewage_disposal","wastewater_disposal","sanitary_disposal")).lower()
    if "septic" in sanitary_text or "سپتیک" in sanitary_text:
        required.add("SEPTIC"); evidence.append({"system":"SEPTIC","source":"sanitary_disposal_basis","value":sanitary_text})

    for key in ("fire_water_required","fire_fighting_required","fire_service_required"):
        if _flag(a.get(key)) is True:
            required.add("FIRE_WATER"); evidence.append({"system":"FIRE_WATER","source":key,"value":a.get(key)})

    for row in _manifest_rows(a):
        family=_norm(row.get("family") or row.get("drawing_family") or row.get("system")).upper().replace("-","_").replace(" ","_")
        title=" ".join(_norm(row.get(k)) for k in ("title","label","title_fa")).upper()
        if family in {"SEPTIC","SEPTIC_SYSTEM","WASTEWATER_SEPTIC"} or "SEPTIC" in title or "سپتیک" in title:
            required.add("SEPTIC"); evidence.append({"system":"SEPTIC","source":"approved_manifest","value":family or title})
        fire_family=family in {"FIRE_WATER","FIRE_FIGHTING","FIRE_PROTECTION","FIRE_SERVICE"}
        fire_title=any(token in title for token in ("FIRE WATER","FIRE PUMP","FIRE TANK","HYDRANT","SPRINKLER"))
        if fire_family or fire_title:
            required.add("FIRE_WATER"); evidence.append({"system":"FIRE_WATER","source":"approved_manifest","value":family or title})
    return {"version":VERSION,"required_systems":sorted(required),"evidence":evidence}


def validate_required_scope_support(answers: dict[str,Any] | None, supported_systems: Iterable[str] | None=None) -> dict[str,Any]:
    scope=required_scope(answers); required=set(scope["required_systems"])
    if not required:
        return {**scope,"status":"NOT_APPLICABLE","unsupported_systems":[],"errors":[],
                "policy":"EXPLICIT_REQUIRED_SCOPE_MUST_BE_SUPPORTED_AND_MATERIALIZED"}
    supported={str(x).upper() for x in (supported_systems if supported_systems is not None else SUPPORTED_RELEASE_SYSTEMS)}
    unsupported=sorted(required-supported)
    errors=[f"required_scope_not_supported:{system}" for system in unsupported]
    return {**scope,"status":"UNSUPPORTED" if unsupported else "PASS","supported_systems":sorted(supported),
            "unsupported_systems":unsupported,"errors":errors,
            "policy":"EXPLICIT_REQUIRED_SCOPE_MUST_BE_SUPPORTED_AND_MATERIALIZED"}


def _text(entity) -> str:
    try:
        if entity.dxftype()=="TEXT": return _norm(entity.dxf.text)
        if entity.dxftype()=="MTEXT": return _norm(entity.plain_text())
    except Exception:
        pass
    return ""


def _is_real_geometry(entity) -> bool:
    return entity.dxftype() in {"LINE","LWPOLYLINE","POLYLINE","ARC","CIRCLE","INSERT","SPLINE","ELLIPSE","HATCH"}


def _layer(entity) -> str:
    return str(getattr(entity.dxf,"layer","") or "").upper()


def _geometry_matches(entity, system: str) -> bool:
    if not _is_real_geometry(entity): return False
    layer=_layer(entity)
    if not layer.startswith("ENGITOOLS-M-"): return False
    if system=="SEPTIC": return "SEPTIC" in layer
    if system=="FIRE_WATER":
        if "FIRE" not in layer: return False
        return any(token in layer for token in ("WATER","PUMP","TANK","HYDRANT","SPRINKLER","HOSE"))
    return False


def _tag_matches(text: str, system: str) -> bool:
    upper=_norm(text).upper()
    if system=="SEPTIC": return "SEPTIC" in upper or "سپتیک" in text
    if system=="FIRE_WATER": return any(token in upper for token in ("FIRE WATER","FIRE PUMP","FIRE TANK","HYDRANT","SPRINKLER","FIRE HOSE"))
    return False


def validate_required_scope_artifact(path: Path | str, answers: dict[str,Any] | None) -> dict[str,Any]:
    """Reopen exact DXF and prove required scope using geometry + readable tags.

    A general note, schedule row, title, or other text-only mention is never
    system materialization evidence.
    """
    scope=required_scope(answers); required=scope["required_systems"]
    if not required:
        return {**scope,"status":"NOT_APPLICABLE","errors":[],"systems":{},"exact_file_reopened":False,
                "policy":"GEOMETRY_PLUS_TAG_REQUIRED_TEXT_ONLY_NEVER_COUNTS"}
    path=Path(path)
    if not path.exists():
        return {**scope,"status":"FAIL","errors":["generated_dxf_missing"],"systems":{},"exact_file_reopened":False,
                "policy":"GEOMETRY_PLUS_TAG_REQUIRED_TEXT_ONLY_NEVER_COUNTS"}
    try:
        doc=ezdxf.readfile(path)
    except Exception as exc:
        return {**scope,"status":"FAIL","errors":[f"exact_dxf_reopen_failed:{exc}"],"systems":{},"exact_file_reopened":False,
                "policy":"GEOMETRY_PLUS_TAG_REQUIRED_TEXT_ONLY_NEVER_COUNTS"}
    msp=doc.modelspace(); entities=list(msp); errors=[]; systems={}
    texts=[_text(e) for e in entities if e.dxftype() in {"TEXT","MTEXT"}]
    for system in required:
        geometry=[e for e in entities if _geometry_matches(e,system)]
        tags=[t for t in texts if _tag_matches(t,system)]
        status="PASS" if geometry and tags else "FAIL"
        if not geometry: errors.append(f"required_scope_geometry_missing:{system}")
        if not tags: errors.append(f"required_scope_tag_missing:{system}")
        systems[system]={"status":status,"geometry_count":len(geometry),"tag_count":len(tags)}
    return {**scope,"status":"PASS" if not errors else "FAIL","errors":sorted(set(errors)),"systems":systems,
            "exact_file_reopened":True,"policy":"GEOMETRY_PLUS_TAG_REQUIRED_TEXT_ONLY_NEVER_COUNTS"}
