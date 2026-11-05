from app.engineering_overlay_materializer import build_engineering_proposal, materialize_engineering_overlay


def test_source_bound_endpoint_materializes_and_systems_fail_independently():
    sha="a"*64
    architecture={"spaces":[{"physical_space_id":"R1","polygon":[[0,0],[10,0],[10,10],[0,10],[0,0]]}]}
    proposal={"source_sha256":sha,"ambiguity_ids":["A1"],"endpoints":[{
        "id":"E1","type":"sink","room_id":"R1","point":[2,2],"source_sha256":sha}],
        "water_design_basis":{"probable_flow_curve":[]}}
    result=materialize_engineering_overlay(source_sha256=sha,architecture=architecture,proposal=proposal)
    assert result["status"]=="MATERIALIZED_DRAFT"
    assert result["overlay"]["release_allowed"] is False
    assert result["systems"]["water"]["status"]=="READY_FOR_CALCULATION"
    assert result["systems"]["gas"]["status"]=="BLOCKED_INPUT"


def test_geometry_and_source_mismatch_fail_closed():
    sha="a"*64; architecture={"spaces":[{"physical_space_id":"R1","polygon":[[0,0],[1,0],[1,1],[0,1],[0,0]]}]}
    bad=materialize_engineering_overlay(source_sha256=sha,architecture=architecture,proposal={
        "source_sha256":sha,"endpoints":[{"id":"E1","room_id":"R1","point":[2,2],"source_sha256":sha}]})
    assert bad["status"]=="INPUT_REQUIRED" and bad["overlay"]["fixture_endpoints"]==[]
    assert materialize_engineering_overlay(source_sha256=sha,architecture=architecture,
        proposal={"source_sha256":"b"*64})["errors"]==["PROPOSAL_SOURCE_MISMATCH"]


def test_generic_builder_hosts_reversible_endpoints_and_runs_canonical_load_engine():
    sha="c"*64
    architecture={"physical_spaces":[{"physical_space_id":"S-K",
        "polygon":[[0,0],[5,0],[5,4],[0,4]],"centroid":[2,2],"area_m2":20}],
        "functional_zones":[{"physical_space_id":"S-K","category":"kitchen"}],
        "shafts":[{"shaft_id":"SH-1","centroid":[.5,.5],"source_handles":["A1"]}]}
    proposal=build_engineering_proposal(source_sha256=sha,architecture=architecture,
                                         ambiguity_ids=["A-1"],answers={})
    assert proposal["new_design_proposals"]
    assert all(row["source_fact"] is False for row in proposal["new_design_proposals"])
    result=materialize_engineering_overlay(source_sha256=sha,architecture=architecture,proposal=proposal)
    assert result["status"]=="MATERIALIZED_DRAFT"
    overlay=result["overlay"]
    assert overlay["release_allowed"] is False
    assert overlay["shafts"][0]["source_handles"]==["A1"]
    assert overlay["deterministic_calculation"]["totals"]["water_fu"]>0


def test_generic_builder_rejects_unknown_endpoint_type():
    sha="d"*64
    architecture={"physical_spaces":[{"physical_space_id":"S1",
                    "polygon":[[0,0],[2,0],[2,2],[0,2]]}]}
    proposal={"schema":"planha-model-engineering-proposal/1.0","source_sha256":sha,
              "endpoints":[{"id":"BAD","type":"invented_terminal","room_id":"S1",
                            "point":[1,1],"source_sha256":sha}]}
    result=materialize_engineering_overlay(source_sha256=sha,architecture=architecture,proposal=proposal)
    assert result["status"]=="INPUT_REQUIRED"
    assert result["errors"]==["ENDPOINT_TYPE_INVALID:BAD"]


def test_structured_model_proposal_controls_program_but_not_geometry():
    sha="f"*64
    architecture={"physical_spaces":[{"physical_space_id":"K1",
        "polygon":[[0,0],[4,0],[4,3],[0,3]],"centroid":[2,1.5],"area_m2":12}],
        "functional_zones":[{"physical_space_id":"K1","category":"kitchen"}]}
    model=[{"ambiguity_id":"A-K1","room_id":"K1","endpoint_types":["sink"],
            "dependencies":["A-K1"],"authority":"MODEL_PROPOSED_DESIGN_ASSUMPTION",
            "release_allowed":False}]
    proposal=build_engineering_proposal(source_sha256=sha,architecture=architecture,
        ambiguity_ids=["A-K1"],model_proposals=model)
    assert [row["type"] for row in proposal["endpoints"]]==["sink"]
    endpoint=proposal["endpoints"][0]
    assert endpoint["point"]==[2.0,1.5]
    assert endpoint["proposal_origin"]=="LLM_STRUCTURED_RESPONSE"
    assert endpoint["source_fact"] is False
