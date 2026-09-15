from copy import deepcopy

import ezdxf

from cad_engine.cross_document_reconciliation_gate import reconcile_cross_document_outputs
from cad_engine.mechanical_network_materializer import APPID, _set_identity
from cad_engine.mechanical_segment_execution import design_authoritative_segments


def _complete():
    graph={"graph_id":"G-PRCS","levels":[{"id":"L1","type":"GROUND","name":"Ground"}],
           "nodes":[{"id":"SOURCE"},{"id":"FIXTURE"}],
           "edges":[{"id":"EDGE-1","calc_id":"CALC-1","from":"SOURCE","to":"FIXTURE",
                     "system":"cold_water","levels":["L1"],"endpoint_ids":["FIXTURE"],
                     "draw_on_plan":True,"plan_path":[(0,0),(2,0),(2,2)]}]}
    rows=[{"network_edge_id":"EDGE-1","calc_id":"CALC-1","size_mm":20,"material":"PPR",
           "material_source":"PROJECT_SPEC","requires_slope":False,"downstream_load":1,
           "load_unit":"WSFU"}]
    execution=design_authoritative_segments(graph,calculation_rows=rows)
    assert execution["status"] == "PASS"
    return execution["network"],execution["calculation_rows"]


def _exact(tmp_path,edge):
    path=tmp_path/"issued.dxf";doc=ezdxf.new("R2010");doc.appids.add(APPID)
    entity=doc.modelspace().add_lwpolyline([(0,0),(2,0),(2,2)])
    _set_identity(entity,"NETWORK_SEGMENT",edge);doc.saveas(path);return path


def test_four_projections_have_distinct_stable_ids_and_full_coverage():
    graph,rows=_complete();result=reconcile_cross_document_outputs(graph,rows)
    assert result["status"] == "PASS" and result["score"] == 100
    record=result["registry"]["records"][0];identity=record["identity"]
    assert len({identity["network_edge_id"],identity["calc_id"],identity["plan_representation_id"],
                identity["riser_representation_id"],identity["schedule_row_id"]}) == 5
    assert result["coverage"] == {"edges":1,"calculations":1,"plans":1,"risers":1,"schedules":1,"exact_plans":0}


def test_orphan_duplicate_and_numeric_divergence_fail_closed():
    graph,rows=_complete();bad=deepcopy(rows)
    bad[0]["size_mm"]=25
    bad.append({**bad[0],"calc_id":"CALC-ORPHAN","network_edge_id":"EDGE-X"})
    result=reconcile_cross_document_outputs(graph,bad)
    assert result["status"] == "FAIL"
    assert any(value.startswith("NUMERIC_MISMATCH:EDGE-1:size_mm") for value in result["errors"])
    assert any(value.startswith("ORPHAN_CALCULATIONS:EDGE-X") for value in result["errors"])


def test_exact_dxf_reopen_proves_full_identity_and_numeric_parity(tmp_path):
    graph,rows=_complete();path=_exact(tmp_path,graph["edges"][0])
    result=reconcile_cross_document_outputs(graph,rows,exact_dxf=path,exact_required=True)
    assert result["status"] == "PASS" and result["score"] == 100
    assert result["coverage"]["exact_plans"] == 1


def test_exact_dxf_tamper_or_duplicate_is_blocking(tmp_path):
    graph,rows=_complete();edge=deepcopy(graph["edges"][0]);edge["schedule_row_id"]="TAMPERED"
    path=_exact(tmp_path,edge)
    result=reconcile_cross_document_outputs(graph,rows,exact_dxf=path,exact_required=True)
    assert result["status"] == "FAIL"
    assert "EXACT_IDENTITY_MISMATCH:EDGE-1:schedule_row_id" in result["errors"]
    assert result["checks"]["exact_file_identity"] is False
    assert result["score"] < 100
