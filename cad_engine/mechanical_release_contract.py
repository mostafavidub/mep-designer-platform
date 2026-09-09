"""Canonical mechanical release-contract surface.

Contract/schema revisions may retain explicit revision metadata; the runtime
engine itself has one unversioned identity.
"""
from .mechanical_release_contract_v19 import release_contract_status, REQUIRED_CAPABILITIES

__all__ = ["release_contract_status", "REQUIRED_CAPABILITIES"]
