"""Production hook for engineering pipeline v14."""
from __future__ import annotations
from .engineering_runner_v14 import run_engineering_pipeline, validate_pipeline
from .sheet_composer_v14 import compose_engineering_content, validate_composed_dxf


def apply_engineering_pipeline_v14(src,dst,calc=None):
 calc=calc or {}; ov=dict(calc.get('_engineering_project_overrides') or {})
 if not ov.get('levels'):
  manifest=calc.get('_approved_drawing_manifest') or {}; levels=[]
  for sheet in manifest.get('sheets') or []:
   for level in sheet.get('levels') or []:
    if level not in levels: levels.append(level)
  if levels: ov['levels']=levels
 pipeline=run_engineering_pipeline(src,design_basis=calc.get('_engineering_design_basis'),project_overrides=ov)
 qa=validate_pipeline(pipeline)
 result={'version':'production-engineering-v14.10','pipeline_qa':qa}
 if qa['status']!='PASS':
  result['status']='SKIPPED_INSUFFICIENT_EVIDENCE'; return result
 composition=compose_engineering_content(dst,pipeline); cad_qa=validate_composed_dxf(dst,pipeline,composition)
 result.update({'composition':composition,'cad_qa':cad_qa,'status':'PASS' if cad_qa['status']=='PASS' else 'FAIL'})
 if result['status']=='FAIL': raise RuntimeError('Engineering pipeline v14 CAD composition QA failed: '+', '.join(cad_qa.get('errors') or []))
 return result
