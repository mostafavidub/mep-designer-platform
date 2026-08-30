"""Production mechanical authority wrapper v17.1.

The issued file is fail-closed: documentation, project inputs, architecture
preservation and final approved-board isolation must all pass on the exact DXF.
"""
from __future__ import annotations
from pathlib import Path
import shutil, tempfile

from .mechanical_authority_site_v16 import design_mechanical_authority_site as _design_v16, evaluate_architecture_preservation
from .reference_parity_engine_v17 import project_context_from_report, build_documentation_package
from .documentation_enhancer_v17 import apply_documentation_enhancements
from .final_delivery_gate_v17 import sanitize_to_approved_boards, validate_final_delivery


def _restore_or_remove(dst,backup):
    if backup and backup.exists(): shutil.copy2(backup,dst)
    else: dst.unlink(missing_ok=True)


def _release_input_errors(report):
    """Reject any project-required enrichment that is still unresolved."""
    errors=[]
    enrichment=report.get('enrichment') or {}
    for name,result in enrichment.items():
        status=str((result or {}).get('status') or '').upper()
        if status in {'INPUT_REQUIRED','FAIL'}:
            errors.append(f'{name}:{status}')
        for rec in (result or {}).get('records') or []:
            rstatus=str(rec.get('status') or '').upper()
            if rstatus in {'INPUT_REQUIRED','FAIL'}:
                errors.append(f"{name}:{rec.get('sheet') or rec.get('route') or 'record'}:{rstatus}")
    authority=report.get('authority') or {}
    basis=(authority.get('design_basis') or {})
    if basis.get('status')!='PASS':
        errors.append('design_basis_not_locked')
    return sorted(set(errors))


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    src=Path(src); dst=Path(dst); answers=dict(answers or {}); backup=None
    if dst.exists():
        fd,name=tempfile.mkstemp(prefix='engitools-v17-backup-',suffix='.dxf'); Path(name).unlink(missing_ok=True); backup=Path(name); shutil.copy2(dst,backup)
    report=_design_v16(src,dst,answers=answers,plan_analysis=plan_analysis)
    if report.get('status')!='PASS':
        if backup and backup.exists(): shutil.copy2(backup,dst); backup.unlink(missing_ok=True)
        return report

    unresolved=_release_input_errors(report)
    report['release_input_qa']={'version':'release-input-gate-v17.1','status':'PASS' if not unresolved else 'FAIL','errors':unresolved}
    if unresolved:
        report['status']='FAIL'; report['stage']='release_input_gate'
        _restore_or_remove(dst,backup)
        if backup: backup.unlink(missing_ok=True)
        return report

    context=project_context_from_report(report,answers=answers,project_id=src.stem)
    package=build_documentation_package(context); report['reference_parity_documentation']=package
    if package.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='reference_parity_documentation_gate'
        _restore_or_remove(dst,backup)
        if backup: backup.unlink(missing_ok=True)
        return report

    enhancement=apply_documentation_enhancements(dst,report,context); report['documentation_enhancement_qa']=enhancement
    if enhancement.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='documentation_enhancement_gate'
        _restore_or_remove(dst,backup)
        if backup: backup.unlink(missing_ok=True)
        return report

    # Last mutating operation: strip all source/model-space material outside the
    # approved sheet boards. This intentionally runs after v17 documentation.
    isolation=sanitize_to_approved_boards(dst,report); report['final_delivery_isolation_qa']=isolation
    if isolation.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='final_delivery_isolation_gate'
        _restore_or_remove(dst,backup)
        if backup: backup.unlink(missing_ok=True)
        return report

    preservation=evaluate_architecture_preservation(src,dst,report,answers=answers)
    report['architecture_preservation_qa_after_v17']=preservation
    if preservation.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='architecture_preservation_after_sanitization'
        _restore_or_remove(dst,backup)
        if backup: backup.unlink(missing_ok=True)
        return report

    exact=validate_final_delivery(dst,report); report['exact_file_final_delivery_qa']=exact
    if exact.get('status')!='PASS':
        report['status']='FAIL'; report['stage']='exact_file_final_delivery_gate'
        _restore_or_remove(dst,backup)
        if backup: backup.unlink(missing_ok=True)
        return report

    report['version']='mechanical-authority-site-pipeline-v17.1'
    report['status']='PASS'
    if backup: backup.unlink(missing_ok=True)
    return report
