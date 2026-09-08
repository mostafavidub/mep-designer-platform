"""Step 8 — fail-closed calculation evidence for project utility inputs.

This module accepts only explicit, finite, positive project pressure evidence.
Benchmark/default/assumed values may remain useful for completeness experiments,
but they can never become final utility-pressure evidence in a released design.
"""
from __future__ import annotations

import math
from typing import Any

from app.mechanical_basis_contract import numeric

VERSION = "calculation-evidence-step8/1"
WATER_PRESSURE_KEYS = (
    "water_inlet_pressure",
    "water_pressure",
    "water_inlet_pressure_bar",
    "utility_water_pressure",
)
ASSUMED_STATUS_TOKENS = ("ASSUM", "DEFAULT", "BENCHMARK", "PLACEHOLDER", "PRELIMINARY")


def _manifest_rows(answers: dict[str, Any]) -> list[dict[str, Any]]:
    raw=(answers or {}).get("_approved_drawing_manifest")
    if isinstance(raw,dict): raw=raw.get("sheets") or raw.get("manifest") or raw.get("approved_manifest") or []
    return [row for row in (raw or []) if isinstance(row,dict)]


def water_scope_required(answers: dict[str, Any]) -> bool:
    """Return True only when the approved workflow explicitly contains water scope."""
    for row in _manifest_rows(answers):
        family=str(row.get("family") or row.get("drawing_family") or row.get("system") or "").strip().upper()
        if family in {"WATER", "WATER_SUPPLY"}: return True
        drawing_type=str(row.get("drawing_type") or row.get("purpose") or "").strip().upper()
        title=" ".join(str(row.get(k) or "") for k in ("title","label","title_fa")).upper()
        if drawing_type=="CALCULATION_SHEET" and "WATER" in title: return True
    return False


def _raw_record(key: str, raw: Any) -> dict[str, Any]:
    status=""; source="project_answer"; value=raw
    if isinstance(raw,dict):
        status=str(raw.get("status") or raw.get("provenance") or "").strip().upper()
        source=str(raw.get("source") or "structured_project_input")
        for candidate in ("value_bar","value","pressure_bar","pressure"):
            if raw.get(candidate) not in (None,"",[]):
                value=raw.get(candidate); break
    assumed=any(token in status for token in ASSUMED_STATUS_TOKENS)
    parsed=numeric(value)
    finite_positive=parsed is not None and math.isfinite(parsed) and parsed>0
    return {"key":key,"raw":raw,"value_bar":parsed,"status":status,"source":source,
            "assumed":assumed,"finite_positive":finite_positive}


def validate_calculation_evidence(answers: dict[str, Any] | None) -> dict[str, Any]:
    """Validate utility pressure provenance before the CAD designer is invoked.

    Missing required project pressure is INPUT_REQUIRED. Explicit invalid,
    contradictory or assumed-as-final pressure is FAIL. If no water scope and no
    pressure answer exists, the contract is NOT_APPLICABLE.
    """
    a=dict(answers or {}); required=water_scope_required(a); records=[]
    for key in WATER_PRESSURE_KEYS:
        raw=a.get(key)
        if raw not in (None,"",[]): records.append(_raw_record(key,raw))
    if not records:
        if required:
            return {"version":VERSION,"status":"INPUT_REQUIRED","required":True,
                    "missing_inputs":["water_inlet_pressure"],"errors":[],"records":[],
                    "policy":"EXPLICIT_PROJECT_PRESSURE_ONLY"}
        return {"version":VERSION,"status":"NOT_APPLICABLE","required":False,
                "missing_inputs":[],"errors":[],"records":[],"policy":"EXPLICIT_PROJECT_PRESSURE_ONLY"}

    errors=[]
    for rec in records:
        if rec["assumed"]:
            errors.append(f"assumed_pressure_not_project_evidence:{rec['key']}")
        elif not rec["finite_positive"]:
            errors.append(f"invalid_project_pressure:{rec['key']}")
    valid=[rec for rec in records if rec["finite_positive"] and not rec["assumed"]]
    if errors:
        return {"version":VERSION,"status":"FAIL","required":required,
                "missing_inputs":[],"errors":sorted(set(errors)),"records":records,
                "policy":"EXPLICIT_PROJECT_PRESSURE_ONLY"}
    values=sorted({round(float(rec["value_bar"]),9) for rec in valid})
    if len(values)>1:
        return {"version":VERSION,"status":"FAIL","required":required,"missing_inputs":[],
                "errors":["conflicting_project_pressure_values:"+",".join(map(str,values))],
                "records":records,"policy":"EXPLICIT_PROJECT_PRESSURE_ONLY"}
    if not valid:
        return {"version":VERSION,"status":"INPUT_REQUIRED","required":required,
                "missing_inputs":["water_inlet_pressure"],"errors":[],"records":records,
                "policy":"EXPLICIT_PROJECT_PRESSURE_ONLY"}
    chosen=valid[0]
    return {"version":VERSION,"status":"PASS","required":required,"missing_inputs":[],"errors":[],
            "records":records,"value_bar":float(chosen["value_bar"]),"source_key":chosen["key"],
            "source":chosen["source"],"provenance":"PROJECT_INPUT",
            "policy":"EXPLICIT_PROJECT_PRESSURE_ONLY"}


def apply_canonical_pressure(answers: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with a canonical numeric pressure only after Step 8 PASS."""
    out=dict(answers or {})
    if evidence.get("status")=="PASS":
        value=float(evidence["value_bar"])
        out["water_inlet_pressure"]=value
        out["water_pressure"]=value
        out["_water_pressure_evidence"]={
            "status":"PROJECT_INPUT","value_bar":value,"source_key":evidence.get("source_key"),
            "source":evidence.get("source"),"contract":VERSION,
        }
    return out
