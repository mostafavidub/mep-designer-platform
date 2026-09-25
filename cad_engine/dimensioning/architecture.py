"""Autonomous architectural dimension network orchestration."""
from __future__ import annotations
from copy import deepcopy

from .references import build_semantic_references
from .coordinate_frames import detect_local_coordinate_frames, references_for_frame
from .requirements import build_requirements
from .determinacy import analyze_determinacy
from .placement import assign_dimension_zones
from .profiles import normalize_profile
from .qa import evaluate_architectural_dimension_qa


def _zones(architecture: dict):
    rows=list((architecture or {}).get("zones") or [])
    if rows:
        return [str(row.get("id") or f"ZONE-{i+1}") for i,row in enumerate(rows)]
    return ["ZONE-1"]


def _critical_reference_ids(refs):
    """Construction-critical references that must remain locatable from print."""
    out=[]
    for ref in refs or []:
        kind=str(ref.get("kind") or "").upper()
        sf=str(ref.get("subfeature") or "").upper()
        if kind in {"WALL","SHAFT","LIGHTWELL","STAIR","LANDING","DOOR","WINDOW","OPENING"}:
            out.append(str(ref["id"]))
        elif sf in {"PROPERTY_EDGE"}:
            out.append(str(ref["id"]))
    return sorted(set(out))


def _datum_ids(refs):
    datums=[]
    for ref in refs or []:
        kind=str(ref.get("kind") or "").upper()
        sf=str(ref.get("subfeature") or "").upper()
        md=ref.get("metadata") or {}
        if sf in {"GRID_AXIS","PROPERTY_EDGE"} or kind in {"GRID","PROPERTY","SITE"}:
            datums.append(str(ref["id"]))
        elif kind=="WALL" and md.get("exterior") and sf in {"FINISH_FACE","OUTER_FACE"}:
            # Approved exterior envelope may serve as the architectural set-out
            # origin when no structural grid/site datum exists.
            datums.append(str(ref["id"]))
    return sorted(set(datums))


def _dedupe_intents(intents):
    out=[]; seen={}
    conflicts=[]
    for row in intents or []:
        rid=str(row.get("id") or "")
        if not rid:
            conflicts.append({"reason":"DIMENSION_INTENT_ID_REQUIRED"})
            continue
        if rid in seen:
            prior=seen[rid]
            signature=(row.get("purpose"), row.get("world_p1"), row.get("world_p2"),
                       (row.get("reference_a") or {}).get("id"), (row.get("reference_b") or {}).get("id"))
            prior_sig=(prior.get("purpose"), prior.get("world_p1"), prior.get("world_p2"),
                       (prior.get("reference_a") or {}).get("id"), (prior.get("reference_b") or {}).get("id"))
            if signature != prior_sig:
                conflicts.append({"intent_id":rid,"reason":"DUPLICATE_INTENT_ID_WITH_DIFFERENT_SEMANTICS"})
            continue
        seen[rid]=row; out.append(row)
    return out,conflicts


def build_architectural_dimension_network(
    architecture: dict,
    drawing_profile: str,
    *,
    unit_evidence: dict | None = None,
    code_requirements: list[dict] | None = None,
    source_preservation: dict | None = None,
    exact_file: dict | None = None,
    visual_qa: dict | None = None,
    placement_evidence: dict | None = None,
    stage: str = "PRE_RENDER",
):
    """Build semantic intents first; CAD rendering is deliberately downstream.

    Returns PASS only when the currently evaluable controls pass. PRE_RENDER may
    remain INPUT_REQUIRED for exact-file/visual evidence. FINAL can release only
    after exact-file and visual proof are supplied.
    """
    architecture=deepcopy(architecture or {})
    profile=normalize_profile(drawing_profile)
    all_refs=[]; all_intents=[]; all_frames=[]
    errors=[]; checkpoints=[]; zone_reports=[]

    for zone_id in _zones(architecture):
        ref_report=build_semantic_references(architecture,zone_id=zone_id)
        refs=ref_report["references"]
        all_refs.extend(refs)
        errors.extend(ref_report["errors"])
        checkpoints.extend(ref_report["human_checkpoints"])

        frames=detect_local_coordinate_frames(refs,zone_id=zone_id)
        all_frames.extend(frames)
        if not refs:
            checkpoints.append({"zone_id":zone_id,"reason":"SEMANTIC_REFERENCES_REQUIRED"})
        if not frames:
            checkpoints.append({"zone_id":zone_id,"reason":"LOCAL_COORDINATE_FRAME_REQUIRED"})

        frame_reports=[]
        for frame in frames:
            if frame.get("status")!="PASS":
                checkpoints.append({"zone_id":zone_id,"frame_id":frame.get("id"),"reason":"LOCAL_COORDINATE_FRAME_AMBIGUOUS"})
                continue
            frame_refs=references_for_frame(refs,frame)
            req=build_requirements(
                architecture,frame_refs,frame,profile,zone_id=zone_id,
                code_requirements=code_requirements,
            )
            all_intents.extend(req["intents"])
            errors.extend(req["errors"])
            checkpoints.extend(req["human_checkpoints"])
            frame_reports.append({
                "frame_id":frame["id"],"reference_count":len(frame_refs),
                "intent_count":len(req["intents"]),"sections":req["sections"],
            })
        zone_reports.append({
            "zone_id":zone_id,"reference_status":ref_report["status"],
            "reference_count":len(refs),"frame_count":len(frames),
            "frames":frame_reports,
        })

    intents,dedupe_conflicts=_dedupe_intents(all_intents)
    errors.extend(dedupe_conflicts)
    placement_plan=assign_dimension_zones(intents)
    intents=placement_plan["intents"]

    critical=_critical_reference_ids(all_refs)
    determinacy=analyze_determinacy(
        critical,intents,all_refs,datum_ids=_datum_ids(all_refs)
    )

    ref_report={
        "status":"FAIL" if errors else ("HUMAN_REVIEW" if checkpoints else "PASS"),
        "errors":errors,"human_checkpoints":checkpoints,
    }
    placement=dict(placement_evidence or {})
    placement.setdefault("planned_zone_counts",placement_plan["counts"])

    qa=evaluate_architectural_dimension_qa(
        profile=profile,intents=intents,references=all_refs,
        reference_report=ref_report,frames=all_frames,determinacy=determinacy,
        unit_evidence=unit_evidence,source_preservation=source_preservation,
        exact_file=exact_file,visual_qa=visual_qa,placement=placement,stage=stage,
    )
    # Human checkpoints are a separate fail-closed state even when numeric
    # controls happen to pass.
    status=qa["status"]
    if checkpoints and status=="PASS":
        status="INPUT_REQUIRED"
    if errors:
        status="FAIL"
    return {
        "contract":"architectural-dimension-network/1",
        "profile":profile,"stage":stage,"status":status,
        "references":all_refs,"frames":all_frames,"intents":intents,
        "critical_reference_ids":critical,"determinacy":determinacy,
        "reference_report":ref_report,"placement_plan":placement_plan,
        "zone_reports":zone_reports,"qa":qa,
        "errors":errors,"human_checkpoints":checkpoints,
        "policy":"semantic geometry -> purpose -> references -> determinacy -> chains -> checks -> placement -> renderer -> exact-file QA",
    }
