"""Rebuild legacy v17 support-sheet documentation from the actual engineering pipeline.

The v17 reference-parity layer previously inferred riser levels from every sheet
manifest row. That allowed support-sheet pseudo-levels such as DETAIL-1 to enter
the riser while an absent pipeline produced zero mapped branches. Production v19
replaces only those generated documentation-layer entities with a context derived
from real architectural plans and real routed engineering content.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf

from .documentation_enhancer_v17 import LAYER, TEXT_LAYER, apply_documentation_enhancements
from .reference_parity_engine_v17 import ProjectContext, canonical_system
from .final_delivery_gate_v17 import validate_final_delivery


FORBIDDEN_LEVEL_PREFIXES = ("DETAIL", "CALC", "SCHEDULE", "SERVICE")
VERTICAL_DOCUMENTATION_SYSTEMS = {"SANITARY_VENT", "WATER", "HEATING", "GAS"}


def _forbidden_level(value) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and any(text.startswith(prefix) for prefix in FORBIDDEN_LEVEL_PREFIXES)


def build_production_context(report: dict, pipeline: dict, answers: dict, project_id: str) -> ProjectContext:
    architecture = pipeline.get("architecture") or {}
    routing = pipeline.get("routing") or {}
    hvac = pipeline.get("hvac") or {}
    recognition = pipeline.get("recognition") or {}

    primary = set(architecture.get("primary_floor_plan_ids") or [])
    plans = [row for row in architecture.get("plans") or [] if not primary or row.get("plan_id") in primary]
    levels = []
    plan_level = {}
    for plan in plans:
        plan_id = plan.get("plan_id")
        level = str(plan.get("level") or plan_id or "").strip()
        if not level or _forbidden_level(level):
            continue
        if level not in levels:
            levels.append(level)
        if plan_id is not None:
            plan_level[str(plan_id)] = level

    systems = []
    for row in ((report.get("composition") or {}).get("manifest") or []):
        canonical = canonical_system(row.get("family"))
        if canonical and canonical not in systems:
            systems.append(canonical)
    for route in list(routing.get("routes") or []) + list(hvac.get("routes") or []):
        canonical = canonical_system(route.get("system"))
        if canonical and canonical not in systems:
            systems.append(canonical)

    routes = []
    for raw in list(routing.get("routes") or []) + list(hvac.get("routes") or []):
        row = dict(raw)
        level = row.get("level") or row.get("floor") or plan_level.get(str(row.get("plan_id")))
        if level and not _forbidden_level(level):
            row["level"] = level
        routes.append(row)

    return ProjectContext(
        project_id=project_id,
        building_use=str((answers or {}).get("building_use") or (answers or {}).get("occupancy") or "residential"),
        levels=levels or ["GROUND"],
        active_systems=systems,
        fixtures=list(recognition.get("fixtures") or []),
        equipment=list(hvac.get("equipment") or []),
        routes=routes,
        rooms=list(architecture.get("rooms") or []),
        answers=dict(answers or {}),
    )


def _remove_previous_documentation(dxf_path: Path) -> int:
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    removed = 0
    for entity in list(msp):
        if str(getattr(entity.dxf, "layer", "")) in {LAYER, TEXT_LAYER}:
            msp.delete_entity(entity)
            removed += 1
    doc.saveas(dxf_path)
    return removed


def rebuild_production_documentation(dxf_path: Path, report: dict, pipeline: dict, answers: dict, project_id: str) -> dict:
    context = build_production_context(report, pipeline, answers, project_id)
    bad_levels = sorted(value for value in context.levels if _forbidden_level(value))
    if bad_levels:
        return {"status": "FAIL", "errors": ["FORBIDDEN_DOCUMENTATION_LEVEL:" + ",".join(bad_levels)]}

    removed = _remove_previous_documentation(Path(dxf_path))
    enhancement = apply_documentation_enhancements(Path(dxf_path), report, context)
    package = enhancement.get("documentation_package") or {}
    reconciliation = ((package.get("riser") or {}).get("reconciliation") or {})
    expected = int(reconciliation.get("expected_branch_count") or 0)
    mapped = int(reconciliation.get("mapped_branch_count") or 0)
    vertical_active = sorted(set(context.active_systems) & VERTICAL_DOCUMENTATION_SYSTEMS)

    errors = []
    if enhancement.get("status") != "PASS":
        errors.append("DOCUMENTATION_REBUILD_FAILED")
    if reconciliation.get("pass") is not True:
        errors.append("PLAN_RISER_RECONCILIATION_FAILED")
    if expected != mapped:
        errors.append(f"PLAN_RISER_BRANCH_COUNT_MISMATCH:expected={expected}:mapped={mapped}")
    if vertical_active and expected == 0:
        errors.append("VERTICAL_SYSTEM_WITH_ZERO_PLAN_BRANCHES:" + ",".join(vertical_active))
    generated_levels = list(((package.get("riser") or {}).get("graph") or {}).get("levels") or [])
    forbidden_generated = sorted(str(value) for value in generated_levels if _forbidden_level(value))
    if forbidden_generated:
        errors.append("RISER_CONTAINS_SUPPORT_SHEET_LEVEL:" + ",".join(forbidden_generated))

    exact = validate_final_delivery(Path(dxf_path), report)
    if exact.get("status") != "PASS":
        errors.append("FINAL_DELIVERY_FAILED_AFTER_DOCUMENTATION_REBUILD")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "removed_previous_documentation_entities": removed,
        "context_levels": context.levels,
        "active_systems": context.active_systems,
        "expected_branch_count": expected,
        "mapped_branch_count": mapped,
        "enhancement": enhancement,
        "documentation_package": package,
        "exact_file_final_delivery_qa": exact,
        "source": "ACTUAL_ARCHITECTURE_LEVELS_AND_ENGINEERING_ROUTES",
    }
