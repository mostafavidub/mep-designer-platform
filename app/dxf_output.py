import os
import secrets
import shutil
import uuid
from collections import Counter
from pathlib import Path

import requests
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from . import main as legacy
from . import artifact_storage

app = legacy.app
_prev_flow_payload = legacy.flow_payload


def _purge_processing_files(pid: int, keep_output: bool = True):
    """Remove every local artifact; R2 is the only durable file store."""
    pdir = legacy.DATA_DIR / 'projects' / str(pid)
    try:
        durable_input = artifact_storage.input_is_durable(pid)
    except Exception:
        durable_input = False
    if durable_input:
        for path in (pdir / 'architecture.zip', pdir / 'architecture.dxf', pdir / 'input', pdir / '.upload_chunks'):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    shutil.rmtree(pdir / 'output', ignore_errors=True)
    shutil.rmtree(Path(os.getenv('CAD_OUTPUT_DIR', '/tmp/engitools-cad-output')) / str(pid), ignore_errors=True)
    if not keep_output:
        shutil.rmtree(pdir, ignore_errors=True)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            if project:
                project.name = f'Test project {pid} (expired)'
                project.questions = []
                project.answers = {}
                project.analysis = {}
                project.last_error = ''
                project.status = 'expired'
                for revision in db.query(legacy.Revision).filter(legacy.Revision.project_id == pid):
                    revision.pdf_path = ''
                    revision.error = ''
            db.commit()
        finally:
            db.close()


def validate_generated_manifest(drawing_set, design_reports):
    """Fail closed unless CAD covers every approved drawing requirement.

    V17 reports the actual authority sheets in ``composition.manifest``.  The
    older adapter only inspected ``authority_submission.layouts`` and therefore
    reported zero generated sheets even after every CAD QA gate had passed.
    Authority packages may also contain required cover/detail/note/schedule
    sheets in addition to the customer-facing system plans, so validate the
    approved system coverage instead of rejecting those mandatory additions.
    """
    if not (drawing_set or {}).get('approved'):
        raise RuntimeError('مانیفست نقشه‌های مکانیکی هنوز تأیید نشده است.')
    manifest = (drawing_set or {}).get('approved_manifest') or {}
    expected_sheets = manifest.get('sheets') or []
    expected_codes = [str(x.get('code') or '') for x in expected_sheets]
    expected_count = int(manifest.get('total_sheets') or -1)
    if expected_count < 1 or expected_count != len(expected_codes):
        raise RuntimeError('مانیفست تأییدشده نامعتبر است.')

    generated_codes = []
    generated_rows = []
    validation_states = []
    for report in design_reports or []:
        authority = report.get('authority_submission') or {}
        legacy_layouts = [str(x) for x in (authority.get('layouts') or [])]
        composition = report.get('composition') or {}
        rows = composition.get('manifest') or []
        if rows:
            generated_rows.extend(rows)
            generated_codes.extend(str(x.get('code') or '') for x in rows)
        else:
            generated_codes.extend(legacy_layouts)
        validation_states.append(
            authority.get('validation_status')
            or (report.get('dxf_qa') or {}).get('status')
            or report.get('status')
        )

    if not generated_codes or any(not code for code in generated_codes):
        raise RuntimeError(
            'Generation Failed: Proposal/CAD sheet mismatch. '
            f'Expected={expected_count} {expected_codes}; '
            f'Generated={len(generated_codes)} {generated_codes}'
        )
    if len(generated_codes) != len(set(generated_codes)):
        raise RuntimeError('Generation Failed: CAD issued duplicate sheet codes.')

    # New authority reports expose machine-readable family/level rows.  Verify
    # that all approved system plans and specials are covered while allowing
    # mandatory authority support sheets (cover, details, notes and schedules).
    if generated_rows:
        family_map = {
            'water_supply': 'WATER',
            'sanitary_vent': 'SANITARY_VENT',
            'heating': 'HEATING',
            'cooling': 'SPLIT_AC',
            'gas': 'GAS',
            'ventilation_exhaust': 'EXHAUST',
        }
        required = Counter()
        special_required = set()
        for sheet in expected_sheets:
            family = str(sheet.get('family') or '')
            drawing_type = str(sheet.get('drawing_type') or '')
            if drawing_type == 'floor_plan' and family in family_map:
                required[family_map[family]] += 1
            elif drawing_type in ('roof_plan', 'roof_rainwater') or str(sheet.get('code') or '').endswith('-RAIN'):
                special_required.add('ROOF')
            elif drawing_type == 'riser_diagram' or str(sheet.get('code') or '').endswith('-RISER'):
                special_required.add('PLUMBING_RISER')
        # V17 may report semantic family variants (for example GAS_PLAN or
        # GAS_DISTRIBUTION) while the approved planner uses canonical family
        # names. Normalize report variants before comparing coverage so the
        # same issued sheet is not rejected because of adapter vocabulary.
        aliases = {
            'WATER': ('WATER', 'COLD_WATER', 'HOT_WATER', 'DOMESTIC_WATER'),
            'SANITARY_VENT': ('SANITARY_VENT', 'SANITARY', 'DRAINAGE', 'WASTE'),
            'HEATING': ('HEATING', 'HYDRONIC', 'RADIATOR'),
            'SPLIT_AC': ('SPLIT_AC', 'COOLING', 'HVAC', 'AIR_CONDITION'),
            'GAS': ('GAS', 'FUEL_GAS'),
            'EXHAUST': ('EXHAUST', 'VENTILATION'),
            'ROOF': ('ROOF', 'RAINWATER'),
            'PLUMBING_RISER': ('PLUMBING_RISER', 'RISER'),
        }

        def row_evidence(row):
            return ' '.join(str(row.get(key) or '') for key in (
                'code', 'family', 'system', 'drawing_type', 'drawing_role', 'label', 'title'
            )).upper().replace('-', '_').replace(' ', '_')

        def canonical_family(row):
            evidence = row_evidence(row)
            for canonical, variants in aliases.items():
                if any(variant in evidence for variant in variants):
                    return canonical
            return str(row.get('family') or '').upper()

        actual = Counter(canonical_family(row) for row in generated_rows)
        actual_specials = set()
        for row in generated_rows:
            evidence = row_evidence(row)
            if 'ROOF' in evidence or 'RAINWATER' in evidence or str(row.get('code') or '').endswith('-RAIN'):
                actual_specials.add('ROOF')
            if 'RISER' in evidence or str(row.get('code') or '').endswith('-RISER'):
                actual_specials.add('PLUMBING_RISER')
        missing = {
            family: count - actual.get(family, 0)
            for family, count in required.items()
            if actual.get(family, 0) < count
        }
        missing_specials = sorted(x for x in special_required if x not in actual_specials)
        if missing or missing_specials:
            raise RuntimeError(
                'Generation Failed: approved mechanical sheet coverage is incomplete. '
                f'Missing={missing}; MissingSpecials={missing_specials}'
            )
    elif generated_codes != expected_codes or len(generated_codes) != expected_count:
        # Preserve strict compatibility for legacy CAD reports which have no
        # semantic manifest and therefore cannot prove equivalent coverage.
        raise RuntimeError(
            'Generation Failed: Proposal/CAD sheet mismatch. '
            f'Expected={expected_count} {expected_codes}; '
            f'Generated={len(generated_codes)} {generated_codes}'
        )
    if any(x != 'PASS' for x in validation_states):
        raise RuntimeError('Generation Failed: CAD manifest validation did not PASS.')
    return {
        'expected_sheets': expected_count,
        'generated_sheets': len(generated_codes),
        'status': 'PASS',
        'manifest_id': manifest.get('manifest_id'),
    }


def _cad_error_message(response):
    try:
        payload = response.json()
        detail = payload.get('detail') if isinstance(payload, dict) else None
    except Exception:
        detail = None
    message = str(detail or 'موتور طراحی اطلاعات پروژه را کافی تشخیص نداد.')
    translations = {
        'Authority-ready mechanical generation blocked: unresolved engineering inputs:':
            'اطلاعات فنی لازم برای طراحی کامل نشده است:',
        'water inlet pressure': 'فشار مبنای آب ورودی',
        'project location/climate': 'شهر و شرایط اقلیمی پروژه',
        'floor heights / false-ceiling constraints': 'ارتفاع طبقات و سقف کاذب',
        'sanitary outlet': 'نوع خروجی فاضلاب',
        'resolved heating/cooling equipment schedule': 'انتخاب تجهیزات گرمایش و سرمایش',
        'gas appliance loads, inlet pressure and meter/regulator location':
            'ظرفیت تجهیزات گازسوز و محل کنتور/رگلاتور',
        'Mechanical technical design QA failed': 'کنترل فنی نقشه مکانیک کامل نشد',
        'fixture_and_symbol_traceability': 'تعداد و جانمایی تجهیزات بهداشتی',
        'water_hydraulic_design': 'محاسبات هیدرولیکی آب',
        'sanitary_vent_design': 'محاسبات فاضلاب و ونت',
        'heating_cooling_equipment_design': 'طراحی تجهیزات گرمایش و سرمایش',
        'ventilation_design': 'محاسبات تهویه',
        'roof_drainage_design': 'محاسبات آب باران بام',
        'Compact mechanical output': 'پاک‌سازی خروجی مکانیک',
    }
    for source, target in translations.items():
        message = message.replace(source, target)
    return f'طراحی متوقف شد: {message}'


def run_design_dxf(project_id, revision_id):
    db = legacy.Session()
    p = db.get(legacy.Project, project_id)
    r = db.get(legacy.Revision, revision_id)
    try:
        p.status = 'designing'
        r.status = 'processing'
        db.commit()
        if not legacy.CAD_DESIGNER_URL:
            raise RuntimeError('موتور CAD Designer هنوز به این سرویس متصل نشده است.')

        pdir = legacy.DATA_DIR / 'projects' / str(p.id)
        discipline = (p.answers or {}).get('discipline', (p.analysis or {}).get('discipline', 'mechanical'))
        if discipline not in legacy.OUTPUT_SCOPES:
            raise RuntimeError('رشته پروژه معتبر نیست.')
        scope = legacy.OUTPUT_SCOPES[discipline]
        design_answers = dict(p.answers or {})
        approved_manifest = ((p.analysis or {}).get('drawing_set') or {}).get('approved_manifest')
        if discipline == 'mechanical':
            if not approved_manifest:
                raise RuntimeError('Approved mechanical drawing manifest is missing from the project workflow.')
            # The CAD engine reads the approved contract from answers. Keeping it
            # only in output_scope made the compositor reject every approved job.
            design_answers['_approved_drawing_manifest'] = approved_manifest
            # Carry the exact fixture blocks found by the browser upload analyzer
            # into the CAD transaction.  The engine still accepts them only when
            # their original coordinates fall inside a reconstructed room; this
            # preserves provenance and avoids inventing installed fixtures.
            fixture_evidence = []
            for analyzed_file in ((p.analysis or {}).get('files') or []):
                for item in (analyzed_file.get('fixture_blocks') or []):
                    if item.get('kind') and item.get('x') is not None and item.get('y') is not None:
                        fixture_evidence.append({
                            'kind': item.get('kind'), 'name': item.get('name'),
                            'x': item.get('x'), 'y': item.get('y'),
                            'source_file': analyzed_file.get('file'),
                        })
            design_answers['_plan_fixture_evidence'] = fixture_evidence
        payload = {
            'project_id': str(p.id),
            'discipline': discipline,
            'architecture_dir': str(pdir / 'input'),
            'answers': design_answers,
            'plan_analysis': p.analysis,
            'rulebook_path': legacy.RULEBOOK_PATH,
            'revision': r.revision_no,
            'revision_instructions': r.feedback,
            'output_scope': {
                'discipline': discipline,
                'label': scope['label'],
                'systems': scope['systems'],
                'only_this_discipline': True,
                'include_other_disciplines': False,
                'approved_manifest': approved_manifest,
            },
        }
        resp = requests.post(legacy.CAD_DESIGNER_URL + '/design', json=payload, timeout=3600)
        if not resp.ok:
            message = _cad_error_message(resp)
            print(f'[mechanical-design] CAD HTTP {resp.status_code}: {message}', flush=True)
            raise RuntimeError(message)
        data = resp.json()
        if data.get('discipline') and data['discipline'] != discipline:
            raise RuntimeError('خروجی CAD Designer با رشته انتخاب‌شده پروژه تطابق ندارد.')

        if discipline == 'mechanical':
            validation = validate_generated_manifest(
                (p.analysis or {}).get('drawing_set') or {},
                data.get('design_reports') or [],
            )
            analysis = dict(p.analysis or {})
            analysis['last_generation_validation'] = validation
            p.analysis = analysis

            reports = data.get('design_reports') or []
            # ``compact_output`` was emitted by the transitional compositor but
            # is optional in the V17 authority report.  The enforceable compact
            # contract is: exactly one generated consolidated DXF, copy only
            # that named file, then reopen/validate the copied artifact below.
            cleanup_states = [
                report.get('compact_output') for report in reports
                if report.get('compact_output') is not None
            ]
            if len(data.get('generated_files') or []) != 1:
                raise RuntimeError(
                    'پاک‌سازی خروجی ناموفق بود: خروجی مکانیک باید دقیقاً یک DXF تجمیعی داشته باشد.'
                )
            if cleanup_states and any(item.get('status') != 'PASS' for item in cleanup_states):
                raise RuntimeError('پاک‌سازی خروجی مکانیک توسط کنترل نهایی تأیید نشد.')
            if any(int(item.get('architecture_source_files_packaged') or 0) != 0 for item in cleanup_states):
                raise RuntimeError('فایل معماری خام نباید داخل بسته خروجی مکانیک قرار گیرد.')

        generated = data.get('generated_files') or []
        package_path = Path(data.get('zip_path') or '')
        if not generated:
            raise RuntimeError('موتور CAD هیچ فایل DXF تولید نکرد.')

        # Validate and upload directly from the ephemeral CAD workspace.
        # No final-artifact copy is ever created on the persistent Volume.
        if len(generated) == 1:
            dst = package_path.parent / generated[0]
            if not dst.exists():
                raise RuntimeError(f'فایل DXF تولیدشده پیدا نشد: {generated[0]}')
        else:
            dst = package_path
            if not dst.exists():
                raise RuntimeError('بسته DXF تولیدشده پیدا نشد.')

        artifact_qa = artifact_storage.validate_output_artifact(dst)
        analysis = dict(p.analysis or {})
        analysis['last_artifact_validation'] = artifact_qa
        p.analysis = analysis

        durable_uri = artifact_storage.upload_output(
            p.id, r.revision_no, discipline, dst,
        )
        if not durable_uri:
            raise RuntimeError('ذخیره خروجی نهایی در R2 تأیید نشد؛ فایل محلی نگهداری نشد.')
        dst.unlink(missing_ok=True)

        # Reuse the existing artifact-path column for compatibility with the
        # current database schema; final artifacts live only in R2.
        r.pdf_path = durable_uri
        r.status = 'ready'
        r.error = ''
        p.status = 'ready'
        p.current_revision = r.revision_no
        p.last_error = ''
        db.commit()
        _purge_processing_files(p.id, keep_output=True)
    except Exception as exc:
        r.status = 'failed'
        r.error = str(exc)
        # A failed CAD run is never a completed analysis. Returning it to
        # ready_to_design makes the UI ask for the same start action forever
        # and hides the actual 422/500 reason from the customer.
        p.status = 'failed'
        p.last_error = str(exc)
        db.commit()
        _purge_processing_files(p.id, keep_output=True)
    finally:
        db.close()


def flow_payload_dxf(p):
    data = _prev_flow_payload(p)
    ready = p.status == 'ready' and bool(p.current_revision)
    output_url = f'/projects/{p.id}/output/{p.current_revision}' if ready else None
    data['output_url'] = output_url
    data['output_format'] = 'DXF'
    # Temporary compatibility for the existing modal JS.
    data['pdf_url'] = output_url
    return data


def _resolve_existing_cad_artifact(pid, rev, discipline, stored_path):
    if str(stored_path or '').startswith('s3://'):
        return str(stored_path)
    path = Path(stored_path or '')
    if path.exists() and path.suffix.lower() in ('.dxf', '.zip'):
        return path

    # Older revisions stored the PDF path even though the CAD engine also wrote
    # the generated DXF package. Reuse that existing CAD artifact immediately.
    engine_dir = Path('/data/cad-engine') / str(pid) / f'R{rev:03d}' / discipline
    if engine_dir.exists():
        dxfs = sorted(engine_dir.glob(f'*_{discipline}.dxf'))
        if len(dxfs) == 1:
            return dxfs[0]
        package = engine_dir / f'EngiTools_{pid}_{discipline}_R{rev}_DXF.zip'
        if package.exists():
            return package
    return None


legacy.run_design = run_design_dxf
legacy.flow_payload = flow_payload_dxf


@app.get('/projects/{pid}/output/{rev}')
def get_cad_output(pid: int, rev: int, request: Request):
    user = legacy.current_user(request)
    db, p = legacy.own_project(pid, user.id)
    if not p:
        raise HTTPException(404)
    r = db.query(legacy.Revision).filter(
        legacy.Revision.project_id == p.id,
        legacy.Revision.revision_no == rev,
    ).first()
    discipline = (p.answers or {}).get('discipline', (p.analysis or {}).get('discipline', 'mechanical'))
    db.close()
    if not r or r.status != 'ready':
        raise HTTPException(404)

    path = _resolve_existing_cad_artifact(pid, rev, discipline, r.pdf_path)
    if not path:
        raise HTTPException(404, 'DXF output is not available for this revision; create a new revision.')

    if isinstance(path, str) and path.startswith('s3://'):
        suffix = Path(path).suffix.lower()
        filename = f'EngiTools_{discipline}_{pid}_R{rev}.dxf' if suffix == '.dxf' else f'EngiTools_{discipline}_{pid}_R{rev}_DXF.zip'
        if not artifact_storage.configured():
            raise HTTPException(503, 'فضای ذخیره‌سازی خروجی موقتاً در دسترس نیست.')
        return RedirectResponse(artifact_storage.presigned_download(path, filename), status_code=307)

    if path.suffix.lower() == '.dxf':
        media_type = 'application/dxf'
        filename = f'EngiTools_{discipline}_{pid}_R{rev}.dxf'
    else:
        media_type = 'application/zip'
        filename = f'EngiTools_{discipline}_{pid}_R{rev}_DXF.zip'
    return FileResponse(path, media_type=media_type, filename=filename)


@app.post('/projects/{pid}/output/{rev}/delete')
def delete_cad_output(pid: int, rev: int, request: Request):
    """Delete a retained final artifact only on the owner's explicit request."""
    user = legacy.current_user(request)
    db, project = legacy.own_project(pid, user.id)
    if not project:
        raise HTTPException(404)
    try:
        revision = db.query(legacy.Revision).filter(
            legacy.Revision.project_id == project.id,
            legacy.Revision.revision_no == rev,
        ).first()
        if not revision or not revision.pdf_path:
            raise HTTPException(404)
        stored = str(revision.pdf_path)
        if stored.startswith('s3://'):
            artifact_storage.delete_artifact(stored)
        else:
            path = Path(stored)
            project_root = (legacy.DATA_DIR / 'projects' / str(pid)).resolve()
            if path.exists() and project_root in path.resolve().parents:
                path.unlink(missing_ok=True)
        revision.pdf_path = ''
        revision.status = 'deleted'
        revision.error = ''
        if project.current_revision == rev:
            project.current_revision = 0
            project.status = 'ready_to_design'
        db.commit()
    finally:
        db.close()
    return RedirectResponse(f'/projects/{pid}', status_code=303)


@app.get('/internal/maintenance/projects/{pid}/output/{rev}')
def maintenance_get_cad_output(pid: int, rev: int, request: Request):
    """Token-protected artifact download used for production E2E verification."""
    expected = os.getenv('INTERNAL_MAINTENANCE_TOKEN', '')
    supplied = request.headers.get('x-maintenance-token', '')
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(404)
    db = legacy.Session()
    try:
        project = db.get(legacy.Project, pid)
        revision = db.query(legacy.Revision).filter(
            legacy.Revision.project_id == pid,
            legacy.Revision.revision_no == rev,
        ).first()
        if not project or not revision or revision.status != 'ready':
            raise HTTPException(404)
        discipline = (project.answers or {}).get(
            'discipline', (project.analysis or {}).get('discipline', 'mechanical')
        )
        path = _resolve_existing_cad_artifact(pid, rev, discipline, revision.pdf_path)
    finally:
        db.close()
    if not isinstance(path, Path) or not path.exists():
        raise HTTPException(404)
    project_root = (legacy.DATA_DIR / 'projects' / str(pid)).resolve()
    resolved = path.resolve()
    if project_root not in resolved.parents:
        raise HTTPException(404)
    return FileResponse(
        resolved, media_type='application/dxf',
        filename=f'EngiTools_{discipline}_{pid}_R{rev}.dxf',
    )


@app.post('/internal/maintenance/upload-test')
async def maintenance_upload_test(request: Request):
    """Upload the exact customer artifact through the production save path."""
    expected = os.getenv('INTERNAL_MAINTENANCE_TOKEN', '')
    supplied = request.headers.get('x-maintenance-token', '')
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(404)
    form = await request.form()
    upload = form.get('file')
    discipline = str(form.get('discipline') or 'mechanical')
    if upload is None or discipline not in legacy.DISCIPLINES:
        raise HTTPException(400)
    db = legacy.Session()
    try:
        user = legacy.User(email=f'maintenance-{uuid.uuid4().hex}@local')
        db.add(user); db.flush()
        project = legacy.Project(
            user_id=user.id, name='Production upload integrity test',
            questions=legacy.qlist(legacy.DISCIPLINES[discipline]['questions']),
            answers={'discipline': discipline}, status='uploading', last_error='',
        )
        db.add(project); db.commit(); db.refresh(project)
        legacy.save_project_input(project.id, upload)
        project.status='analyzing'; db.commit()
        pid=project.id
    finally:
        db.close()
    legacy.schedule_analysis(pid)
    return {'ok': True, 'project_id': pid}
