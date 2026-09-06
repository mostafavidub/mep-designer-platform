"""Discipline-aware adapter used by the shared panel bridge.

The panel bridge is intentionally discipline-agnostic.  This adapter preserves
its mature recovery/token/progress behavior while routing design-basis questions
and drawing-set approval to the correct engineering workflow.  Electrical panel
projects persist the same approved manifest contract as Mechanical before they
enter the durable design queue.
"""
from __future__ import annotations

from . import mechanical_workflow, electrical_workflow
from . import mechanical_drawing_set, electrical_drawing_set


def _discipline(project):
    return (project.answers or {}).get("discipline", (project.analysis or {}).get("discipline", "mechanical"))


def _persist_electrical_manifest_if_ready(project, missing):
    if missing:
        return
    analysis = dict(project.analysis or {})
    current = dict(analysis.get("drawing_set") or {})
    if electrical_drawing_set.approved_manifest_is_valid(current):
        return
    proposed = electrical_drawing_set.proposal(project)
    approved = electrical_drawing_set.approve_drawing_set(proposed)
    analysis["drawing_set"] = approved
    analysis["electrical_drawing_set"] = approved
    project.analysis = analysis


def required_basis_questions(project):
    if _discipline(project) == "electrical":
        missing = electrical_workflow.required_basis_questions(project)
        _persist_electrical_manifest_if_ready(project, missing)
        return missing
    return mechanical_workflow.required_basis_questions(project)


def _question_payload(key, project=None):
    if project is not None and _discipline(project) == "electrical":
        return electrical_workflow.question_payload(key)
    if key in electrical_workflow.REQUIRED_BASIS_QUESTION_SPECS:
        return electrical_workflow.question_payload(key)
    return mechanical_workflow._question_payload(key)


def create_proposal(project):
    if _discipline(project) == "electrical":
        return electrical_drawing_set.proposal(project)
    return mechanical_workflow.create_proposal(project)


def approve_drawing_set(value, project=None):
    if project is not None and _discipline(project) == "electrical":
        return electrical_drawing_set.approve_drawing_set(value)
    if str((value or {}).get("version") or "").startswith("electrical-"):
        return electrical_drawing_set.approve_drawing_set(value)
    return mechanical_workflow.approve_drawing_set(value)


def ensure_required_basis_questions(project):
    if _discipline(project) == "electrical":
        changed = electrical_workflow.ensure_required_basis_questions(project)
        if not changed:
            _persist_electrical_manifest_if_ready(project, [])
        return changed
    return mechanical_workflow.ensure_required_basis_questions(project)


def reopen_basis_questions(project, missing):
    if _discipline(project) == "electrical":
        return electrical_workflow.reopen_basis_questions(project, missing)
    return mechanical_workflow.reopen_basis_questions(project, missing)
