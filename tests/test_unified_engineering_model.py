from copy import deepcopy
import json
from pathlib import Path

from cad_engine.unified_engineering_model import build_unified_engineering_model
from cad_engine.reference_parity_engine import ProjectContext, build_documentation_package, canonical_system


def fixture():
    pmm={"rooms":[{"id":"R-1","level":"GROUND","type":"bath","bounds":[0,0,3,3]}]}
    graph={"graph_id":"G-1","levels":[{"id":"L-1","name":"GROUND","type":"GROUND"}],
           "nodes":[{"id":"F-1"},{"id":"S-1"}],
           "edges":[{"id":"E-1","from":"F-1","to":"S-1","system":"sanitary",
                     "role":"floor_main","levels":["L-1"],"endpoint_ids":["F-1"],
                     "calc_id":"C-1","plan_id":"C-1","riser_id":"C-1","schedule_id":"C-1"}]}
    rows=[{"calc_id":"C-1","network_edge_id":"E-1","system":"sanitary","size_mm":63,
           "material":"uPVC","slope_percent":2,"downstream_load":1,"load_unit":"FU",
           "source":"EXPLICIT_SYSTEM_DESIGN_BASIS"}]
    return pmm,graph,rows


def test_one_model_drives_nonzero_plan_riser_schedule_branches():
    pmm,graph,rows=fixture(); model=build_unified_engineering_model(pmm,graph,rows,{"drawing_unit_to_m":1})
    assert model["status"] == "PASS"
    assert model["totals"]["branches"] == 1
    assert model["branch_counts"] == {"sanitary":1}
    context=ProjectContext(levels=["GROUND"],active_systems=["SANITARY_VENT"],
                           network_graph=graph,calculation_rows=rows,unified_engineering_model=model)
    package=build_documentation_package(context)
    assert package["status"] == "PASS"
    assert package["riser"]["reconciliation"]["expected_branch_count"] == 1
    assert package["riser"]["reconciliation"]["mapped_branch_count"] == 1
    assert package["riser"]["graph"]["authority"] == "UNIFIED_ENGINEERING_MODEL"
    assert package["calculations"]["authority"] == "UNIFIED_ENGINEERING_MODEL"


def test_non_vertical_system_only_package_is_not_a_false_riser_failure():
    pmm,graph,rows=fixture()
    graph["edges"][0].update({"system":"exhaust_ventilation","role":"equipment_branch"})
    rows[0]["system"]="exhaust_ventilation"
    model=build_unified_engineering_model(pmm,graph,rows)
    context=ProjectContext(levels=["GROUND"],active_systems=["EXHAUST"],network_graph=graph,
                           calculation_rows=rows,unified_engineering_model=model)
    package=build_documentation_package(context)
    assert package["status"] == "PASS"
    assert package["riser"]["reconciliation"]["expected_branch_count"] == 0


def test_overlapping_system_names_use_the_most_specific_family():
    assert canonical_system("exhaust_ventilation") == "EXHAUST"
    assert canonical_system("roof_rainwater") == "RAINWATER"
    assert canonical_system("cold_water") == "WATER"


def test_identity_divergence_fails_closed():
    pmm,graph,rows=fixture(); graph=deepcopy(graph);graph["edges"][0]["riser_id"]="OTHER"
    result=build_unified_engineering_model(pmm,graph,rows)
    assert result["status"] == "FAIL"
    assert "OUTPUT_IDENTITY_DIVERGENCE:E-1" in result["errors"]


def test_connected_endpoints_without_plan_branch_fails_closed():
    pmm,graph,rows=fixture(); graph=deepcopy(graph);graph["edges"][0]["role"]="vertical_riser"
    result=build_unified_engineering_model(pmm,graph,rows)
    assert result["status"] == "FAIL"
    assert "ZERO_PLAN_BRANCHES_WITH_CONNECTED_ENDPOINTS" in result["errors"]


def test_orphan_calculation_fails_closed():
    pmm,graph,rows=fixture();rows=rows+[{"calc_id":"C-X","network_edge_id":"E-X","source":"PROJECT_INPUT"}]
    result=build_unified_engineering_model(pmm,graph,rows)
    assert result["status"] == "FAIL"
    assert any(value.startswith("ORPHAN_CALCULATIONS:") for value in result["errors"])


def test_golden_unified_model_contract():
    golden=json.loads((Path(__file__).parents[1]/"standards/golden/unified-engineering-model-1.json").read_text())
    pmm,graph,rows=fixture(); model=build_unified_engineering_model(pmm,graph,rows)
    context=ProjectContext(levels=["GROUND"],active_systems=["SANITARY_VENT"],network_graph=graph,
                           calculation_rows=rows,unified_engineering_model=model)
    package=build_documentation_package(context)
    assert model["status"] == golden["required"]["status"]
    assert model["totals"]["branches"] >= golden["required"]["branches_min"]
    assert package["riser"]["graph"]["authority"] == "UNIFIED_ENGINEERING_MODEL"
    assert not set(golden["forbidden"]) & set(model["errors"])
