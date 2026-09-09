"""Canonical Mechanical runtime contract.

Build identity and schema/configuration revisions are metadata. They are not engine
versions and never select between parallel Mechanical implementations.
"""
from __future__ import annotations

from .build_identity import build_identity

PRODUCTION_CAD_ENTRYPOINT = "cad_engine.main:app"
RUNTIME_IDENTITY = "mechanical"
PMM_SCHEMA = "project-mechanical-model/v3"
TRACEABILITY_POLICY = "NO_ORPHAN_ENGINEERING_OUTPUT"
MECHANICAL_RULEBOOK_REVISION = "5.0"
FIXTURE_EQUIPMENT_RULEBOOK_REVISION = "2.4-fixture-equipment-approved-symbols"
SITE_MANIFEST_REVISION = "12.1"
VISUAL_GATE_REVISION = "split-ac-visual-legibility/1"
GOVERNANCE_CONTRACT_REVISION = "mechanical-design-governance/1"


def runtime_contract() -> dict:
    return {
        "runtime_identity": RUNTIME_IDENTITY,
        "production_cad_entrypoint": PRODUCTION_CAD_ENTRYPOINT,
        "pmm_schema": PMM_SCHEMA,
        "traceability_policy": TRACEABILITY_POLICY,
        "mechanical_rulebook_revision": MECHANICAL_RULEBOOK_REVISION,
        "fixture_equipment_rulebook_revision": FIXTURE_EQUIPMENT_RULEBOOK_REVISION,
        "site_manifest_revision": SITE_MANIFEST_REVISION,
        "visual_gate_revision": VISUAL_GATE_REVISION,
        "governance_contract_revision": GOVERNANCE_CONTRACT_REVISION,
        "build_identity": build_identity(),
    }
