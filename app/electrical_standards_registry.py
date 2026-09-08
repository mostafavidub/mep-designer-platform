"""Compatibility facade for the active Electrical Rule Book.

New code should import :mod:`app.electrical_rulebook`. This module remains only
to avoid breaking historical imports; it owns no independent edition/version
state and cannot supply project-specific facts.
"""
from __future__ import annotations

from .electrical_rulebook import (
    REFERENCE_RULES as STANDARDS,
    RULEBOOK_REVISION,
    project_rule_requirements,
    verified_rule_ids,
    validate_rulebook,
)


def validate_registry():
    result = validate_rulebook()
    return {
        "rulebook_revision": RULEBOOK_REVISION,
        "status": result["status"],
        "errors": result["errors"],
        "standards": STANDARDS,
        "compatibility_facade": True,
    }
