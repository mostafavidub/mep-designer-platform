"""Fail-closed bridge from persisted RAW-DXF architecture to downstream engineering.

The canonical adapter and independent validator remain the authority.  This
module only materializes their result in project state and exposes one shared
predicate to transports that could otherwise start Mechanical work.
"""
from __future__ import annotations

from copy import deepcopy

from cad_engine.architecture_contract import adapt_current_architecture
from cad_engine.architecture_review_engine import execute_preflight
from cad_engine.build_identity import build_identity


PERSISTENCE_KEY = "architecture_preflight_ui"


def _legacy_model(analysis):
    model = deepcopy((((analysis or {}).get("architectural_auto") or {}).get("architecture_model") or {}))
    if not (model.get("source") or {}).get("source_sha256"):
        sources = [row.get("source") for row in model.get("source_models") or []
                   if isinstance(row.get("source"), dict) and row["source"].get("source_sha256")]
        if len(sources) == 1:
            model["source"] = deepcopy(sources[0])
    return model


def materialize_architecture_preflight(analysis):
    """Return analysis with a deterministic preflight state, without promotion."""
    updated = deepcopy(analysis or {})
    stored = deepcopy(updated.get(PERSISTENCE_KEY) or {})
    canonical = stored.get("canonical_model")
    legacy = _legacy_model(updated)
    registry = stored.get("review_registry") or {}
    accepted = registry.get("accepted_decisions") or []
    source_missing = isinstance(canonical, dict) and not (canonical.get("source") or {}).get("source_sha256")
    if not isinstance(canonical, dict) or (source_missing and not accepted):
        if legacy.get("schema") != "canonical-architectural-model/1.0":
            return updated, False
        canonical = adapt_current_architecture(legacy, build_identity())
        result = execute_preflight(canonical, engine_identity=build_identity(), created_at="UNSPECIFIED")
        stored = {
            "canonical_model": deepcopy(result.get("reviewed_canonical_model") or canonical),
            "review_registry": deepcopy(result.get("review_registry") or {}),
            "snapshot": deepcopy(result.get("snapshot")),
            "last_validator_report_hash": (result.get("validator_report") or {}).get("report_hash"),
            "source_sha256": (canonical.get("source") or {}).get("source_sha256"),
            "canonical_model_hash": canonical.get("canonical_model_hash"),
            "created_at": "UNSPECIFIED",
            "requests": {},
        }
        updated[PERSISTENCE_KEY] = stored
        return updated, True
    return updated, False


def architecture_authority_report(analysis):
    """Evaluate current architecture; absence of authority is always blocking."""
    prepared, _changed = materialize_architecture_preflight(analysis)
    stored = prepared.get(PERSISTENCE_KEY) or {}
    canonical = stored.get("canonical_model")
    if not isinstance(canonical, dict):
        return {
            "state": "ARCHITECTURE_INPUT_REQUIRED", "blocking": True,
            "reason": "CANONICAL_ARCHITECTURE_REQUIRED", "review_item_count": 0,
            "source_requirement_count": 1,
        }
    result = execute_preflight(
        canonical, review_registry=stored.get("review_registry"),
        engine_identity=build_identity(), created_at=stored.get("created_at") or "UNSPECIFIED",
    )
    plan = result["preflight_plan"]
    report = result["validator_report"]
    release = canonical.get("release") or {}
    state = plan.get("primary_state") or "ARCHITECTURE_INPUT_REQUIRED"
    validator_pass = report.get("status") == "PASS"
    released = release.get("release_allowed") is True and release.get("downstream_engineering_allowed") is True
    return {
        "state": state,
        "blocking": not (state == "AUTO_VALIDATED" and validator_pass and released),
        "reason": None if validator_pass and released else "ARCHITECTURE_PREFLIGHT_REQUIRED",
        "validator_status": report.get("status"),
        "review_item_count": len(plan.get("review_items") or []),
        "source_requirement_count": len(plan.get("source_input_requirements") or []),
        "conflict_count": len(plan.get("conflicts") or []),
        "canonical_model_hash": canonical.get("canonical_model_hash"),
        "source_sha256": (canonical.get("source") or {}).get("source_sha256"),
    }


def architecture_input_error(report):
    state = report.get("state") or "ARCHITECTURE_INPUT_REQUIRED"
    return (
        "INPUT_REQUIRED[ARCHITECTURE_PREFLIGHT_REQUIRED]:"
        f"state={state};source_requirements={int(report.get('source_requirement_count') or 0)};"
        f"review_items={int(report.get('review_item_count') or 0)}"
    )


def install(main_auto_module):
    """Persist preflight beside each completed deterministic analysis."""
    if getattr(main_auto_module, "_architecture_authority_gate_installed", False):
        return
    original = main_auto_module.analyze_project_job

    def analyze_project_job(project_id):
        original(project_id)
        db = main_auto_module.legacy.Session()
        try:
            project = db.get(main_auto_module.legacy.Project, project_id)
            if not project:
                return
            analysis, changed = materialize_architecture_preflight(project.analysis or {})
            if changed:
                project.analysis = analysis
                db.commit()
        finally:
            db.close()

    main_auto_module.analyze_project_job = analyze_project_job
    main_auto_module._architecture_authority_gate_installed = True
