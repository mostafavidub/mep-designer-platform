from copy import deepcopy
import ezdxf

from cad_engine.mechanical_design_core import _boards, _draw_titleblock
from cad_engine.mechanical_release_hardening import validate_titleblocks
from cad_engine.titleblock_issue_control import evaluate_titleblock_issue_control, exact_titleblock_evidence

HASH="a"*64

def context():
 row={"project_id":"PRJ-1","project_name":"Test","discipline":"MECHANICAL","drawing_title":"WATER PLAN","content_title":"WATER PLAN","sheet_code":"M-111","level_id":"L1","content_level_id":"L1","system":"WATER","content_system":"WATER","paper_size":"A4","measured_paper_size":"A4","orientation":"PORTRAIT","measured_orientation":"PORTRAIT","scale":"1:100","measured_scale":"1:100","revision":"1","issue_status":"SUBMISSION_READY","designed_by":"D-1","drawn_by":"C-1","checked_by":"CHK-1","approved_by":"APP-1","issue_date":"2026-09-15","architecture_sha256":HASH,"provenance":{"source":"PROJECT","verified_at":"2026-09-15T12:00:00Z","verified_by":"SYS"},"plot_qa":{"status":"PASS","intrusions":[],"clipped":False},"approval_signature":{"artifact_hash":"z"*64}}
 from cad_engine.titleblock_issue_control import digest
 row["metadata_hash"]=digest({k:v for k,v in row.items() if k!="metadata_hash"})
 return {"titleblocks":[row],"manifest":[{"code":"M-111"}],"layout_codes":["M-111"],"artifact_hash":"z"*64,"revision_register":[{"revision":"1","date":"2026-09-15","description":"Issue","author":"D-1","content_hash":"b"*64}],"revision_diff":{"changed":True,"revision_incremented":True},"issue_transition":{"status":"PASS","actor":"APP-1","timestamp":"2026-09-15T12:00:00Z","evidence":"SIGNATURE"},"artifacts":{"dxf":"1","pdf":"2","manifest":"3","revision_register":"4"},"visual_qa":{"status":"PASS","sheet_codes":["M-111"],"defects":[]}}

def exact(c):return {"reopened":True,"immutable":True,"sheet_codes":["M-111"],"metadata_hashes":[c["titleblocks"][0]["metadata_hash"]]}

def test_complete_signed_issue_scores_exactly_100():
 c=context();r=evaluate_titleblock_issue_control(c,exact(c));assert r["status"]=="PASS" and r["score"]==100 and r["release_allowed"]

def test_final_without_real_checker_signature_is_blocked():
 c=context();c["titleblocks"][0]["checked_by"]="—";c["titleblocks"][0]["approval_signature"]={}
 r=evaluate_titleblock_issue_control(c,exact(c));assert r["status"]=="FAIL" and not r["release_allowed"]

def test_scale_title_and_manifest_tampering_are_detected():
 c=context();c["titleblocks"][0]["measured_scale"]="1:50";c["titleblocks"][0]["content_title"]="GAS PLAN";c["layout_codes"]=["M-999"]
 r=evaluate_titleblock_issue_control(c,exact(c));assert "M-111:SCALE_MISMATCH" in r["errors"] and "TITLEBLOCK_MANIFEST_LAYOUT_MISMATCH" in r["errors"]

def test_revision_without_content_change_is_blocked():
 c=context();c["revision_diff"]={"changed":False,"revision_incremented":True}
 assert "REVISION_CONTENT_DIFF_MISMATCH" in evaluate_titleblock_issue_control(c,exact(c))["errors"]

def test_generated_titleblock_has_truthful_metadata_and_exact_reopen(tmp_path):
 row={"old_sheet":"S1","code":"M-111","family":"WATER","level":"GROUND","title_fa":"WATER PLAN"};board=_boards([row])["S1"]
 doc=ezdxf.new("R2010");_draw_titleblock(doc,doc.modelspace(),board,"Project",issue={"revision":3,"issue_status":"PRE_SUBMISSION"})
 path=tmp_path/"issued.dxf";doc.saveas(path);e=exact_titleblock_evidence(path)
 assert e["sheet_codes"]==["M-111"] and e["records"][0]["checked_by"]=="NOT CHECKED" and e["records"][0]["revision"]=="3"
 result=validate_titleblocks(path,{"boards":{"S1":vars(board)},"manifest":[row]});assert result["status"]=="PASS",result

def test_exact_metadata_removal_fails_existing_titleblock_gate(tmp_path):
 row={"old_sheet":"S1","code":"M-111","family":"WATER","level":"GROUND","title_fa":"WATER PLAN"};board=_boards([row])["S1"]
 doc=ezdxf.new("R2010");_draw_titleblock(doc,doc.modelspace(),board);path=tmp_path/"issued.dxf";doc.saveas(path)
 doc=ezdxf.readfile(path)
 for e in doc.modelspace():
  try:e.discard_xdata("ENGITOOLS_TITLEBLOCK")
  except Exception:pass
 doc.saveas(path)
 assert validate_titleblocks(path,{"boards":{"S1":vars(board)},"manifest":[row]})["status"]=="FAIL"
