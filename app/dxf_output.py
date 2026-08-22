import shutil
from pathlib import Path

import requests
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from . import main as legacy

app = legacy.app
_prev_flow_payload = legacy.flow_payload


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
            },
        }
        resp = requests.post(legacy.CAD_DESIGNER_URL + '/design', json=payload, timeout=3600)
        resp.raise_for_status()
        data = resp.json()
        if data.get('discipline') and data['discipline'] != discipline:
            raise RuntimeError('خروجی CAD Designer با رشته انتخاب‌شده پروژه تطابق ندارد.')

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

        # Keep using the existing database field for backwards compatibility;
        # the stored artifact is now DXF (or a ZIP of DXFs), not a PDF.
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
    # Keep the legacy key temporarily because the current modal JS reads it.
    data['pdf_url'] = output_url
    return data


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
    if not r or r.status != 'ready' or not r.pdf_path:
        raise HTTPException(404)

    path = Path(r.pdf_path)
    if not path.exists() or path.suffix.lower() not in ('.dxf', '.zip'):
        raise HTTPException(404, 'DXF output is not available for this revision; create a new revision.')

    if path.suffix.lower() == '.dxf':
        media_type = 'application/dxf'
        filename = f'EngiTools_{discipline}_{pid}_R{rev}.dxf'
    else:
        media_type = 'application/zip'
        filename = f'EngiTools_{discipline}_{pid}_R{rev}_DXF.zip'
    return FileResponse(path, media_type=media_type, filename=filename)
