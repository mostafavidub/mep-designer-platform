"""Replayable, non-material human interpretation of existing wall gaps."""
from __future__ import annotations

from hashlib import sha256
import json

SCHEMA="architectural-human-gap-review/1.0"
QUESTION_VERSION="1.0"
ALLOWED_DECISIONS={"DOOR","WINDOW","OPEN_PASSAGE","CONTINUOUS_WALL","UNKNOWN"}


def _hash(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()


def _normalized_geometry(geometry):
    points=[[round(float(x),6),round(float(y),6)] for x,y in geometry]
    return min(points,list(reversed(points)))


def build_review_manifest(*,source_sha256,frame_id,dependency_engine_sha,gaps,walls):
    """Build immutable questions; answers may interpret but never edit geometry."""
    wall_by_id={row["wall_id"]:row for row in walls}
    questions=[]
    for gap in sorted(gaps,key=lambda row:row["gap_id"]):
        geometry=_normalized_geometry(gap["geometry"])
        wall_snapshot=[{"wall_id":wid,"status":wall_by_id.get(wid,{}).get("status"),
                        "representation":wall_by_id.get(wid,{}).get("representation"),
                        "source_handles":wall_by_id.get(wid,{}).get("source_handles") or []}
                       for wid in sorted(gap.get("host_wall_ids") or [])]
        geometry_hash=_hash(geometry)
        evidence={"gap_width":gap.get("gap_width"),"local_wall_thickness":gap.get("local_wall_thickness"),
                  "classification":gap.get("classification"),"status":gap.get("status"),
                  "source_handles":sorted(gap.get("source_handles") or []),
                  "portal_evidence_ids":sorted(gap.get("portal_evidence_ids") or []),
                  "host_walls":wall_snapshot}
        evidence_hash=_hash(evidence)
        identity={"source_sha256":source_sha256,"frame_id":frame_id,"dependency_engine_sha":dependency_engine_sha,
                  "gap_id":gap["gap_id"],"closure_id":gap.get("closure_id"),
                  "host_wall_ids":sorted(gap.get("host_wall_ids") or []),"gap_geometry_hash":geometry_hash,
                  "evidence_hash":evidence_hash,"question_version":QUESTION_VERSION}
        questions.append({**identity,"question_id":"GAPQ-"+_hash(identity)[:16].upper(),
                          "gap_geometry":geometry,"source_handles":evidence["source_handles"],
                          "question":"What is this location in the source drawing?",
                          "allowed_answers":sorted(ALLOWED_DECISIONS),
                          "review_authority":"HUMAN_SOURCE_INTERPRETATION",
                          "review_scope":"TOPOLOGY_CLASSIFICATION_ONLY",
                          "material_geometry":"NONE","wall_authority":"NONE","routing_authority":"NONE",
                          "portal_authority":"NONE","access_authority":"NONE"})
    fingerprint_input={"schema":SCHEMA,"source_sha256":source_sha256,"frame_id":frame_id,
                       "dependency_engine_sha":dependency_engine_sha,"questions":questions}
    return {"schema":SCHEMA,"source_sha256":source_sha256,"frame_id":frame_id,
            "dependency_engine_sha":dependency_engine_sha,"question_version":QUESTION_VERSION,
            "review_fingerprint":_hash(fingerprint_input),"questions":questions,"decisions":[]}


def validate_review_decisions(manifest,current_manifest):
    """Validate each row independently; stale or malformed answers gain no authority."""
    accepted=[];stale=[];rejected=[]
    if manifest.get("schema")!=SCHEMA:
        return {"accepted_review_decisions":[],"stale_review_decisions":[],
                "rejected_review_decisions":[{"reason":"SCHEMA_INVALID"}]}
    current={row["question_id"]:row for row in current_manifest.get("questions") or []}
    seen={}
    identity_keys=("source_sha256","frame_id","dependency_engine_sha","gap_id","closure_id",
                   "host_wall_ids","gap_geometry_hash","evidence_hash","question_version")
    for row in manifest.get("decisions") or []:
        qid=row.get("question_id");answer=row.get("decision")
        if not qid or answer not in ALLOWED_DECISIONS:
            rejected.append({**row,"reason":"DECISION_INVALID"});continue
        if qid in seen and seen[qid]!=answer:
            rejected.append({**row,"reason":"DECISION_CONFLICT"});continue
        seen[qid]=answer;question=current.get(qid)
        if question is None:
            stale.append({**row,"reason":"QUESTION_NOT_CURRENT"});continue
        if any(row.get(key)!=question.get(key) for key in identity_keys):
            stale.append({**row,"reason":"MATERIAL_IDENTITY_CHANGED"});continue
        accepted.append({**row,"review_authority":"HUMAN_SOURCE_INTERPRETATION",
                         "review_scope":"TOPOLOGY_CLASSIFICATION_ONLY"})
    return {"accepted_review_decisions":accepted,"stale_review_decisions":stale,
            "rejected_review_decisions":rejected}
