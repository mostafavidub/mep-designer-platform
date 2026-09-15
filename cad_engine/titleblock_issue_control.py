"""Data-driven title-block and issue-control authority."""
from __future__ import annotations
from hashlib import sha256
import json, re

CONTRACT="mechanical-titleblock-issue-control/1"
FINAL_STATES={"SUBMISSION_READY","ISSUED_FOR_CONSTRUCTION"}
ALLOWED_STATES={"DRAFT","INTERNAL_REVIEW","INPUT_REQUIRED","COORDINATION","CLIENT_REVIEW","PRE_SUBMISSION",*FINAL_STATES,"VOID"}
FORBIDDEN={"","—","-","N/A","TBD","NONE","UNKNOWN"}
WEIGHTS={
 "schema_complete":8,"source_provenance":5,"project_identity":5,"sheet_identity_unique":6,
 "manifest_layout_parity":6,"title_content_parity":5,"level_system_parity":5,"paper_orientation":4,
 "scale_viewport_parity":6,"safe_zone_and_plot":5,"revision_register":7,"revision_content_diff":5,
 "issue_state_transition":6,"role_separation":5,"approval_signature_binding":6,"package_artifact_parity":6,
 "exact_dxf_reopen":5,"sheet_by_sheet_visual_qa":5,
}
assert len(WEIGHTS)==18 and sum(WEIGHTS.values())==100
REQUIRED=("project_id","project_name","discipline","drawing_title","sheet_code","level_id","paper_size","orientation","scale","revision","issue_status","designed_by","drawn_by","checked_by","approved_by","issue_date","architecture_sha256")

def digest(value):
 raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
 return sha256(raw.encode()).hexdigest()

def _blank(value): return str(value if value is not None else "").strip().upper() in FORBIDDEN

def normalize_titleblock(board, project, issue):
 """Create deterministic sheet metadata; never fabricate professional approval."""
 board=dict(board or {});project=dict(project or {});issue=dict(issue or {})
 row={"project_id":project.get("project_id"),"project_name":project.get("project_name"),
      "discipline":project.get("discipline","MECHANICAL"),"drawing_title":board.get("title"),
      "sheet_code":board.get("code"),"level_id":board.get("level_id"),"paper_size":board.get("paper_size"),
      "orientation":board.get("orientation"),"scale":board.get("scale"),"revision":issue.get("revision"),
      "issue_status":issue.get("issue_status","PRE_SUBMISSION"),"designed_by":issue.get("designed_by","AUTOMATED DESIGN"),
      "drawn_by":issue.get("drawn_by","AUTOMATED CAD"),"checked_by":issue.get("checked_by","NOT CHECKED"),
      "approved_by":issue.get("approved_by","NOT APPROVED"),"issue_date":issue.get("issue_date"),
      "architecture_sha256":project.get("architecture_sha256"),"contract":CONTRACT}
 row["metadata_hash"]=digest(row)
 return row

def evaluate_titleblock_issue_control(context, exact=None):
 context=context or {};exact=exact or {};rows=context.get("titleblocks") or [];manifest=context.get("manifest") or []
 miss={k:[] for k in WEIGHTS};err={k:[] for k in WEIGHTS};codes=[]
 for i,row in enumerate(rows):
  absent=[k for k in REQUIRED if _blank(row.get(k))]
  if absent:miss["schema_complete"].append(f"SHEET[{i}]:"+",".join(absent))
  provenance=row.get("provenance") or {}
  if any(not provenance.get(k) for k in ("source","verified_at","verified_by")):miss["source_provenance"].append(f"SHEET[{i}]:PROVENANCE")
  if _blank(row.get("project_id")) or _blank(row.get("architecture_sha256")):miss["project_identity"].append(f"SHEET[{i}]:PROJECT_IDENTITY")
  code=row.get("sheet_code");codes.append(code)
  if row.get("drawing_title")!=row.get("content_title"):err["title_content_parity"].append(f"{code}:TITLE_CONTENT_MISMATCH")
  if row.get("level_id")!=row.get("content_level_id") or row.get("system")!=row.get("content_system"):err["level_system_parity"].append(f"{code}:LEVEL_SYSTEM_MISMATCH")
  if row.get("paper_size")!=row.get("measured_paper_size") or row.get("orientation")!=row.get("measured_orientation"):err["paper_orientation"].append(f"{code}:PAPER_ORIENTATION_MISMATCH")
  if row.get("scale")!=row.get("measured_scale") or (row.get("scale")=="AS INDICATED" and not row.get("view_scales")):err["scale_viewport_parity"].append(f"{code}:SCALE_MISMATCH")
  plot=row.get("plot_qa") or {}
  if plot.get("status")!="PASS" or plot.get("intrusions") or plot.get("clipped"):err["safe_zone_and_plot"].append(f"{code}:PLOT_QA")
  state=row.get("issue_status")
  if state not in ALLOWED_STATES:err["issue_state_transition"].append(f"{code}:INVALID_ISSUE_STATE")
  if state in FINAL_STATES:
   if any(_blank(row.get(k)) for k in ("checked_by","approved_by")):err["role_separation"].append(f"{code}:FINAL_ROLE_MISSING")
   if not row.get("approval_signature") or row.get("approval_signature",{}).get("artifact_hash")!=context.get("artifact_hash"):err["approval_signature_binding"].append(f"{code}:SIGNATURE_NOT_BOUND")
  elif str(row.get("checked_by","")).upper() not in {"NOT CHECKED","INPUT REQUIRED"} or str(row.get("approved_by","")).upper() not in {"NOT APPROVED","INPUT REQUIRED"}:
   err["role_separation"].append(f"{code}:UNVERIFIED_PRELIMINARY_APPROVAL")
 if len(codes)!=len(set(codes)) or any(_blank(x) for x in codes):err["sheet_identity_unique"].append("DUPLICATE_OR_BLANK_SHEET_CODE")
 mc={r.get("code") for r in manifest};lc=set(context.get("layout_codes") or [])
 if set(codes)!=mc or mc!=lc:err["manifest_layout_parity"].append("TITLEBLOCK_MANIFEST_LAYOUT_MISMATCH")
 revisions=context.get("revision_register") or []
 if not revisions or any(not all(r.get(k) not in (None,"") for k in ("revision","date","description","author","content_hash")) for r in revisions):miss["revision_register"].append("COMPLETE_REVISION_REGISTER")
 diff=context.get("revision_diff") or {}
 if diff.get("changed") is True and diff.get("revision_incremented") is not True or diff.get("changed") is False and diff.get("revision_incremented") is True:err["revision_content_diff"].append("REVISION_CONTENT_DIFF_MISMATCH")
 transition=context.get("issue_transition") or {}
 if transition.get("status")!="PASS" or not transition.get("actor") or not transition.get("timestamp") or not transition.get("evidence"):miss["issue_state_transition"].append("AUDITED_ISSUE_TRANSITION")
 artifacts=context.get("artifacts") or {}
 if set(artifacts)!={"dxf","pdf","manifest","revision_register"} or len(set(artifacts.values()))<4:err["package_artifact_parity"].append("PACKAGE_ARTIFACT_HASH_SET_INVALID")
 expected_hashes=[r.get("metadata_hash") for r in sorted(rows,key=lambda x:str(x.get("sheet_code") or ""))]
 if exact.get("reopened") is not True or exact.get("immutable") is not True or set(exact.get("sheet_codes") or [])!=set(codes) or exact.get("metadata_hashes")!=expected_hashes:err["exact_dxf_reopen"].append("EXACT_TITLEBLOCK_PARITY_FAILED")
 visual=context.get("visual_qa") or {}
 if visual.get("status")!="PASS" or set(visual.get("sheet_codes") or [])!=set(codes) or visual.get("defects"):err["sheet_by_sheet_visual_qa"].append("TITLEBLOCK_VISUAL_QA_FAILED")
 controls=[]
 for name,w in WEIGHTS.items():
  s="FAIL" if err[name] else ("INPUT_REQUIRED" if miss[name] else "PASS")
  controls.append({"id":name,"weight":w,"status":s,"errors":sorted(set(err[name])),"missing_inputs":sorted(set(miss[name]))})
 score=sum(x["weight"] for x in controls if x["status"]=="PASS");status="FAIL" if any(x["status"]=="FAIL" for x in controls) else ("INPUT_REQUIRED" if any(x["status"]=="INPUT_REQUIRED" for x in controls) else "PASS")
 return {"contract":CONTRACT,"status":status,"score":score,"controls":controls,"release_allowed":status=="PASS" and score==100,
         "errors":sorted({e for x in controls for e in x["errors"]}),"missing_inputs":sorted({e for x in controls for e in x["missing_inputs"]}),"evidence_hash":digest({"context":context,"exact":exact})}

def exact_titleblock_evidence(path):
 try:
  import ezdxf
  doc=ezdxf.readfile(str(path));records=[]
  for entity in doc.modelspace():
   try:values=[str(v) for code,v in entity.get_xdata("ENGITOOLS_TITLEBLOCK") if code==1000]
   except Exception:continue
   if values and values[0]=="TITLEBLOCK":records.append(dict(v.split("=",1) for v in values[1:] if "=" in v))
  records.sort(key=lambda x:x.get("sheet_code",""))
  return {"reopened":True,"immutable":True,"sheet_codes":[r.get("sheet_code") for r in records],"metadata_hashes":[r.get("metadata_hash") for r in records],"records":records}
 except Exception as exc:return {"reopened":False,"immutable":False,"sheet_codes":[],"metadata_hashes":[],"error":type(exc).__name__}
