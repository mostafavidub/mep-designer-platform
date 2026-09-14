from cad_engine.plan_isolation_acceptance import evaluate_plan_isolation


def test_unresolved_architectural_ownership_blocks_engineering():
    result=evaluate_plan_isolation({
        "architecture":{"plans":[],"quality":{"ambiguous_plan_ownership_count":1},
                        "level_ownership_contract":{"status":"FAIL"}},
        "topology":{"nodes":[],"edges":[]},"routing":{"routes":[]}})
    assert result["status"]=="FAIL"
    assert "architectural_level_ownership_unresolved" in result["errors"]
    assert "ambiguous_plan_ownership" in result["errors"]


def test_duplicate_non_typical_level_fingerprints_block_engineering():
    result=evaluate_plan_isolation({
        "architecture":{"plans":[],"quality":{},"level_ownership_contract":{"status":"PASS","plans":[
            {"plan_id":"P1","level":"GROUND","source_geometry_fingerprint":"same"},
            {"plan_id":"P2","level":"LEVEL-01","source_geometry_fingerprint":"same"}]}},
        "topology":{"nodes":[],"edges":[]},"routing":{"routes":[]}})
    assert result["status"]=="FAIL"
    assert "duplicate_architecture_across_levels:P1:P2" in result["errors"]
