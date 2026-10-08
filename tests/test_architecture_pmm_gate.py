from copy import deepcopy

from app.architecture_authority_gate import (
    PERSISTENCE_KEY, architecture_authority_report, architecture_input_error,
    materialize_architecture_preflight,
)
from app.architecture_reconstruction_v1 import enrich_auto
from cad_engine.mechanical_network_topology import build_authoritative_topology_from_evidence
from tests.test_architecture_preflight_ui import model as canonical_model


SHA = "9" * 64


def source_insufficient_analysis():
    return {"architectural_auto": {"architecture_model": {
        "schema": "canonical-architectural-model/1.0",
        "source": {"source_sha256": SHA, "insunits": "METERS", "metres_per_unit": 1.0},
        "levels": [{"name": "همکف", "region_bounds": [0, 0, 10, 10]}],
        "frames": [{"frame_id": "FRAME-1", "level_candidate": "همکف", "bounds": [0, 0, 10, 10]}],
        "physical_spaces": [], "functional_zones": [], "architectural_objects": [], "dimensions": [],
        "completeness": {"status": "INPUT_REQUIRED", "release_allowed": False,
                         "downstream_engineering_allowed": False,
                         "issues": [{"code": "NO_PHYSICAL_SPACES_RECONSTRUCTED", "frame_id": "FRAME-1"}]},
    }}}


def source_insufficient_analysis_with_legacy_source_projection():
    analysis = source_insufficient_analysis()
    model = analysis["architectural_auto"]["architecture_model"]
    source = model.pop("source")
    model["source_models"] = [{"source": source, "diagnostics": {}}]
    return analysis


def test_missing_persisted_preflight_is_materialized_without_authority_promotion():
    original = source_insufficient_analysis()
    prepared, changed = materialize_architecture_preflight(original)

    assert changed is True
    assert PERSISTENCE_KEY not in original
    canonical = prepared[PERSISTENCE_KEY]["canonical_model"]
    assert canonical["release"]["release_allowed"] is False
    assert canonical["release"]["downstream_engineering_allowed"] is False
    report = architecture_authority_report(prepared)
    assert report["blocking"] is True
    assert report["state"] == "ARCHITECTURE_INPUT_REQUIRED"
    assert architecture_input_error(report).startswith("INPUT_REQUIRED[ARCHITECTURE_PREFLIGHT_REQUIRED]")


def test_single_exact_legacy_source_projection_preserves_sha_without_guessing():
    prepared, changed = materialize_architecture_preflight(
        source_insufficient_analysis_with_legacy_source_projection()
    )

    assert changed is True
    canonical = prepared[PERSISTENCE_KEY]["canonical_model"]
    assert canonical["source"]["source_sha256"] == SHA
    assert architecture_authority_report(prepared)["source_sha256"] == SHA


def test_single_dxf_reconstruction_preserves_exact_source_identity_in_aggregate():
    source = {"source_sha256": SHA, "insunits": "METERS", "metres_per_unit": 1.0}
    auto = enrich_auto({"level_profiles": []}, {"files": [{"canonical_architecture_model": {
        "source": source, "physical_spaces": [], "functional_zones": [], "frames": [],
        "architectural_objects": [], "dimensions": [],
        "completeness": {"issues": [{"code": "NO_PHYSICAL_SPACES_RECONSTRUCTED",
                                        "status": "INPUT_REQUIRED"}]},
    }}]})

    assert auto["architecture_model"]["source"] == source


def test_independently_validated_canonical_architecture_allows_downstream_gate():
    canonical = canonical_model(True)
    analysis = {PERSISTENCE_KEY: {"canonical_model": canonical, "review_registry": {},
                                  "source_sha256": canonical["source"]["source_sha256"],
                                  "canonical_model_hash": canonical["canonical_model_hash"]}}

    report = architecture_authority_report(analysis)

    assert report["state"] == "AUTO_VALIDATED"
    assert report["blocking"] is False


def test_invalid_pmm_stops_before_typed_level_or_network_inference():
    pmm = {
        "schema": "project-mechanical-model/v3", "valid": False,
        "architecture_completeness": {"status": "CONFLICT", "downstream_engineering_allowed": False},
        "levels": [{"name": "همکف", "roof": False}],
    }

    result = build_authoritative_topology_from_evidence(pmm, {}, {"detections": []})

    assert result == {"status": "INPUT_REQUIRED",
                      "missing_inputs": ["ARCHITECTURE_PREFLIGHT_REQUIRED"], "network": None}


def test_review_state_copy_does_not_mutate_canonical_input():
    canonical = canonical_model(False)
    before = deepcopy(canonical)
    analysis = {PERSISTENCE_KEY: {"canonical_model": canonical, "review_registry": {}}}

    architecture_authority_report(analysis)

    assert canonical == before
