"""Planha governed architectural dimensioning package.

This package is additive to the existing semantic_dimension_engine facade.
Mechanical output remains on the proven MEP-DIM-001 path while architecture
uses the same semantic/source-preserving contracts through explicit adapters.
"""

from .architecture import build_architectural_dimension_network
from .qa import evaluate_architectural_dimension_qa

__all__ = ["build_architectural_dimension_network", "evaluate_architectural_dimension_qa"]
