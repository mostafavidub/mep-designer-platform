import hashlib
import shutil
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from . import main as legacy

CHUNK_SIZE_MAX = 2 * 1024 * 1024
MAX_CHUNKS = 400


def _clear_abandoned_chunks():
    """Legacy startup cleanup is disabled; queue cleanup handles transient CAD files safely."""
    return


def register_resumable_upload_routes(app):
    _clear_abandoned_chunks()
    @app.post('/api/upload/init/{discipline}')
    async def init_resumable_upload(discipline: str, request: Request):
        if discipline not in legacy.DISCIPLINES:
            raise HTTPException(404)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            user = legacy.current_user(request)
            db = legacy.Session()
            project_name = (payload.get('name') or '').strip() or f"{legacy.DISCIPLINES[discipline]['title']} - upload"
            project = legacy.Project(
                user_id=user.id,
                name=project_name,
                questions=legacy.qlist(legacy.DISCIPLINES[discipline]['questions']),
                answers={'discipline': discipline},
                status='uploading',
                last_error='',
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            pid = project.id
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if 'no space left on device' in lowered or getattr(exc, 'errno', None) == 28:
                raise HTTPException(507, 'فضای Volume سرور پر است.') from exc
            if 'database or disk is full' in lowered:
                usage = shutil.disk_usage(str(legacy.DATA_DIR))
                sizes = {}
                for root in Path(legacy.DATA_DIR).iterdir():
                    try:
                        sizes[root.name] = root.stat().st_size if root.is_file() else sum(
                            item.stat().st_size for item in root.rglob('*') if item.is_file()
                        )
                    except OSError:
                        pass
                largest = sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:5]
                summary = '، '.join(f'{name}={size}' for name, size in largest)
                raise HTTPException(507, f'فضای Volume پر است؛ آزاد={usage.free}؛ {summary}') from exc
            if 'readonly database' in lowered:
                raise HTTPException(500, 'دیتابیس فقط‌خواندنی شده است.') from exc
            if 'database is locked' in lowered:
                raise HTTPException(503, 'دیتابیس موقتاً قفل است.') from exc
            if 'database' in lowered or 'sql' in lowered:
                raise HTTPException(500, f'خطای دیتابیس هنگام ساخت پروژه: {type(exc).__name__}') from exc
            raise HTTPException(500, f'ساخت پروژه ناموفق بود: {type(exc).__name__}') from exc
        finally:
            if 'db' in locals():
                db.close()
        return JSONResponse({
            'ok': True,
            'project_id': pid,
            'chunk_url': f'/api/upload/{pid}/chunk',
            'flow_url': f'/projects/{pid}/flow',
        })

    @app.post('/api/upload/{pid}/chunk')
    async def upload_chunk(pid: int, request: Request):
        user = legacy.current_user(request)
        db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        try:
            try:
                index = int(request.query_params.get('index', '-1'))
                total = int(request.query_params.get('total', '0'))
            except ValueError:
                raise HTTPException(400, 'Invalid chunk coordinates')
            filename = Path(request.query_params.get('filename', '')).name
            ext = Path(filename).suffix.lower()
            if ext not in {'.dxf', '.zip'}:
                raise HTTPException(400, 'فایل ورودی باید DXF یا ZIP باشد.')
            if total < 1 or total > MAX_CHUNKS or index < 0 or index >= total:
                raise HTTPException(400, 'Invalid chunk coordinates')

            # Idempotent response if the final chunk response was lost and retried.
            durable = db.query(legacy.ProjectInputBlob.id).filter_by(project_id=pid).first()
            if project.status != 'uploading' and durable is not None:
                return JSONResponse({'ok': True, 'complete': True, 'project_id': pid, 'flow_url': f'/projects/{pid}/flow'})

            body = await request.body()
            if not body or len(body) > CHUNK_SIZE_MAX:
                raise HTTPException(413, 'Chunk is empty or too large')

            chunk = db.query(legacy.ProjectUploadChunk).filter_by(project_id=pid, chunk_index=index).first()
            if chunk is None:
                chunk = legacy.ProjectUploadChunk(project_id=pid, chunk_index=index)
                db.add(chunk)
            chunk.total_chunks = total
            chunk.filename = filename
            chunk.content = body
            db.commit()

            rows = db.query(legacy.ProjectUploadChunk).filter_by(project_id=pid).order_by(
                legacy.ProjectUploadChunk.chunk_index
            ).all()
            complete = len(rows) == total and [row.chunk_index for row in rows] == list(range(total))
            if not complete:
                return JSONResponse({'ok': True, 'complete': False, 'received': index, 'total': total})

            assembled = b''.join(bytes(row.content) for row in rows)
            if len(assembled) > CHUNK_SIZE_MAX * MAX_CHUNKS:
                raise HTTPException(413, 'Uploaded file is too large')
            blob = db.query(legacy.ProjectInputBlob).filter_by(project_id=pid).first()
            if blob is None:
                blob = legacy.ProjectInputBlob(project_id=pid)
                db.add(blob)
            blob.filename = f'architecture{ext}'
            blob.media_type = 'application/zip' if ext == '.zip' else 'application/dxf'
            blob.sha256 = hashlib.sha256(assembled).hexdigest()
            blob.content = assembled
            for row in rows:
                db.delete(row)

            project.status = 'analyzing'
            project.last_error = ''
            db.commit()
            legacy.schedule_analysis(pid)
            return JSONResponse({'ok': True, 'complete': True, 'project_id': pid, 'flow_url': f'/projects/{pid}/flow'})
        except HTTPException:
            raise
        except Exception as exc:
            # Keep received database chunks so a client retry can resume safely.
            project.last_error = str(exc)
            project.status = 'awaiting_upload'
            db.commit()
            detail = 'فضای موقت سرور پر شده است؛ فایل‌های ناقص پاک شدند، دوباره تلاش کنید.' if getattr(exc, 'errno', None) == 28 else 'آپلود روی سرور کامل نشد.'
            raise HTTPException(507 if getattr(exc, 'errno', None) == 28 else 500, detail) from exc
        finally:
            db.close()
