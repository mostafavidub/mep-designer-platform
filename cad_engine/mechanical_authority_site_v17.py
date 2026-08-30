"""Production mechanical authority wrapper v17.3.

The issued file is fail-closed: project inputs, approved manifest, engineering
content, documentation, architecture preservation and exact-file isolation must
all pass before a DXF can be released.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import shutil, tempfile

from .mechanical_authority_site_v16 import design_mechanical_authority_site as _design_v16, evaluate_architecture_preservation
from .reference_parity_engine_v17 import project_context_from_report, build_documentation_package
from .documentation_enhancer_v17 import apply_documentation_enhancements
from .final_delivery_gate_v17 import sanitize_to_approved_boards, validate_final_delivery

WEB_TO_CAD_FAMILY = {
    'WATER_SUPPLY': 'WATER',
    'SANITARY_VENT': 'SANITARY_VENT',
    'HEATING': 'HEATING',
    'COOLING': 'SPLIT_AC',
    'GAS': 'GAS',
    'VENTILATION_EXHAUST': 'EXHAUST',
    'ROOF_RAINWATER': 'ROOF',
}
PRIMARY_CAD_FAMILIES = set(WEB_TO_CAD_FAMILY.values())


def _restore_or_remove(dst,backup):
    if backup and backup.exists(): shutil.copy2(backup,dst)
    else: dst.unlink(missing_ok=True)


def _normalize_project_answers(answers):
    """Bridge questionnaire keys to legacy CAD input names without inventing values."""
    a=dict(answers or {})
    if a.get('water_inlet_pressure') not in (None,'') and a.get('water_pressure') in (None,''):
        a['water_pressure']=a['water_inlet_pressure']
    return a


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
        family=str(raw.get('family') or raw.get('drawing_family') or raw.get('system') or '').strip().upper()
        canonical=WEB_TO_CAD_FAMILY.get(family,family)
        levels=raw.get('levels') or []
        if not isinstance(levels,list): levels=[levels]
        level=str(raw.get('level') or raw.get('floor') or raw.get('pattern') or (levels[0] if len(levels)==1 else 'MULTI') or 'MULTI').strip().upper()
        drawing_type=str(raw.get('drawing_type') or raw.get('purpose') or raw.get('type') or 'PLAN').strip().upper()
        rows.append({
            'family':family,'canonical_family':canonical,'level':level,
            'purpose':str(raw.get('purpose') or 'PLAN').strip().upper(),
            'drawing_type':drawing_type,
            'code':str(raw.get('code') or raw.get('sheet_code') or raw.get('sheet') or '').strip().upper(),
            'special':bool(raw.get('special')),
        })
    return rows


def _approved_primary_counts(rows):
    counts=Counter()
    for row in rows:
        family=row['canonical_family']
        if family not in PRIMARY_CAD_FAMILIES: continue
        # Customer manifest can contain riser/equipment/detail roles under the
        # same family. Only floor/roof plan identities control the primary CAD
        # plan count; support documentation is allowed only for approved systems.
        if family=='ROOF':
            if row['drawing_type']=='ROOF_PLAN' and row['family']=='ROOF_RAINWATER': counts[family]+=1
        elif row['drawing_type']=='FLOOR_PLAN':
            counts[family]+=1
    return counts


def _generated_primary_counts(rows):
    counts=Counter()
    for row in rows:
        family=row['canonical_family']
        if family not in PRIMARY_CAD_FAMILIES: continue
        level=row['level']
        purpose=row['purpose']
        if family=='ROOF':
            counts[family]+=1
        elif purpose=='PLAN' and level not in {'SERVICE','ROOF'}:
            counts[family]+=1
    return counts


def validate_approved_manifest(report,answers):
    """Enforce the workflow-approved system plan set on the generated CAD set.

    Web and CAD planners use different internal family names and support-sheet
    schemas. Canonical system identities are therefore the release contract:
    no unapproved primary system may appear, every approved primary system must
    appear, and the number of primary floor/roof plans must match. Cover, notes,
    calculations, risers, schedules and project-applicable details are support
    documents and may exist only when their parent approved system is present.
    """
    approved_raw=(answers or {}).get('_approved_drawing_manifest')
    generated=_manifest_rows(((report.get('composition') or {}).get('manifest') or []))
    if approved_raw is None:
        return {'version':'approved-manifest-gate-v17.3','status':'SKIPPED','errors':[],'reason':'NO_WORKFLOW_MANIFEST_IN_DIRECT_ENGINE_CALL','generated_count':len(generated)}
    approved=_manifest_rows(approved_raw);errors=[]
    if not approved: errors.append('approved_manifest_unparseable_or_empty')
    if not generated: errors.append('generated_manifest_empty')
    approved_primary=_approved_primary_counts(approved);generated_primary=_generated_primary_counts(generated)
    approved_families=set(approved_primary);generated_families=set(generated_primary)
    extra=sorted(generated_families-approved_families);missing=sorted(approved_families-generated_families)
    if extra: errors.append('generated_unapproved_system_families:'+','.join(extra))
    if missing: errors.append('approved_system_families_not_generated:'+','.join(missing))
    for family in sorted(approved_families & generated_families):
        if approved_primary[family] != generated_primary[family]:
            errors.append(f'primary_plan_count_mismatch:{family}:approved={approved_primary[family]}:generated={generated_primary[family]}')

    # Fail closed if support documents imply a system that the user did not approve.
    support_parent={
        'PLUMBING_RISER':'SANITARY_VENT',
        'WATER_SERVICE_CALC':'WATER',
    }
    for row in generated:
        parent=support_parent.get(row['canonical_family'])
        if parent and parent not in approved_families:
            errors.append(f'unapproved_support_family:{row["canonical_family"]}:requires={parent}')
    if any(r['canonical_family']=='EQUIPMENT_SCHEDULE' for r in generated) and not (approved_families & {'HEATING','SPLIT_AC','GAS','EXHAUST'}):
        errors.append('unapproved_support_family:EQUIPMENT_SCHEDULE:no_approved_equipment_system')
    if any(r['canonical_family']=='GENERAL_DETAIL' for r in generated) and not approved_families:
        errors.append('unapproved_support_family:GENERAL_DETAIL:no_approved_system')

    return {
        'version':'approved-manifest-gate-v17.3','status':'PASS' if not errors else 'FAIL','errors':sorted(set(errors)),
        'approved_count':len(approved),'generated_count':len(generated),'source':'workflow_approved_manifest',
        'approved_primary_counts':dict(approved_primary),'generated_primary_counts':dict(generated_primary),
    }


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    src=Path(src);dst=Path(dst);answers=_normalize_project_answers(answers);backup=None
    if dst.exists():
        fd,name=tempfile.mkstemp(prefix='engitools-v17-backup-',suffix='.dxf');Path(name).unlink(missing_ok=True);backup=Path(name);shutil.copy2(dst,backup)
    report=_design_v16(src,dst,answers=answers,plan_analysis=plan_analysis)
    if report.get('status')!='PASS':
        if backup and backup.exists():shutil.copy2(backup,dst);backup.unlink(missing_ok=True)
        return report
    unresolved=_release_input_errors(report);report['release_input_qa']={'version':'release-input-gate-v17.3','status':'PASS' if not unresolved else 'FAIL','errors':unresolved}
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
    report['version']='mechanical-authority-site-pipeline-v17.3';report['status']='PASS'
    if backup:backup.unlink(missing_ok=True)
    return report
