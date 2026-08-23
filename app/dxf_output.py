import shutil
from pathlib import Path

import requests
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from . import main as legacy

app = legacy.app
_prev_flow_payload = legacy.flow_payload


def validate_generated_manifest(drawing_set, design_reports):
    """Fail closed unless CAD issued exactly the customer-approved sheets."""
    if not (drawing_set or {}).get('approved'):
        raise RuntimeError('مانیفست نقشه‌های مکانیکی هنوز تأیید نشده است.')
    manifest = (drawing_set or {}).get('approved_manifest') or {}
    expected_sheets = manifest.get('sheets') or []
    expected_codes = [str(x.get('code') or '') for x in expected_sheets]
    expected_count = int(manifest.get('total_sheets') or -1)
    if expected_count < 1 or expected_count != len(expected_codes):
        raise RuntimeError('مانیفست تأییدشده نامعتبر است.')

    generated_codes = []
    validation_states = []
    for report in design_reports or []:
        authority = report.get('authority_submission') or {}
        generated_codes.extend(str(x) for x in (authority.get('layouts') or []))
        validation_states.append(authority.get('validation_status'))
    if generated_codes != expected_codes or len(generated_codes) != expected_count:
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
        payload = {
            'project_id': str(p.id),
            'discipline': discipline,
            'architecture_dir': str(pdir / 'input'),
            'answers': p.answers,
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
                'approved_manifest': ((p.analysis or {}).get('drawing_set') or {}).get('approved_manifest'),
            },
        }
        resp = requests.post(legacy.CAD_DESIGNER_URL + '/design', json=payload, timeout=3600)
        resp.raise_for_status()
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

        generated = data.get('generated_files') or []
        package_path = Path(data.get('zip_path') or '')
        if not generated:
            raise RuntimeError('موتور CAD هیچ فایل DXF تولید نکرد.')

        out = pdir / 'output' / f'rev_{r.revision_no:03d}'
        out.mkdir(parents=True, exist_ok=True)
        if len(generated) == 1:
            src = package_path.parent / generated[0]
            if not src.exists():
                raise RuntimeError(f'فایل DXF تولیدشده پیدا نشد: {generated[0]}')
            dst = out / f'{discipline}_design.dxf'
            shutil.copy2(src, dst)
        else:
            if not package_path.exists():
                raise RuntimeError('بسته DXF تولیدشده پیدا نشد.')
            dst = out / f'{discipline}_design_DXF.zip'
            shutil.copy2(package_path, dst)

        # Reuse the existing artifact-path column for compatibility with the
        # current database schema; the file stored here is now DXF/ZIP, not PDF.
        r.pdf_path = str(dst)
        r.status = 'ready'
        r.error = ''
        p.status = 'ready'
        p.current_revision = r.revision_no
        p.last_error = ''
        db.commit()
    except Exception as exc:
        r.status = 'failed'
        r.error = str(exc)
        p.status = 'failed'
        p.last_error = str(exc)
        db.commit()
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

    if path.suffix.lower() == '.dxf':
        media_type = 'application/dxf'
        filename = f'EngiTools_{discipline}_{pid}_R{rev}.dxf'
    else:
        media_type = 'application/zip'
        filename = f'EngiTools_{discipline}_{pid}_R{rev}_DXF.zip'
    return FileResponse(path, media_type=media_type, filename=filename)
