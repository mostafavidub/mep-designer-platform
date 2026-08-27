"""Guarded production hook for engineering pipeline v13."""
from __future__ import annotations

from .engineering_runner_v13 import run_engineering_pipeline, validate_pipeline
from .sheet_composer_v13 import compose_engineering_content, validate_composed_dxf


def apply_engineering_pipeline_v13(src, dst, calc=None):
    calc = calc or {}
    project_overrides = dict(calc.get('_engineering_project_overrides') or {})
    if not project_overrides.get('levels'):
        manifest = calc.get('_approved_drawing_manifest') or {}
        levels=[]
        for sheet in manifest.get('sheets') or []:
            for level in sheet.get('levels') or []:
                if level not in levels: levels.append(level)
        if levels: project_overrides['levels']=levels
    pipeline = run_engineering_pipeline(src, design_basis=calc.get('_engineering_design_basis'), project_overrides=project_overrides)
    pipeline_qa = validate_pipeline(pipeline)
    result={'pipeline_qa':pipeline_qa,'version':'production-engineering-v13.10'}
    if pipeline_qa['status'] != 'PASS':
        result['status']='SKIPPED_INSUFFICIENT_EVIDENCE'
        return result
    composition=compose_engineering_content(dst,pipeline)
    cad_qa=validate_composed_dxf(dst,pipeline,composition)
    result['composition']=composition; result['cad_qa']=cad_qa
    result['status']='PASS' if cad_qa['status']=='PASS' else 'FAIL'
    if result['status']=='FAIL':
        raise RuntimeError('Engineering pipeline v13 CAD composition QA failed: '+', '.join(cad_qa.get('errors') or []))
    return result
