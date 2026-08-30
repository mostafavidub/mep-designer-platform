"""Project-driven electrical engineering system.

No missing engineering evidence may be silently promoted to FINAL. The public
API exposes the final v15.2 authority-parity pipeline incorporating the reusable
quality lessons proven by the Mechanical authority workflow.
"""

from .models import EngineeringStatus, EvidenceValue
from .pipeline import ElectricalPipeline, run_electrical_pipeline
from .release_gate import evaluate_production_release
from .strict_pipeline import run_strict_electrical_pipeline
from .strict_pipeline_v15 import run_strict_electrical_pipeline_v15
from .strict_pipeline_v15_2 import run_strict_electrical_pipeline_v15_2
from .release_contract_v15_2 import release_contract_status

__all__ = [
    "EngineeringStatus",
    "EvidenceValue",
    "ElectricalPipeline",
    "run_electrical_pipeline",
    "run_strict_electrical_pipeline",
    "run_strict_electrical_pipeline_v15",
    "run_strict_electrical_pipeline_v15_2",
    "evaluate_production_release",
    "release_contract_status",
]
