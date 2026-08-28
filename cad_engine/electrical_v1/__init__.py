"""Project-driven electrical engineering system.

No missing engineering evidence may be silently promoted to FINAL. The public
entry point now defaults to the strict authority-parity pipeline that incorporates
the reusable quality lessons from Mechanical v15.2.
"""

from .models import EngineeringStatus, EvidenceValue
from .pipeline import ElectricalPipeline, run_electrical_pipeline
from .release_gate import evaluate_production_release
from .strict_pipeline import run_strict_electrical_pipeline
from .strict_pipeline_v15 import run_strict_electrical_pipeline_v15
from .authority_qa import release_contract_status

__all__ = [
    "EngineeringStatus",
    "EvidenceValue",
    "ElectricalPipeline",
    "run_electrical_pipeline",
    "run_strict_electrical_pipeline",
    "run_strict_electrical_pipeline_v15",
    "evaluate_production_release",
    "release_contract_status",
]
