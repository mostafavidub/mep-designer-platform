"""Project-driven electrical engineering system.

Nothing in this package may silently promote missing engineering evidence to a
FINAL design value. See ``models.EngineeringStatus`` and the pipeline gates.
"""

from .models import EngineeringStatus, EvidenceValue
from .pipeline import ElectricalPipeline, run_electrical_pipeline

__all__ = [
    "EngineeringStatus",
    "EvidenceValue",
    "ElectricalPipeline",
    "run_electrical_pipeline",
]
