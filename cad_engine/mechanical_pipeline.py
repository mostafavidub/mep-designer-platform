"""Canonical mechanical engineering pipeline surface.

Production code imports this module; the implementation compatibility layer is
kept internal until its no-behavior-change retirement is complete.
"""
from .mechanical_pipeline_v19 import run_v19_pipeline as run_pipeline

__all__ = ["run_pipeline"]
