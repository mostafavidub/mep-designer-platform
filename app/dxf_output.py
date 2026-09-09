import base64, io, json, os, shutil, tempfile, zipfile
from pathlib import Path
from types import SimpleNamespace

import requests
from fastapi import HTTPException

from . import main as legacy
from .design_progress import set_project_progress
from .artifact_storage import persist_final_artifact, delete_local_copy_after_remote_verification
from .mechanical_basis_contract import reopen_missing_mechanical_inputs
from cad_engine.version_manifest import active_version_manifest


def _cad_error_message(resp):
    try:
        body=resp.json(); detail=body.get('detail') if isinstance(body,dict) else None
        if isinstance(detail,dict):
            missing=detail.get('missing_inputs') or []
            if missing: return 'ورودی‌های مهندسی بیشتری لازم است: '+', '.join(str(x) for x in missing)
            return str(detail.get('message') or detail.get('code') or detail)
        if detail: return str(detail)
    except Exception: pass
    return f'CAD Designer HTTP {resp.status_code}'


def _cad_rejection_diagnostic(resp):
    try: body=resp.json()
    except Exception: return {'http_status':resp.status_code,'detail':'unparseable'}
    detail=body.get('detail') if isinstance(body,dict) else body
    if not isinstance(detail,dict): return {'http_status':resp.status_code,'detail':detail}
    return {
        'http_status':resp.status_code,
        'code':detail.get('code'),'status':detail.get('status'),'stage':detail.get('stage'),
        'missing_inputs':detail.get('missing_inputs') or [],
        'engineering_acceptance':detail.get('engineering_acceptance'),
        'pipeline_qa':detail.get('pipeline_qa'),'authority_qa':detail.get('authority_qa'),
        'v19_qa':detail.get('v19_qa'),
    }


def _post_to_compatible_cad(payload):
    """Use the canonical CAD process shipped in this exact deployment."""
    if os.getenv('COBUILT_CAD_IN_PROCESS', '').strip() == '1':
        from cad_engine import main as _canonical_entrypoint  # noqa: F401
        from cad_engine.main_v15 import design

        class LocalResponse:
            def __init__(self, status_code, body):
                self.status_code = status_code; self.ok = status_code < 400; self._body = body
            def json(self): return self._body

        try:
            local_payload = {'architecture_archive_b64': None, **payload}
            return LocalResponse(200, design(SimpleNamespace(**local_payload)))
        except HTTPException as exc:
            return LocalResponse(exc.status_code, {'detail': exc.detail})
    cobuilt = os.getenv('COBUILT_CAD_DESIGNER_URL', 'http://127.0.0.1:8081').rstrip('/')
    token = os.getenv('COBUILT_CAD_SERVICE_TOKEN', '').strip()
    headers = {'x-cad-service-token': token} if token else None
    return requests.post(cobuilt + '/design', json=payload, headers=headers, timeout=3600)


def _attach_remote_architecture(payload, project_dir):
    """Carry preserved inputs to a stateless CAD service over private HTTP."""
    target = os.getenv('COBUILT_CAD_DESIGNER_URL', 'http://127.0.0.1:8081').lower()
    if os.getenv('COBUILT_CAD_IN_PROCESS', '').strip() == '1' or target.startswith(('http://127.0.0.1', 'http://localhost')):
        return payload
    project_dir = Path(project_dir); archive = project_dir / 'architecture.zip'
    if archive.is_file(): raw = archive.read_bytes()
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for source in sorted((project_dir / 'input').rglob('*.dxf')):
                if source.is_file() and '__MACOSX' not in source.parts and not source.name.startswith(('._', '.')):
                    bundle.write(source, arcname=source.name)
        raw = buffer.getvalue()
    if not raw: return payload
    transferred = dict(payload); transferred['architecture_dir'] = None
    transferred['architecture_archive_b64'] = base64.b64encode(raw).decode('ascii')
    return transferred


def _materialize_remote_cad_artifact(data):
    generated=list(data.get('generated_files') or []); package_path=Path(data.get('zip_path') or '')
    encoded=data.get('zip_base64') or ''
    if not encoded:
        artifact=(package_path.parent/generated[0]) if len(generated)==1 else package_path
        return None,package_path,artifact
    root=Path(tempfile.mkdtemp(prefix='engitools-cad-transfer-'))
    try:
        archive=root/'transfer.zip'; archive.write_bytes(base64.b64decode(encoded,validate=True))
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                candidate=(root/member.filename).resolve()
                if root.resolve() not in candidate.parents or member.is_dir(): raise RuntimeError('بسته انتقال خروجی CAD معتبر نیست.')
            bundle.extractall(root)
        artifact=(root/generated[0]) if len(generated)==1 else archive
        return root,archive,artifact
    except Exception:
        shutil.rmtree(root,ignore_errors=True); raise


def _v19_contract_from_analysis(analysis):
    """Project analysis -> complete v19 authority envelope without inventing evidence.

    Missing calculations or graph evidence is preserved as missing; the v19
    authority adapter will return INPUT_REQUIRED instead of falling back to a
    legacy engineering decision path.
    """
    analysis=dict(analysis or {})
    pmm=analysis.get('project_mechanical_model') or {}
    calculation_rows=(analysis.get('calculation_rows_v19') if 'calculation_rows_v19' in analysis else
                      analysis.get('calculation_rows') if 'calculation_rows' in analysis else
                      analysis.get('engineering_calculation_rows'))
    active_systems=analysis.get('active_systems_v19')
    return {
        'project_mechanical_model': pmm,
        'calculation_rows': calculation_rows,
        'active_systems': active_systems,
        'coordination_inputs': analysis.get('coordination_inputs_v19') or {},
        'route_request': analysis.get('route_request_v19') or {},
        'equipment_requirements': analysis.get('equipment_requirements_v19') or {},
        'manufacturer_catalogue': analysis.get('manufacturer_catalogue_v19') or [],
        'manufacturer_database_records': analysis.get('manufacturer_database_records_v19'),
        'equipment_selection_checks': analysis.get('equipment_selection_checks_v19'),
        'declared_equipment_ids': analysis.get('declared_equipment_ids_v19') or [],
        'detail_specs': analysis.get('detail_specs_v19') or [],
        'final_parametric_detail_specs': analysis.get('final_parametric_detail_specs_v19') or [],
        'network_graph': analysis.get('network_graph_v19') or {},
        'annotation_solver': analysis.get('annotation_solver_v19'),
        'submission_checks': analysis.get('submission_checks_v19'),
        'engineer_review': analysis.get('engineer_review_v19'),
        'quality_metrics': analysis.get('quality_metrics_v19') or {},
        'golden_result': analysis.get('golden_result_v19'),
        'pmm_schema': pmm.get('schema'),
    }


def run_design_dxf(project_id, revision_id):
    db = legacy.Session(); p = db.get(legacy.Project, project_id); r = db.get(legacy.Revision, revision_id)
    transfer_root = None
    try:
        p.status = 'designing'; r.status = 'processing'; set_project_progress(p, 'preparing_inputs'); db.commit()
        if not os.getenv('COBUILT_CAD_DESIGNER_URL', 'http://127.0.0.1:8081').strip():
            raise RuntimeError('موتور CAD Designer هنوز به این سرویس متصل نشده است.')
        pdir = legacy.DATA_DIR / 'projects' / str(p.id)
        discipline = (p.answers or {}).get('discipline', (p.analysis or {}).get('discipline', 'mechanical'))
        if discipline not in legacy.OUTPUT_SCOPES: raise RuntimeError('رشته پروژه معتبر نیست.')
        scope = legacy.OUTPUT_SCOPES[discipline]; design_answers = dict(p.answers or {})
        approved_manifest = ((p.analysis or {}).get('drawing_set') or {}).get('approved_manifest')
        if discipline == 'mechanical':
            if not approved_manifest: raise RuntimeError('Approved mechanical drawing manifest is missing from the project workflow.')
            design_answers['_approved_drawing_manifest'] = approved_manifest
            fixture_evidence = []
            for analyzed_file in ((p.analysis or {}).get('files') or []):
                for item in (analyzed_file.get('fixture_blocks') or []):
                    if item.get('kind') and item.get('x') is not None and item.get('y') is not None:
                        fixture_evidence.append({'kind':item.get('kind'),'name':item.get('name'),'x':item.get('x'),'y':item.get('y'),'source_file':analyzed_file.get('file')})
            design_answers['_plan_fixture_evidence'] = fixture_evidence
            design_answers['_plan_analysis'] = p.analysis
            design_answers['_runtime_contract'] = active_version_manifest()
            design_answers['_v19_input_contract'] = _v19_contract_from_analysis(p.analysis)
        set_project_progress(p, 'validating_contract'); db.commit()
        payload = {
            'project_id': str(p.id),'discipline': discipline,'architecture_dir': str(pdir / 'input'),
            'answers': design_answers,'plan_analysis': p.analysis,'rulebook_path': legacy.RULEBOOK_PATH,
            'revision': r.revision_no,'revision_instructions': r.feedback,
            'output_scope': {'discipline':discipline,'label':scope['label'],'systems':scope['systems'],'only_this_discipline':True,'include_other_disciplines':False,'approved_manifest':approved_manifest},
        }
        if discipline == 'mechanical':
            for stage in ('coordination_v19','manufacturer_v19','documentation_v19'):
                set_project_progress(p, stage); db.commit()
        set_project_progress(p, 'engine_designing'); db.commit(); payload = _attach_remote_architecture(payload, pdir)
        resp = _post_to_compatible_cad(payload)
        if not resp.ok:
            message = _cad_error_message(resp)
            print('[mechanical-design] CAD rejection diagnostic: '+json.dumps(_cad_rejection_diagnostic(resp),ensure_ascii=True,sort_keys=True),flush=True)
            print(f'[mechanical-design] CAD HTTP {resp.status_code}: {message}',flush=True)
            if discipline == 'mechanical': reopen_missing_mechanical_inputs(p, resp.json() if hasattr(resp,'json') else {})
            raise RuntimeError(message)
        data=resp.json(); active_versions=active_version_manifest()
        if discipline=='mechanical':
            reports=data.get('design_reports') or []
            for report in reports:
                if report.get('pipeline_authority') != 'mechanical-v19': raise RuntimeError('Mechanical CAD response did not come from authoritative v19 runtime.')
                if report.get('engineering_authority') != 'PMM_V3_V19': raise RuntimeError('Mechanical CAD response is missing PMM v3 engineering authority.')
                if report.get('legacy_renderer_role') != 'CAD_MATERIALIZER_ONLY': raise RuntimeError('Legacy renderer attempted to retain engineering authority.')
                if report.get('executed_versions') != active_versions: raise RuntimeError('Mechanical CAD runtime version does not match site runtime.')
                preflight=report.get('v19_traceability_preflight') or {}
                if preflight.get('status')!='PASS' or preflight.get('zero_mismatch') is not True: raise RuntimeError('Mechanical traceability reconciliation did not pass.')
        transfer_root,package_path,artifact=_materialize_remote_cad_artifact(data)
        if not artifact or not artifact.exists(): raise RuntimeError('خروجی نهایی CAD ساخته نشد.')
        set_project_progress(p,'artifact_qa'); db.commit()
        final=persist_final_artifact(p.id,r.revision_no,discipline,artifact)
        r.pdf_path=final; r.status='completed'; p.status='completed'; p.last_error=''; set_project_progress(p,'completed'); db.commit()
        delete_local_copy_after_remote_verification(artifact,final)
    except Exception as exc:
        db.rollback(); p=db.get(legacy.Project,project_id); r=db.get(legacy.Revision,revision_id)
        if p and r:
            p.status='needs_input' if 'ورودی‌های مهندسی' in str(exc) or 'INPUT_REQUIRED' in str(exc) else 'failed'
            p.last_error=str(exc); r.status='failed'; r.error=str(exc); db.commit()
    finally:
        if transfer_root: shutil.rmtree(transfer_root,ignore_errors=True)
        db.close()
