"""Canonical mechanical engineering authority.

This is the only production-facing mechanical authority import. Historical
version-named implementation modules are compatibility debt and are not
production entrypoints. Their history/retirement is governed by the Single
Living System standard.
"""
from .mechanical_authority_site_v19 import design_mechanical_authority_site

__all__ = ["design_mechanical_authority_site"]
