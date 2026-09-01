"""Ten-step, fail-closed mechanical design governance contract."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
STANDARD=ROOT/'standards'


def _load(relative: str) -> dict:
    return json.loads((ROOT/relative).read_text(encoding='utf-8'))


def validate_repository_governance(root: Path=ROOT) -> dict:
    """Validate all ten permanent governance artifacts and locked test references."""
    root=Path(root);errors=[]
    governance=json.loads((root/'standards/mechanical-design-governance-v1.json').read_text())
    steps=governance.get('steps') or []
    if [x.get('id') for x in steps] != list(range(1,11)):errors.append('ten_step_sequence_invalid')
    for step in steps:
        artifact=root/str(step.get('artifact') or '')
        if not artifact.is_file():errors.append(f"governance_artifact_missing:{step.get('id')}:{step.get('artifact')}")
    registry=json.loads((root/'standards/capability-registry.json').read_text())
    test_text='\n'.join(p.read_text(encoding='utf-8') for p in (root/'tests').glob('test_*.py'))
    for capability in registry.get('capabilities') or []:
        cid=capability.get('id')
        if capability.get('status')!='LOCKED':errors.append(f'capability_not_locked:{cid}')
        if not capability.get('requirements'):errors.append(f'capability_requirements_empty:{cid}')
        tests=capability.get('tests') or []
        if not tests:errors.append(f'capability_tests_empty:{cid}')
        for test in tests:
            if f'def {test}(' not in test_text:errors.append(f'locked_test_missing:{cid}:{test}')
    project=json.loads((root/'standards/projects/project-1.contract.json').read_text())
    if project.get('contract_status')!='LOCKED':errors.append('project_contract_not_locked')
    forbidden=set((project.get('input') or {}).get('forbidden_generation_inputs') or [])
    if 'reference_mechanical_dxf' not in forbidden:errors.append('reference_mechanical_not_forbidden')
    baseline=json.loads((root/'standards/golden/project-1.baseline.json').read_text())
    if baseline.get('status')!='APPROVED':errors.append('golden_baseline_not_approved')
    snapshot=json.loads((root/'standards/releases/project-1/v18.0.snapshot.json').read_text())
    if snapshot.get('status')!='APPROVED' or snapshot.get('all_required_gates')!='PASS':errors.append('release_snapshot_not_approved')
    changes=json.loads((root/'standards/contract-changelog.json').read_text())
    if not any(x.get('status')=='APPROVED' for x in changes.get('changes') or []):errors.append('approved_contract_change_missing')
    return {'version':'mechanical-governance-v1.0','status':'PASS' if not errors else 'FAIL',
            'errors':sorted(set(errors)),'steps_checked':len(steps),'capabilities_checked':len(registry.get('capabilities') or [])}


def validate_release_against_contract(report: dict, project_contract: dict|None=None, baseline: dict|None=None) -> dict:
    """Block missing/SKIPPED gates and any semantic regression below the golden baseline."""
    project_contract=project_contract or _load('standards/projects/project-1.contract.json')
    baseline=baseline or _load('standards/golden/project-1.baseline.json');errors=[]
    if report.get('status')!='PASS':errors.append('release_status_not_pass')
    for gate in project_contract.get('required_gates') or []:
        status=str((report.get(gate) or {}).get('status') or 'MISSING').upper()
        if status!='PASS':errors.append(f'required_gate_not_pass:{gate}:{status}')
    composition=report.get('composition') or {};boards=composition.get('boards') or {};manifest=composition.get('manifest') or []
    split_visual=report.get('split_ac_visual_qa') or {};split_boards=split_visual.get('boards') or []
    split_units=[u for board in split_boards for u in (board.get('units') or [])]
    actual={
        'board_count':len(boards),
        'approved_plan_count':int((report.get('approved_manifest_qa') or {}).get('expected_plan_count') or 0),
        'titleblock_count':int((report.get('titleblock_qa') or {}).get('validated_titleblocks') or 0),
        'populated_plan_count':sum(x.get('status')=='PASS' for x in (report.get('plan_board_population_qa') or {}).get('boards') or []),
        'detail_sheet_count':sum(str(x.get('family') or '').upper()=='GENERAL_DETAIL' for x in manifest),
        'modelspace_entity_count':int((report.get('montage_exact_reopen_qa') or {}).get('entity_count') or 0),
        'split_ac_visual_board_count':sum(x.get('status')=='PASS' for x in split_boards),
        'split_ac_min_symbol_pixel_long_side':min((int(x.get('pixel_long_side') or max(int(x.get('pixel_width') or 0),int(x.get('pixel_height') or 0))) for x in split_units),default=0),
        'split_ac_min_symbol_pixel_short_side':min((int(x.get('pixel_short_side') or min(int(x.get('pixel_width') or 0),int(x.get('pixel_height') or 0))) for x in split_units),default=0),
    }
    for name,minimum in (baseline.get('minimums') or {}).items():
        if actual.get(name,0)<minimum:errors.append(f'golden_minimum_regression:{name}:{actual.get(name,0)}<{minimum}')
    families=Counter(str(x.get('family') or '').upper() for x in manifest)
    expected=baseline.get('exact_family_counts') or {}
    if dict(families)!=expected:errors.append('golden_family_manifest_changed_without_migration')
    return {'version':'mechanical-release-governance-gate-v1.0','status':'PASS' if not errors else 'FAIL',
            'errors':sorted(set(errors)),'actual':actual,'family_counts':dict(families)}
