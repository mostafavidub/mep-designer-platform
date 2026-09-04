import re
from cad_engine.build_identity import build_identity, stamp_artifact
from tools.runtime_version_guard import audit

def test_build_identity_is_complete_and_stable():
    first = build_identity(); second = build_identity()
    required = {"commit_sha","build_timestamp","pmm_schema_revision","pmm_schema_hash","rulebook_hash","manufacturer_db_hash","compliance_profile_hash","dependency_hashes","build_identity","production_entrypoint"}
    assert required <= first.keys(); assert first == second; assert first["production_entrypoint"] == "cad_engine.main:app"
    for key in ("pmm_schema_hash","rulebook_hash","manufacturer_db_hash","compliance_profile_hash","build_identity"):
        assert re.fullmatch(r"[0-9a-f]{64}", first[key])

def test_artifact_stamp_preserves_metadata():
    stamped = stamp_artifact({"artifact":"example.dxf"}); assert stamped["artifact"] == "example.dxf"; assert stamped["build"] == build_identity()

def test_no_new_parallel_runtime_versions_and_canonical_launchers():
    assert audit("56c3fc2")["status"] == "PASS"
