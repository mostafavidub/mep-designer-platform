"""Compatibility facade for automatic build identity and semantic revisions."""

from .build_identity import build_identity

PLATFORM_RELEASE = build_identity()["commit_sha"]
CAD_API_VERSION = PLATFORM_RELEASE
MECHANICAL_PIPELINE_VERSION = PLATFORM_RELEASE
MECHANICAL_VISUAL_GATE_VERSION = "split-ac-visual-legibility/1"
MECHANICAL_RULEBOOK_VERSION = "5.0"
MECHANICAL_SITE_MANIFEST_VERSION = "12.1"
FIXTURE_EQUIPMENT_RULEBOOK_VERSION = "2.4-fixture-equipment-approved-symbols"
GOVERNANCE_VERSION = "mechanical-governance-v1.0"
PRODUCTION_CAD_ENTRYPOINT = "cad_engine.main:app"


def active_version_manifest():
    identity = build_identity()
    return {
        "platform_release": PLATFORM_RELEASE,
        "cad_api": CAD_API_VERSION,
        "mechanical_pipeline": MECHANICAL_PIPELINE_VERSION,
        "mechanical_visual_gate": MECHANICAL_VISUAL_GATE_VERSION,
        "mechanical_rulebook": MECHANICAL_RULEBOOK_VERSION,
        "mechanical_site_manifest": MECHANICAL_SITE_MANIFEST_VERSION,
        "fixture_equipment_rulebook": FIXTURE_EQUIPMENT_RULEBOOK_VERSION,
        "governance": GOVERNANCE_VERSION,
        "production_cad_entrypoint": PRODUCTION_CAD_ENTRYPOINT,
        "build_identity": identity,
    }
