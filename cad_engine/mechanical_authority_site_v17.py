"""Production mechanical authority wrapper v17.4.

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
DRAWING_TYPE_ROLE = {
    'RISER_DIAGRAM': 'RISER',
    'EQUIPMENT_PLAN': 'EQUIPMENT',
    'CALCULATION_SHEET': 'CALC',
    'SCHEMATIC': 'SCHEMATIC',
    'DETAIL_SHEET': 'DETAIL',
    'VENTILATION_PLAN': 'VENTILATION',
}


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
            'title':str(raw.get('title') or raw.get('title_fa') or raw.get('label') or '').strip().upper(),
        })
    return rows


def _approved_primary_counts(rows):
    counts=Counter()
    for row in rows:
        family=row['canonical_family']
        if family not in PRIMARY_CAD_FAMILIES: continue
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
        level=row['level']; purpose=row['purpose']
        if family=='ROOF': counts[family]+=1
        elif purpose=='PLAN' and level not in {'SERVICE','ROOF'}: counts[family]+=1
    return counts


def _approved_support_roles(rows):
    roles=set()
    for row in rows:
        family=row['canonical_family']
        role=DRAWING_TYPE_ROLE.get(row['drawing_type'])
        if family in PRIMARY_CAD_FAMILIES and role:
            roles.add((family,role))
        # A non-rainwater roof_plan nested under another family is support, not
        # the primary roof/rainwater drawing.
        if family in PRIMARY_CAD_FAMILIES and family!='ROOF' and row['drawing_type']=='ROOF_PLAN':
            roles.add((family,'ROOF_SUPPORT'))
    return roles


def _require_role(errors, approved_roles, family, role, generated_label):
    if (family,role) not in approved_roles:
        errors.append(f'unapproved_support_role:{generated_label}:requires={family}/{role}')


def validate_approved_manifest(report,answers):
    """Enforce approved primary plans and project-dependent support documents.

    Primary floor/roof plan counts must match the customer-approved manifest.
    Variable support sheets are release-authorized only when the approved Web
    manifest contains the corresponding role. Cover/general-notes remain fixed
    administrative documents; they cannot authorize an otherwise absent system.
    """
    approved_raw=(answers or {}).get('_approved_drawing_manifest')
    generated=_manifest_rows(((report.get('composition') or {}).get('manifest') or []))
    if approved_raw is None:
        return {'version':'approved-manifest-gate-v17.4','status':'SKIPPED','errors':[],'reason':'NO_WORKFLOW_MANIFEST_IN_DIRECT_ENGINE_CALL','generated_count':len(generated)}
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

    approved_roles=_approved_support_roles(approved)
    for row in generated:
        family=row['canonical_family']; level=row['level']; purpose=row['purpose']; title=row['title']
        if family=='WATER' and purpose=='PLAN' and level=='SERVICE':
            _require_role(errors,approved_roles,'WATER','EQUIPMENT','WATER/SERVICE')
        elif family=='WATER_SERVICE_CALC':
            _require_role(errors,approved_roles,'WATER','CALC','WATER_SERVICE_CALC')
        elif family=='PLUMBING_RISER':
            _require_role(errors,approved_roles,'SANITARY_VENT','RISER','PLUMBING_RISER')
        elif family=='SPLIT_AC' and purpose=='PLAN' and level=='ROOF':
            # Roof outdoor-unit coordination is an equipment/roof-support role,
            # not an extra primary cooling plan.
            if ('SPLIT_AC','EQUIPMENT') not in approved_roles and ('SPLIT_AC','ROOF_SUPPORT') not in approved_roles:
                errors.append('unapproved_support_role:SPLIT_AC/ROOF:requires=SPLIT_AC/EQUIPMENT_OR_ROOF_SUPPORT')
        elif family=='GENERAL_DETAIL':
            if 'GAS' in title:
                _require_role(errors,approved_roles,'GAS','DETAIL','GENERAL_DETAIL/GAS')
            elif 'HVAC' in title:
                if not any((f,'DETAIL') in approved_roles or (f,'EQUIPMENT') in approved_roles for f in ('HEATING','SPLIT_AC','EXHAUST')):
                    errors.append('unapproved_support_role:GENERAL_DETAIL/HVAC:no_approved_hvac_detail_role')
            elif 'PLUMBING' in title:
                if not any((f,'DETAIL') in approved_roles for f in ('WATER','SANITARY_VENT')):
                    errors.append('unapproved_support_role:GENERAL_DETAIL/PLUMBING:no_approved_plumbing_detail_role')
            elif not approved_roles:
                errors.append('unapproved_support_role:GENERAL_DETAIL:no_approved_support_role')
        elif family=='EQUIPMENT_SCHEDULE':
            # A combined schedule is justified only by an approved equipment
            # role; primary system presence alone is not enough.
            if not any((f,'EQUIPMENT') in approved_roles for f in ('HEATING','SPLIT_AC','GAS','EXHAUST','WATER')):
                errors.append('unapproved_support_role:EQUIPMENT_SCHEDULE:no_approved_equipment_role')

    return {
        'version':'approved-manifest-gate-v17.4','status':'PASS' if not errors else 'FAIL','errors':sorted(set(errors)),
        'approved_count':len(approved),'generated_count':len(generated),'source':'workflow_approved_manifest',
        'approved_primary_counts':dict(approved_primary),'generated_primary_counts':dict(generated_primary),
        'approved_support_roles':sorted(f'{f}/{r}' for f,r in approved_roles),
    }


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    src=Path(src);dst=Path(dst);answers=_normalize_project_answers(answers);backup=None
    if dst.exists():
        fd,name=tempfile.mkstemp(prefix='engitools-v17-backup-',suffix='.dxf');Path(name).unlink(missing_ok=True);backup=Path(name);shutil.copy2(dst,backup)
    report=_design_v16(src,dst,answers=answers,plan_analysis=plan_analysis)
    if report.get('status')!='PASS':
        if backup and backup.exists():shutil.copy2(backup,dst);backup.unlink(missing_ok=True)
        return report
    unresolved=_release_input_errors(report);report['release_input_qa']={'version':'release-input-gate-v17.4','status':'PASS' if not unresolved else 'FAIL','errors':unresolved}
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
    report['version']='mechanical-authority-site-pipeline-v17.4';report['status']='PASS'
    if backup:backup.unlink(missing_ok=True)
    return report
