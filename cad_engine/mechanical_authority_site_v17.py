"""Production mechanical authority wrapper v17.

v16 remains the engineering + Architecture Preservation transaction. v17 adds
project-agnostic Detail/Riser/Calculation/General-Notes documentation models,
writes traceable registers onto documentation sheets, re-runs exact-file
Architecture Preservation QA, and fails closed if documentation consistency is
not complete.
"""
from __future__ import annotations
from pathlib import Path
import shutil, tempfile

from .mechanical_authority_site_v16 import design_mechanical_authority_site as _design_v16, evaluate_architecture_preservation
from .reference_parity_engine_v17 import project_context_from_report, build_documentation_package
from .documentation_enhancer_v17 import apply_documentation_enhancements


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    src=Path(src); dst=Path(dst); answers=dict(answers or {}); backup=None
    if dst.exists():
        fd,name=tempfile.mkstemp(prefix='engitools-v17-backup-',suffix='.dxf'); Path(name).unlink(missing_ok=True); backup=Path(name); shutil.copy2(dst,backup)
    report=_design_v16(src,dst,answers=answers,plan_analysis=plan_analysis)
    if report.get('status')!='PASS':
        if backup and backup.exists(): shutil.copy2(backup,dst); backup.unlink(missing_ok=True)
        return report
    context=project_context_from_report(report,answers=answers,project_id=src.stem); package=build_documentation_package(context); report['reference_parity_documentation']=package
    if package.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='reference_parity_documentation_gate'
        if backup and backup.exists(): shutil.copy2(backup,dst)
        else: dst.unlink(missing_ok=True)
        if backup: backup.unlink(missing_ok=True)
        return report
    enhancement=apply_documentation_enhancements(dst,report,context); report['documentation_enhancement_qa']=enhancement
    if enhancement.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='documentation_enhancement_gate'
        if backup and backup.exists(): shutil.copy2(backup,dst)
        else: dst.unlink(missing_ok=True)
        if backup: backup.unlink(missing_ok=True)
        return report
    preservation=evaluate_architecture_preservation(src,dst,report,answers=answers); report['architecture_preservation_qa_after_v17']=preservation
    if preservation.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='architecture_preservation_after_documentation'
        if backup and backup.exists(): shutil.copy2(backup,dst)
        else: dst.unlink(missing_ok=True)
    report['version']='mechanical-authority-site-pipeline-v17.0'
    if backup: backup.unlink(missing_ok=True)
    return report
