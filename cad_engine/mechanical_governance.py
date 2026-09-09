"""Canonical mechanical design governance surface."""
from .mechanical_governance_v1 import validate_repository_governance, validate_release_against_contract

__all__ = ["validate_repository_governance", "validate_release_against_contract"]
