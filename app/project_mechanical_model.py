"""Project Mechanical Model (PMM).

The PMM is the machine-readable mechanical source-of-truth snapshot. Existing
planner/CAD fields remain backward compatible; v3 adds deterministic engineering
identities and traceability metadata. Route-grade level region bounds are kept
when architecture analysis supplies them so downstream topology never has to
guess a fixture/equipment level.
"""
from copy import deepcopy
from hashlib import sha256
import json


PMM_SCHEMA = "project-mechanical-model/v3"


def _unique(values):
    out = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out


def _stable_id(kind, payload):
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"PMM-{kind.upper()}-{sha256(raw.encode('utf-8')).hexdigest()[:16].upper()}"


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
                "region_bounds": deepcopy(profile.get("region_bounds")),
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
            region_bounds = deepcopy(item.get("region_bounds"))
        else:
            name = item
            confidence = None
            region_bounds = None
        if name:
            rows.append({
                "name": str(name), "roof": False, "region_bounds": region_bounds, "room_counts": {},
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


def _identity_registry(levels, spaces, fixtures, equipment, shafts, manifest):
    """Create deterministic IDs without mutating legacy PMM payload fields."""
    rows = []
    aliases = {}

    def add(kind, payload, aliases_for_row=None):
        entity_id = _stable_id(kind, payload)
        rows.append({"entity_id": entity_id, "kind": kind, "fingerprint": deepcopy(payload)})
        for alias in aliases_for_row or []:
            if alias is not None and str(alias).strip():
                aliases[str(alias)] = entity_id
        return entity_id

    for level in levels:
        add("level", {"name": level.get("name"), "source_name": level.get("source_name")}, [level.get("name")])
    for space in spaces:
        add("space-group", {"level": space.get("level"), "type": space.get("type"), "count": space.get("count")})
    for fixture in fixtures:
        add("fixture-group", {"type": fixture.get("type"), "count": fixture.get("count")})
    for index, item in enumerate(equipment or []):
        payload = {"index": index, "id": item.get("id") if isinstance(item, dict) else None,
                   "type": item.get("type") if isinstance(item, dict) else str(item)}
        aliases_for_row = [item.get("id")] if isinstance(item, dict) else []
        add("equipment", payload, aliases_for_row)
    for shaft in shafts:
        add("shaft-group", {"level": shaft.get("level"), "count": shaft.get("count")})
    for index, sheet in enumerate(manifest or []):
        if isinstance(sheet, dict):
            payload = {"index": index, "code": sheet.get("code"), "family": sheet.get("family"), "levels": sheet.get("levels")}
            aliases_for_row = [sheet.get("code"), sheet.get("id")]
        else:
            payload = {"index": index, "value": str(sheet)}
            aliases_for_row = []
        add("sheet", payload, aliases_for_row)
    return {"schema": "pmm-identity-registry/1.0", "entities": rows, "alias_to_entity_id": aliases}


def build_project_mechanical_model(analysis, answers=None, scope=None, proposal=None):
    """Build a deterministic, JSON-safe PMM snapshot from approved inputs."""
    analysis = analysis or {}
    answers = answers or {}
    scope = scope or {}
    proposal = proposal or {}
    auto = analysis.get("architectural_auto") or {}

    levels = _level_rows(auto)
    level_names = _unique(row.get("name") for row in levels)
    spaces = _space_rows(levels)
    fixtures = _fixture_rows(auto)
    equipment = deepcopy(auto.get("equipment") or [])
    shafts = _shaft_rows(levels)
    manifest = deepcopy(proposal.get("drawing_manifest") or proposal.get("deliverable_sheets") or [])
    identity_registry = _identity_registry(levels, spaces, fixtures, equipment, shafts, manifest)

    model = {
        "schema": PMM_SCHEMA,
        "mode": "authoritative-coordination-contract",
        "discipline": "mechanical",
        "levels": levels,
        "level_names": level_names,
        "candidate_levels": deepcopy(auto.get("candidate_levels") or []),
        "restored_explicit_levels": deepcopy(auto.get("restored_explicit_levels") or []),
        "spaces": spaces,
        "fixtures": fixtures,
        "equipment": equipment,
        "coordination": deepcopy(analysis.get("coordination_v19") or {
            "status": "INPUT_REQUIRED", "missing_inputs": ["STRUCTURAL_MODEL", "RCP_MODEL"],
            "claim": "NOT_COORDINATED",
        }),
        "manufacturer_selection": deepcopy(analysis.get("manufacturer_selection_v19") or {
            "status": "PRE_SUBMISSION", "selection_type": "DESIGN_ENVELOPE",
            "claim": "NOT_MANUFACTURER_CONFIRMED",
        }),
        "documentation_identity": deepcopy(analysis.get("documentation_identity_v19") or {
            "status": "INPUT_REQUIRED", "required_identity": "Plan ID=Riser ID=Calc ID=Schedule ID",
        }),
        "shafts": shafts,
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
        "identity_registry": identity_registry,
        "traceability_contract": {
            "required_chain": ["PMM_ENTITY_ID", "CALC_ID", "PLAN_ID", "RISER_ID", "SCHEDULE_ID", "QA"],
            "policy": "NO_ORPHAN_ENGINEERING_OUTPUT",
            "legacy_fields_preserved": True,
        },
        "inputs": {
            "architectural_inference": auto.get("effective_level_inference"),
            "level_detection_version": auto.get("level_detection_version"),
            "fixture_blocks_detected": int(auto.get("fixture_blocks_detected") or 0),
            "roof_drain_count": int(auto.get("roof_drain_count") or 0),
            "answers_present": sorted(str(key) for key in answers.keys()),
            "structural_rcp_policy": "authoritative-input-only",
            "manufacturer_policy": "official-datasheet-or-design-envelope",
            "level_geometry_policy": "region_bounds_preserved_when_authoritatively_detected",
        },
    }

    diagnostics = []
    if model["planner_total_plans"] != model["drawing_manifest_count"]:
        diagnostics.append("planner_total_does_not_match_manifest_count")
    if not level_names:
        diagnostics.append("no_architecture_levels_in_pmm")
    if model["candidate_levels"]:
        diagnostics.append("unresolved_candidate_levels_present")
    entity_ids = [row["entity_id"] for row in identity_registry["entities"]]
    if len(entity_ids) != len(set(entity_ids)):
        diagnostics.append("duplicate_pmm_entity_id")
    diagnostics.extend(auto.get("level_detection_diagnostics") or [])
    model["diagnostics"] = list(dict.fromkeys(diagnostics))
    model["valid"] = not any(x in model["diagnostics"] for x in (
        "planner_total_does_not_match_manifest_count", "no_architecture_levels_in_pmm", "duplicate_pmm_entity_id"
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
