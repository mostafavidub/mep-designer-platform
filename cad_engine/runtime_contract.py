"""Canonical Mechanical runtime contract.

Build identity and schema/contract revisions are metadata. They are not engine
versions and never select between parallel Mechanical implementations.
"""
from __future__ import annotations
from .build_identity import build_identity

PRODUCTION_CAD_ENTRYPOINT = "cad_engine.main:app"
RUNTIME_IDENTITY = "mechanical"
PMM_SCHEMA = "project-mechanical-model/v3"
TRACEABILITY_POLICY = "NO_ORPHAN_ENGINEERING_OUTPUT"


def runtime_contract() -> dict:
    return {
        "runtime_identity": RUNTIME_IDENTITY,
        "production_cad_entrypoint": PRODUCTION_CAD_ENTRYPOINT,
        "pmm_schema": PMM_SCHEMA,
        "traceability_policy": TRACEABILITY_POLICY,
        "build_identity": build_identity(),
    }
