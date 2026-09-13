"""Compatibility facade for stable runtime identities and build provenance.

New code must import :mod:`runtime_contract` or :mod:`build_identity` directly.
This module remains only so older stored jobs can be read without selecting a
parallel Mechanical implementation.
"""

from .build_identity import build_identity

PLATFORM_BUILD = build_identity()["commit_sha"]
CAD_API_IDENTITY = "cad-designer"
MECHANICAL_RUNTIME_IDENTITY = "mechanical"
MECHANICAL_VISUAL_GATE_IDENTITY = "all-sheet-visual-qa"
MECHANICAL_RULEBOOK_IDENTITY = "mechanical-rulebook"
MECHANICAL_SITE_MANIFEST_IDENTITY = "mechanical-site-manifest"
FIXTURE_EQUIPMENT_RULEBOOK_IDENTITY = "fixture-equipment-rulebook"
GOVERNANCE_IDENTITY = "mechanical-governance"
PRODUCTION_CAD_ENTRYPOINT = "cad_engine.main:app"


def active_version_manifest():
    identity = build_identity()
    return {
        "platform_build": PLATFORM_BUILD,
        "cad_api_identity": CAD_API_IDENTITY,
        "mechanical_runtime_identity": MECHANICAL_RUNTIME_IDENTITY,
        "mechanical_visual_gate_identity": MECHANICAL_VISUAL_GATE_IDENTITY,
        "mechanical_rulebook_identity": MECHANICAL_RULEBOOK_IDENTITY,
        "mechanical_site_manifest_identity": MECHANICAL_SITE_MANIFEST_IDENTITY,
        "fixture_equipment_rulebook_identity": FIXTURE_EQUIPMENT_RULEBOOK_IDENTITY,
        "governance_identity": GOVERNANCE_IDENTITY,
        "production_cad_entrypoint": PRODUCTION_CAD_ENTRYPOINT,
        "build_identity": identity,
    }
