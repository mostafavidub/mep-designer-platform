"""Project-driven Electrical engineering system.

The package exposes one living runtime. Missing engineering evidence must never
be silently promoted to FINAL, and release/build identity is not encoded in
module names.
"""

from .models import EngineeringStatus, EvidenceValue

# Patch the canonical reconstruction function before pipeline modules import it.
# This remains one architectural model/runtime: the safety layer only resolves
# evidenced unit-header conflicts and rejects unsafe shared helper geometry.
from . import architecture as _architecture
from .architecture_safety import reconstruct_architecture_safe
_architecture.reconstruct_architecture = reconstruct_architecture_safe

from .pipeline import ElectricalPipeline, run_electrical_pipeline
from .release_gate import evaluate_production_release
from .strict_pipeline import run_strict_electrical_pipeline
from .release_contract import release_contract_status

__all__ = [
    "EngineeringStatus",
    "EvidenceValue",
    "ElectricalPipeline",
    "run_electrical_pipeline",
    "run_strict_electrical_pipeline",
    "evaluate_production_release",
    "release_contract_status",
]
