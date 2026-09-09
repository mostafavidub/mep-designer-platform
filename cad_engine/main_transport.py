"""Canonical CAD API transport boundary.

The underlying transport implementation is compatibility debt. Mechanical
engineering authority is injected by cad_engine.main from the canonical
mechanical_authority module; this module is not a mechanical design engine.
"""
from . import main_v15 as transport_module
from .main_v18 import app

__all__ = ["app", "transport_module"]
