"""Project Mechanical Model (PMM) v1.

This module adds a single, machine-readable snapshot of the mechanical design
inputs without changing any existing planner or CAD decisions. The snapshot is
stored in ``Project.analysis['project_mechanical_model']`` and is intentionally
additive in v1 so existing production behaviour remains unchanged while later
stages migrate to consume it as the contract.
"""
from copy import deepcopy


PMM_SCHEMA = "project-mechanical-model/v1"


def _unique(values):
    out = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out


def _level_rows(auto):
    profiles = auto.get("level_profiles") or []
    if profiles:
        rows = []
        for profile in profiles:
            name = str(profile.get("name") or "").strip()
            if not name:
                continue
            rows.append({
                "name": name,
                "roof": bool(profile.get("roof")),
                "room_counts": deepcopy(profile.get("room_counts") or {}),
                "recognized_room_labels": int(profile.get("recognized_room_labels") or 0),
                "wet_fixture_candidate": bool(profile.get("wet_fixture_candidate")),
                "sanitary_candidate": bool(profile.get("sanitary_candidate")),
                "conditioned_candidate": bool(profile.get("conditioned_candidate")),
                "ventilation_candidate": bool(profile.get("ventilation_candidate")),
                "gas_candidate": bool(profile.get("gas_candidate")),
                "typical_confidence": profile.get("typical_confidence"),
                "source_type": profile.get("source_type"),
                "source_name": profile.get("source_name"),
                "level_confidence": profile.get("level_confidence"),
                "level_evidence": deepcopy(profile.get("level_evidence") or []),
                "level_detection_status": profile.get("level_detection_status"),
            })
        return rows

    rows = []
    for item in auto.get("levels") or []:
        if isinstance(item, dict):
            name = item.get("name")
            confidence = item.get("confidence")
        else:
            name = item
            confidence = None
        if name:
            rows.append({
                "name": str(name), "roof": False, "room_counts": {},
                "level_confidence": confidence, "level_evidence": [],
            })
    return rows


def _space_rows(levels):
    spaces = []
    for level in levels:
        for room_type, count in (level.get("room_counts") or {}).items():
            try:
                qty = int(count or 0)
            except (TypeError, ValueError):
                qty = 0
            if qty > 0:
                spaces.append({
                    "level": level["name"],
                    "type": str(room_type),
                    "count": qty,
                    "source": "architecture-room-labels",
                })
    return spaces


def _fixture_rows(auto):
    rows = []
    for fixture_type, count in (auto.get("fixture_counts") or {}).items():
        try:
            qty = int(count or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            rows.append({"type": str(fixture_type), "count": qty, "source": "cad-fixture-detection"})
    return rows


def _shaft_rows(levels):
    rows = []
    for level in levels:
        count = int((level.get("room_counts") or {}).get("shaft") or 0)
        if count:
            rows.append({"level": level["name"], "count": count, "source": "architecture-room-labels"})
    return rows


def build_project_mechanical_model(analysis, answers=None, scope=None, proposal=None):
    """Build a deterministic, JSON-safe PMM snapshot from already-approved inputs.

    v1 deliberately *does not* alter planner decisions. It mirrors the inputs
    and the generated drawing manifest so consumers can migrate to the PMM in
    later guarded steps without changing current production output.
    """
    analysis = analysis or {}
    answers = answers or {}
    scope = scope or {}
    proposal = proposal or {}
    auto = analysis.get("architectural_auto") or {}

    levels = _level_rows(auto)
    level_names = _unique(row.get("name") for row in levels)
    manifest = deepcopy(proposal.get("drawing_manifest") or proposal.get("deliverable_sheets") or [])

    model = {
        "schema": PMM_SCHEMA,
        "mode": "shadow",
        "discipline": "mechanical",
        "levels": levels,
        "level_names": level_names,
        "candidate_levels": deepcopy(auto.get("candidate_levels") or []),
        "restored_explicit_levels": deepcopy(auto.get("restored_explicit_levels") or []),
        "spaces": _space_rows(levels),
        "fixtures": _fixture_rows(auto),
        "equipment": deepcopy(auto.get("equipment") or []),
        "shafts": _shaft_rows(levels),
        "systems": {
            "conditioned_levels": deepcopy(scope.get("conditioned_levels") or []),
            "heated_levels": deepcopy(scope.get("heated_levels") or []),
            "wet_fixture_levels": deepcopy(scope.get("wet_fixture_levels") or []),
            "sanitary_fixture_levels": deepcopy(scope.get("sanitary_fixture_levels") or []),
            "ventilation_required_levels": deepcopy(scope.get("ventilation_required_levels") or []),
            "gas_consumer_levels": deepcopy(scope.get("gas_consumer_levels") or []),
            "roof_exists": bool(scope.get("roof_exists")),
            "roof_level_name": scope.get("roof_level_name"),
            "vertical_systems": bool(scope.get("vertical_systems")),
        },
        "typical_groups": deepcopy(scope.get("typical_groups") or auto.get("typical_groups") or []),
        "drawing_manifest": manifest,
        "drawing_manifest_count": len(manifest),
        "planner_total_plans": int(proposal.get("total_plans") or proposal.get("deliverable_sheet_count") or len(manifest)),
        "inputs": {
            "architectural_inference": auto.get("effective_level_inference"),
            "level_detection_version": auto.get("level_detection_version"),
            "fixture_blocks_detected": int(auto.get("fixture_blocks_detected") or 0),
            "roof_drain_count": int(auto.get("roof_drain_count") or 0),
            "answers_present": sorted(str(key) for key in answers.keys()),
        },
    }

    diagnostics = []
    if model["planner_total_plans"] != model["drawing_manifest_count"]:
        diagnostics.append("planner_total_does_not_match_manifest_count")
    if not level_names:
        diagnostics.append("no_architecture_levels_in_pmm")
    if model["candidate_levels"]:
        diagnostics.append("unresolved_candidate_levels_present")
    diagnostics.extend(auto.get("level_detection_diagnostics") or [])
    model["diagnostics"] = list(dict.fromkeys(diagnostics))
    # Candidate levels are intentionally diagnostic, not a PMM-invalidating
    # condition in this release. Only structural integrity failures invalidate.
    model["valid"] = not any(x in model["diagnostics"] for x in (
        "planner_total_does_not_match_manifest_count", "no_architecture_levels_in_pmm"
    ))
    return model


def install(workflow_module):
    """Attach PMM generation to the existing proposal path without changing it."""
    if getattr(workflow_module, "_pmm_v1_installed", False):
        return

    original_create_proposal = workflow_module.create_proposal

    def create_proposal_with_pmm(project):
        proposal = original_create_proposal(project)
        analysis = dict(project.analysis or {})
        scope = workflow_module.build_scope(project)
        analysis["project_mechanical_model"] = build_project_mechanical_model(
            analysis=analysis,
            answers=project.answers or {},
            scope=scope,
            proposal=proposal,
        )
        project.analysis = analysis
        return proposal

    workflow_module.create_proposal = create_proposal_with_pmm
    workflow_module._pmm_v1_installed = True
