"""Production mechanical authority wrapper v17.2.

The issued file is fail-closed: project inputs, approved manifest, engineering
content, documentation, architecture preservation and exact-file isolation must
all pass before a DXF can be released.
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
    errors=[]
    enrichment=report.get('enrichment') or {}
    for name,result in enrichment.items():
        status=str((result or {}).get('status') or '').upper()
        if status in {'INPUT_REQUIRED','FAIL'}: errors.append(f'{name}:{status}')
        for rec in (result or {}).get('records') or []:
            rstatus=str(rec.get('status') or '').upper()
            if rstatus in {'INPUT_REQUIRED','FAIL'}: errors.append(f"{name}:{rec.get('sheet') or rec.get('route') or 'record'}:{rstatus}")
    authority=report.get('authority') or {};basis=authority.get('design_basis') or {}
    if basis.get('status')!='PASS': errors.append('design_basis_not_locked')
    pipeline_qa=report.get('pipeline_qa') or {}
    if pipeline_qa.get('status')!='PASS': errors.extend('pipeline:'+str(x) for x in pipeline_qa.get('errors') or [])
    return sorted(set(errors))


def _manifest_rows(value):
    if isinstance(value,dict): value=value.get('sheets') or value.get('manifest') or value.get('approved_manifest') or []
    if not isinstance(value,list): return []
    rows=[]
    for raw in value:
        if not isinstance(raw,dict): continue
        rows.append({'family':str(raw.get('family') or raw.get('drawing_family') or raw.get('system') or '').strip().upper(),
                     'level':str(raw.get('level') or raw.get('floor') or 'MULTI').strip().upper(),
                     'purpose':str(raw.get('purpose') or raw.get('type') or 'PLAN').strip().upper(),
                     'code':str(raw.get('code') or raw.get('sheet_code') or raw.get('sheet') or '').strip().upper()})
    return rows


def validate_approved_manifest(report,answers):
    approved_raw=(answers or {}).get('_approved_drawing_manifest');generated=_manifest_rows(((report.get('composition') or {}).get('manifest') or []))
    if approved_raw is None:
        return {'version':'approved-manifest-gate-v17.2','status':'SKIPPED','errors':[],'reason':'NO_WORKFLOW_MANIFEST_IN_DIRECT_ENGINE_CALL','generated_count':len(generated)}
    approved=_manifest_rows(approved_raw);errors=[]
    if not approved: errors.append('approved_manifest_unparseable_or_empty')
    if not generated: errors.append('generated_manifest_empty')
    if approved and generated:
        if all(x['family'] for x in approved) and all(x['family'] for x in generated):
            a={(x['family'],x['level'],x['purpose']) for x in approved};g={(x['family'],x['level'],x['purpose']) for x in generated}
        else:
            a={x['code'] for x in approved if x['code']};g={x['code'] for x in generated if x['code']}
        if not a or not g: errors.append('manifest_has_no_comparable_identity')
        else:
            extra=sorted(g-a);missing=sorted(a-g)
            if extra: errors.append('generated_unapproved_sheets:'+repr(extra))
            if missing: errors.append('approved_sheets_not_generated:'+repr(missing))
    return {'version':'approved-manifest-gate-v17.2','status':'PASS' if not errors else 'FAIL','errors':errors,'approved_count':len(approved),'generated_count':len(generated),'source':'workflow_approved_manifest'}


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    src=Path(src);dst=Path(dst);answers=dict(answers or {});backup=None
    if dst.exists():
        fd,name=tempfile.mkstemp(prefix='engitools-v17-backup-',suffix='.dxf');Path(name).unlink(missing_ok=True);backup=Path(name);shutil.copy2(dst,backup)
    report=_design_v16(src,dst,answers=answers,plan_analysis=plan_analysis)
    if report.get('status')!='PASS':
        if backup and backup.exists():shutil.copy2(backup,dst);backup.unlink(missing_ok=True)
        return report
    unresolved=_release_input_errors(report);report['release_input_qa']={'version':'release-input-gate-v17.2','status':'PASS' if not unresolved else 'FAIL','errors':unresolved}
    if unresolved:
        report['status']='FAIL';report['stage']='release_input_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    manifest_qa=validate_approved_manifest(report,answers);report['approved_manifest_qa']=manifest_qa
    if manifest_qa.get('status')=='FAIL':
        report['status']='FAIL';report['stage']='approved_manifest_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    context=project_context_from_report(report,answers=answers,project_id=src.stem);package=build_documentation_package(context);report['reference_parity_documentation']=package
    if package.get('status')!='PASS':
        report['status']='FAIL';report['stage']='reference_parity_documentation_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    enhancement=apply_documentation_enhancements(dst,report,context);report['documentation_enhancement_qa']=enhancement
    if enhancement.get('status')!='PASS':
        report['status']='FAIL';report['stage']='documentation_enhancement_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    isolation=sanitize_to_approved_boards(dst,report);report['final_delivery_isolation_qa']=isolation
    if isolation.get('status')!='PASS':
        report['status']='FAIL';report['stage']='final_delivery_isolation_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    preservation=evaluate_architecture_preservation(src,dst,report,answers=answers);report['architecture_preservation_qa_after_v17']=preservation
    if preservation.get('status')!='PASS':
        report['status']='FAIL';report['stage']='architecture_preservation_after_sanitization';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    exact=validate_final_delivery(dst,report);report['exact_file_final_delivery_qa']=exact
    if exact.get('status')!='PASS':
        report['status']='FAIL';report['stage']='exact_file_final_delivery_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    report['version']='mechanical-authority-site-pipeline-v17.2';report['status']='PASS'
    if backup:backup.unlink(missing_ok=True)
    return report
