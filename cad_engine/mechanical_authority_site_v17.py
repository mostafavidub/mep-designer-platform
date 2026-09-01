"""Production mechanical authority wrapper v17.6.

The issued file is fail-closed: project inputs, approved manifest, engineering
content, documentation, architecture preservation and exact-file isolation must
all pass before a DXF can be released.

v17.6 strengthens the approved-manifest contract so that every approved plan
(floor, roof, equipment or ventilation plan) must result in exactly one real
generated board. Count-only family agreement is not enough: duplicate/missing
board identities and empty mechanical boards also block release.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import shutil, tempfile

import ezdxf
from ezdxf import bbox

from .mechanical_authority_site_v16 import design_mechanical_authority_site as _design_v16, evaluate_architecture_preservation
from .reference_parity_engine_v17 import project_context_from_report, build_documentation_package
from .documentation_enhancer_v17 import apply_documentation_enhancements
from .final_delivery_gate_v17 import sanitize_to_approved_boards, validate_final_delivery
from .mechanical_release_hardening_v18 import (
    validate_layout_geometry, validate_titleblocks, validate_safe_zones,
    validate_equipment_linkage, validate_detail_library,
    validate_content_completeness, validate_split_ac_visual_legibility, create_montage_and_validate,
    validate_architectural_presentation,
)
from .version_manifest import MECHANICAL_PIPELINE_VERSION

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
PLAN_DRAWING_TYPES = {'FLOOR_PLAN','ROOF_PLAN','EQUIPMENT_PLAN','VENTILATION_PLAN'}
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
            'old_sheet':str(raw.get('old_sheet') or raw.get('board_id') or '').strip(),
        })
    return rows


def _is_approved_primary(row):
    family=row['canonical_family']
    if family not in PRIMARY_CAD_FAMILIES: return False
    if family=='ROOF':
        return row['drawing_type']=='ROOF_PLAN' and row['family']=='ROOF_RAINWATER'
    return row['drawing_type']=='FLOOR_PLAN'


def _is_generated_primary(row):
    family=row['canonical_family']
    if family not in PRIMARY_CAD_FAMILIES: return False
    if family=='ROOF': return True
    return row['purpose']=='PLAN' and row['level'] not in {'SERVICE','ROOF'}


def _is_approved_plan_board(row):
    return row['canonical_family'] in PRIMARY_CAD_FAMILIES and row['drawing_type'] in PLAN_DRAWING_TYPES


def _is_generated_plan_board(row):
    family=row['canonical_family']
    if family not in PRIMARY_CAD_FAMILIES: return False
    # CAD composition represents floor, service/equipment and roof plans with
    # purpose=PLAN. ROOF itself is always a plan board.
    return family=='ROOF' or row['purpose']=='PLAN'


def _approved_primary_counts(rows):
    counts=Counter()
    for row in rows:
        if _is_approved_primary(row): counts[row['canonical_family']]+=1
    return counts


def _generated_primary_counts(rows):
    counts=Counter()
    for row in rows:
        if _is_generated_primary(row): counts[row['canonical_family']]+=1
    return counts


def _plan_board_contract(approved,generated,composition):
    """Require one real, unique board for every approved plan-type deliverable."""
    errors=[]
    approved_rows=[r for r in approved if _is_approved_plan_board(r)]
    generated_rows=[r for r in generated if _is_generated_plan_board(r)]
    expected=len(approved_rows); actual=len(generated_rows)
    if expected != actual:
        errors.append(f'total_plan_count_mismatch:approved={expected}:generated={actual}')

    generated_codes=[r['code'] for r in generated_rows]
    blank_codes=[str(i) for i,c in enumerate(generated_codes) if not c]
    if blank_codes: errors.append('generated_plan_code_missing:index='+','.join(blank_codes))
    duplicates=sorted(k for k,v in Counter(generated_codes).items() if k and v>1)
    if duplicates: errors.append('duplicate_generated_plan_codes:'+','.join(duplicates))

    board_ids=[r['old_sheet'] for r in generated_rows]
    missing_board_id=[r['code'] or '?' for r in generated_rows if not r['old_sheet']]
    if missing_board_id: errors.append('generated_plan_missing_board_id:'+','.join(sorted(missing_board_id)))
    duplicate_board_ids=sorted(k for k,v in Counter(board_ids).items() if k and v>1)
    if duplicate_board_ids: errors.append('duplicate_generated_plan_board_ids:'+','.join(duplicate_board_ids))

    boards=(composition or {}).get('boards') or {}
    missing_boards=[]; invalid_boards=[]
    for row in generated_rows:
        bid=row['old_sheet']
        if not bid: continue
        board=boards.get(bid)
        if not board:
            missing_boards.append(row['code'] or bid); continue
        area=board.get('plan_area')
        if not isinstance(area,(list,tuple)) or len(area)!=4:
            invalid_boards.append(row['code'] or bid)
    if missing_boards: errors.append('generated_plan_board_not_found:'+','.join(sorted(missing_boards)))
    if invalid_boards: errors.append('generated_plan_board_invalid:'+','.join(sorted(invalid_boards)))

    real_board_count=sum(1 for r in generated_rows if r['old_sheet'] and r['old_sheet'] in boards)
    if real_board_count != actual:
        errors.append(f'plan_board_count_mismatch:generated_plans={actual}:real_boards={real_board_count}')

    return {
        'status':'PASS' if not errors else 'FAIL','errors':sorted(set(errors)),
        'expected_plans':expected,'generated_plans':actual,'real_plan_boards':real_board_count,
        'generated_plan_codes':generated_codes,'generated_plan_board_ids':board_ids,
    }


def _approved_support_roles(rows):
    roles=set()
    for row in rows:
        family=row['canonical_family']
        role=DRAWING_TYPE_ROLE.get(row['drawing_type'])
        if family in PRIMARY_CAD_FAMILIES and role: roles.add((family,role))
        if family in PRIMARY_CAD_FAMILIES and family!='ROOF' and row['drawing_type']=='ROOF_PLAN':
            roles.add((family,'ROOF_SUPPORT'))
    return roles


def _require_role(errors, approved_roles, family, role, generated_label):
    if (family,role) not in approved_roles:
        errors.append(f'unapproved_support_role:{generated_label}:requires={family}/{role}')


def validate_approved_manifest(report,answers):
    """Enforce approved plan boards, primary family counts and justified supports."""
    approved_raw=(answers or {}).get('_approved_drawing_manifest')
    composition=report.get('composition') or {}
    generated=_manifest_rows(composition.get('manifest') or [])
    if approved_raw is None:
        return {'version':'approved-manifest-gate-v17.6','status':'SKIPPED','errors':[],'reason':'NO_WORKFLOW_MANIFEST_IN_DIRECT_ENGINE_CALL','generated_count':len(generated)}
    approved=_manifest_rows(approved_raw);errors=[];derived_support=[]
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

    # Manifest-only validation is used before CAD composition and cannot prove
    # physical board identity. Once boards exist (the production path), enforce
    # the complete one-approved-plan-to-one-real-board contract fail-closed.
    if composition.get('boards'):
        plan_contract=_plan_board_contract(approved,generated,composition)
        errors.extend(plan_contract['errors'])
    else:
        approved_plans=[r for r in approved if _is_approved_plan_board(r)]
        generated_plans=[r for r in generated if _is_generated_plan_board(r)]
        plan_contract={'status':'NOT_APPLICABLE_PRE_COMPOSITION','errors':[],
                       'expected_plans':len(approved_plans),'generated_plans':len(generated_plans),
                       'real_plan_boards':0,'generated_plan_codes':[r['code'] for r in generated_plans],
                       'generated_plan_board_ids':[]}

    approved_roles=_approved_support_roles(approved)
    for row in generated:
        family=row['canonical_family']; level=row['level']; purpose=row['purpose']; title=row['title']
        if family=='WATER' and purpose=='PLAN' and level=='SERVICE':
            if not ({('WATER','EQUIPMENT'),('WATER','RISER')} & approved_roles):
                errors.append('unapproved_support_role:WATER/SERVICE:requires=WATER/EQUIPMENT')
            elif ('WATER','EQUIPMENT') not in approved_roles:
                derived_support.append('WATER/SERVICE<-WATER/RISER')
        elif family=='WATER_SERVICE_CALC':
            if not ({('WATER','CALC'),('WATER','RISER')} & approved_roles):
                errors.append('unapproved_support_role:WATER_SERVICE_CALC:requires=WATER/CALC')
            elif ('WATER','CALC') not in approved_roles:
                derived_support.append('WATER_SERVICE_CALC<-WATER/RISER')
        elif family=='PLUMBING_RISER':
            if not ({'WATER','SANITARY_VENT'} & approved_families):
                errors.append('unapproved_support_family:PLUMBING_RISER:no_approved_plumbing_system')
            else:
                derived_support.append('PLUMBING_RISER<-approved_plumbing_primary')
        elif family=='SPLIT_AC' and purpose=='PLAN' and level=='ROOF':
            if ('SPLIT_AC','EQUIPMENT') not in approved_roles and ('SPLIT_AC','ROOF_SUPPORT') not in approved_roles:
                errors.append('unapproved_support_role:SPLIT_AC/ROOF:requires=SPLIT_AC/EQUIPMENT_OR_ROOF_SUPPORT')
        elif family=='GENERAL_DETAIL':
            if 'GAS' in title:
                if 'GAS' not in approved_families: errors.append('unapproved_support_family:GENERAL_DETAIL/GAS:requires=GAS')
                else: derived_support.append('GENERAL_DETAIL/GAS<-GAS')
            elif 'HVAC' in title:
                parents=approved_families & {'HEATING','SPLIT_AC','EXHAUST'}
                if not parents: errors.append('unapproved_support_family:GENERAL_DETAIL/HVAC:no_approved_hvac_system')
                else: derived_support.append('GENERAL_DETAIL/HVAC<-'+','.join(sorted(parents)))
            elif 'PLUMBING' in title:
                parents=approved_families & {'WATER','SANITARY_VENT'}
                if not parents: errors.append('unapproved_support_family:GENERAL_DETAIL/PLUMBING:no_approved_plumbing_system')
                else: derived_support.append('GENERAL_DETAIL/PLUMBING<-'+','.join(sorted(parents)))
            elif not approved_families:
                errors.append('unapproved_support_family:GENERAL_DETAIL:no_approved_system')
        elif family=='EQUIPMENT_SCHEDULE':
            parents=approved_families & {'HEATING','SPLIT_AC','GAS','EXHAUST'}
            if not parents: errors.append('unapproved_support_family:EQUIPMENT_SCHEDULE:no_approved_equipment_system')
            else: derived_support.append('EQUIPMENT_SCHEDULE<-'+','.join(sorted(parents)))

    reported_roles=set(approved_roles)
    if 'WATER/SERVICE<-WATER/RISER' in derived_support:
        reported_roles.add(('WATER','EQUIPMENT'))
    if 'WATER_SERVICE_CALC<-WATER/RISER' in derived_support:
        reported_roles.add(('WATER','CALC'))

    return {
        'version':'approved-manifest-gate-v17.6','status':'PASS' if not errors else 'FAIL','errors':sorted(set(errors)),
        'approved_count':len(approved),'generated_count':len(generated),'source':'workflow_approved_manifest',
        'approved_primary_counts':dict(approved_primary),'generated_primary_counts':dict(generated_primary),
        'expected_plan_count':plan_contract['expected_plans'],
        'generated_plan_count':plan_contract['generated_plans'],
        'real_plan_board_count':plan_contract['real_plan_boards'],
        'generated_plan_codes':plan_contract['generated_plan_codes'],
        # Include effective roles derived from an approved WATER/RISER so older
        # consumers can keep reading the normalized support-role contract.
        'approved_support_roles':sorted(f'{f}/{r}' for f,r in reported_roles),
        'derived_support_documents':sorted(set(derived_support)),
    }


def validate_plan_board_population(dst,report,answers):
    """Reopen exact DXF and reject any issued plan board with no mechanical content."""
    approved_raw=(answers or {}).get('_approved_drawing_manifest')
    if approved_raw is None:
        return {'version':'plan-board-population-v17.6','status':'SKIPPED','errors':[],'reason':'NO_WORKFLOW_MANIFEST_IN_DIRECT_ENGINE_CALL'}
    composition=report.get('composition') or {}
    generated=_manifest_rows(composition.get('manifest') or [])
    boards=composition.get('boards') or {}
    try:
        doc=ezdxf.readfile(dst)
    except Exception as exc:
        return {'version':'plan-board-population-v17.6','status':'FAIL','errors':['exact_dxf_reopen_failed:'+str(exc)]}
    results=[];errors=[]
    for row in generated:
        if not _is_generated_plan_board(row): continue
        board=boards.get(row['old_sheet']) or {}
        area=board.get('plan_area')
        if not isinstance(area,(list,tuple)) or len(area)!=4:
            continue
        x1,y1,x2,y2=map(float,area); count=0
        for entity in doc.modelspace():
            layer=str(getattr(entity.dxf,'layer','') or '').upper()
            if not layer.startswith('ENGITOOLS-M-'): continue
            try:
                ex=bbox.extents([entity],fast=True)
                if not ex.has_data: continue
                cx=(float(ex.extmin.x)+float(ex.extmax.x))/2
                cy=(float(ex.extmin.y)+float(ex.extmax.y))/2
            except Exception:
                continue
            if x1<=cx<=x2 and y1<=cy<=y2: count+=1
        status='PASS' if count>0 else 'FAIL'
        if status=='FAIL': errors.append('empty_plan_mechanical_board:'+str(row['code'] or row['old_sheet']))
        results.append({'code':row['code'],'board_id':row['old_sheet'],'mechanical_entity_count':count,'status':status})
    return {'version':'plan-board-population-v17.6','status':'PASS' if not errors else 'FAIL','errors':errors,'boards':results,'exact_file_reopened':True}


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    src=Path(src);dst=Path(dst);answers=_normalize_project_answers(answers);backup=None
    if dst.exists():
        fd,name=tempfile.mkstemp(prefix='engitools-v17-backup-',suffix='.dxf');Path(name).unlink(missing_ok=True);backup=Path(name);shutil.copy2(dst,backup)
    report=_design_v16(src,dst,answers=answers,plan_analysis=plan_analysis)
    if report.get('status')!='PASS':
        if backup and backup.exists():shutil.copy2(backup,dst);backup.unlink(missing_ok=True)
        return report
    unresolved=_release_input_errors(report);report['release_input_qa']={'version':'release-input-gate-v17.6','status':'PASS' if not unresolved else 'FAIL','errors':unresolved}
    if unresolved:
        report['status']='FAIL';report['stage']='release_input_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    manifest_qa=validate_approved_manifest(report,answers);report['approved_manifest_qa']=manifest_qa
    if manifest_qa.get('status')=='FAIL':
        report['status']='FAIL';report['stage']='approved_manifest_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    geometry=validate_layout_geometry(report.get('composition') or {});report['layout_geometry_qa']=geometry
    if geometry.get('status')!='PASS':
        report['status']='FAIL';report['stage']='layout_geometry_gate';_restore_or_remove(dst,backup)
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
    hardening_gates=(
        ('titleblock_qa',validate_titleblocks(dst,report.get('composition') or {}),'titleblock_gate'),
        ('safe_zone_qa',validate_safe_zones(dst,report.get('composition') or {}),'safe_zone_gate'),
        ('architectural_presentation_qa',validate_architectural_presentation(dst,report.get('composition') or {}),'architectural_presentation_gate'),
        ('equipment_linkage_qa',validate_equipment_linkage(dst,report.get('composition') or {}),'equipment_linkage_gate'),
        ('split_ac_visual_qa',validate_split_ac_visual_legibility(dst,report.get('composition') or {},dst.with_name(dst.stem+'-split-previews')),'split_ac_visual_gate'),
        ('detail_library_qa',validate_detail_library(dst,report.get('composition') or {}),'detail_library_gate'),
        ('content_completeness_qa',validate_content_completeness(dst,report.get('composition') or {}),'content_completeness_gate'),
    )
    for key,gate,stage in hardening_gates:
        report[key]=gate
        if gate.get('status')!='PASS':
            report['status']='FAIL';report['stage']=stage;_restore_or_remove(dst,backup)
            if backup:backup.unlink(missing_ok=True)
            return report
    population=validate_plan_board_population(dst,report,answers);report['plan_board_population_qa']=population
    if population.get('status')=='FAIL':
        report['status']='FAIL';report['stage']='plan_board_population_gate';_restore_or_remove(dst,backup)
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
    montage=create_montage_and_validate(dst,dst.with_name(dst.stem+'-montage.png'));report['montage_exact_reopen_qa']=montage
    if montage.get('status')!='PASS':
        report['status']='FAIL';report['stage']='montage_exact_reopen_gate';_restore_or_remove(dst,backup)
        if backup:backup.unlink(missing_ok=True)
        return report
    report['version']=MECHANICAL_PIPELINE_VERSION;report['status']='PASS'
    if backup:backup.unlink(missing_ok=True)
    return report
