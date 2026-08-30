"""Durable S3-compatible storage for architectural inputs and CAD outputs.

The implementation works with Cloudflare R2 and any S3-compatible provider.
When credentials are absent it preserves the current local-storage behaviour,
so a deployment can be rolled out before the bucket is connected.
"""
from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

import ezdxf


S3_ENDPOINT = os.getenv('S3_ENDPOINT', '').strip()
S3_BUCKET = os.getenv('S3_BUCKET', '').strip()
S3_ACCESS_KEY_ID = os.getenv('S3_ACCESS_KEY_ID', '').strip()
S3_SECRET_ACCESS_KEY = os.getenv('S3_SECRET_ACCESS_KEY', '').strip()
S3_REGION = os.getenv('S3_REGION', 'auto').strip() or 'auto'
SIGNED_URL_TTL_SECONDS = int(os.getenv('SIGNED_URL_TTL_SECONDS', '3600'))


def configured() -> bool:
    return bool(S3_ENDPOINT and S3_BUCKET and S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY)


def healthcheck() -> dict:
    """Verify production bucket access without exposing credentials."""
    fields = {
        'endpoint': bool(S3_ENDPOINT),
        'bucket': bool(S3_BUCKET),
        'access_key_id': bool(S3_ACCESS_KEY_ID),
        'secret_access_key': bool(S3_SECRET_ACCESS_KEY),
    }
    if not configured():
        return {'configured': False, 'reachable': False, 'fields': fields}
    try:
        _client().head_bucket(Bucket=S3_BUCKET)
        return {'configured': True, 'reachable': True}
    except Exception as exc:
        return {
            'configured': True,
            'reachable': False,
            'error_type': type(exc).__name__,
        }


def _client():
    if not configured():
        return None
    import boto3
    from botocore.config import Config
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        region_name=S3_REGION,
        config=Config(signature_version='s3v4'),
    )


def input_key(project_id: int, filename: str) -> str:
    return f'projects/{project_id}/input/{Path(filename).name}'


def output_key(project_id: int, revision: int, discipline: str, filename: str) -> str:
    return f'projects/{project_id}/outputs/R{revision:03d}/{discipline}/{Path(filename).name}'


def upload_input(project_id: int, path: Path) -> str | None:
    client = _client()
    if client is None:
        return None
    key = input_key(project_id, path.name)
    client.upload_file(str(path), S3_BUCKET, key)
    client.head_object(Bucket=S3_BUCKET, Key=key)
    return f's3://{S3_BUCKET}/{key}'


def upload_output(project_id: int, revision: int, discipline: str, path: Path) -> str | None:
    client = _client()
    if client is None:
        return None
    key = output_key(project_id, revision, discipline, path.name)
    client.upload_file(str(path), S3_BUCKET, key)
    client.head_object(Bucket=S3_BUCKET, Key=key)
    return f's3://{S3_BUCKET}/{key}'


def _parse_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith('s3://'):
        raise ValueError('Not an S3 artifact URI')
    bucket, key = uri[5:].split('/', 1)
    return bucket, key


def presigned_download(uri: str, filename: str) -> str:
    bucket, key = _parse_uri(uri)
    return _client().generate_presigned_url(
        'get_object',
        Params={
            'Bucket': bucket,
            'Key': key,
            'ResponseContentDisposition': f'attachment; filename="{filename}"',
        },
        ExpiresIn=SIGNED_URL_TTL_SECONDS,
    )


def delete_artifact(uri: str) -> bool:
    """Delete one retained output only after an explicit user action."""
    if not configured() or not str(uri or '').startswith('s3://'):
        return False
    bucket, key = _parse_uri(uri)
    _client().delete_object(Bucket=bucket, Key=key)
    return True


def input_is_durable(project_id: int) -> bool:
    """Return true only after the original upload is present in object storage."""
    if not configured():
        return False
    response = _client().list_objects_v2(
        Bucket=S3_BUCKET, Prefix=f'projects/{project_id}/input/', MaxKeys=1,
    )
    return bool(response.get('Contents'))


def restore_project_input(project_id: int, project_dir: Path) -> bool:
    """Restore a missing original upload from object storage."""
    if not configured():
        return False
    project_dir.mkdir(parents=True, exist_ok=True)
    client = _client()
    prefix = f'projects/{project_id}/input/'
    response = client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
    objects = response.get('Contents') or []
    candidates = [obj['Key'] for obj in objects if obj['Key'].lower().endswith(('.zip', '.dxf'))]
    if not candidates:
        return False
    key = sorted(candidates)[-1]
    target = project_dir / ('architecture.zip' if key.lower().endswith('.zip') else 'architecture.dxf')
    client.download_file(S3_BUCKET, key, str(target))
    return target.exists() and target.stat().st_size > 0


def ensure_design_input(project_id: int, data_dir: Path, safe_extract) -> Path:
    """Guarantee the CAD engine has a local extracted input directory."""
    project_dir = data_dir / 'projects' / str(project_id)
    input_dir = project_dir / 'input'
    if input_dir.exists() and any(input_dir.rglob('*.dxf')):
        return input_dir
    if not (project_dir / 'architecture.zip').exists() and not (project_dir / 'architecture.dxf').exists():
        restore_project_input(project_id, project_dir)
    shutil.rmtree(input_dir, ignore_errors=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    zipped = project_dir / 'architecture.zip'
    drawing = project_dir / 'architecture.dxf'
    if zipped.exists():
        safe_extract(zipped, input_dir)
    elif drawing.exists():
        shutil.copy2(drawing, input_dir / drawing.name)
    if not any(input_dir.rglob('*.dxf')):
        raise RuntimeError('فایل معماری پروژه در فضای ذخیره‌سازی پیدا نشد.')
    return input_dir


def _validate_dxf(path: Path) -> dict:
    if not path.exists() or path.stat().st_size < 512:
        raise RuntimeError(f'فایل DXF خالی یا ناقص است: {path.name}')
    doc = ezdxf.readfile(path)
    entity_count = sum(1 for _ in doc.modelspace())
    if entity_count < 1:
        raise RuntimeError(f'فایل DXF هیچ Entity قابل استفاده‌ای ندارد: {path.name}')
    return {'name': path.name, 'bytes': path.stat().st_size, 'entities': entity_count}


def validate_output_artifact(path: Path) -> dict:
    """Fail closed unless every delivered DXF is readable and non-empty."""
    suffix = path.suffix.lower()
    if suffix == '.dxf':
        return {'status': 'PASS', 'format': 'DXF', 'files': [_validate_dxf(path)]}
    if suffix != '.zip' or not path.exists() or path.stat().st_size < 512:
        raise RuntimeError('بسته خروجی وجود ندارد یا ناقص است.')
    reports = []
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ساختار ZIP خروجی خراب است.')
        names = [name for name in archive.namelist() if name.lower().endswith('.dxf')]
        if not names:
            raise RuntimeError('هیچ فایل DXF داخل بسته خروجی وجود ندارد.')
        import tempfile
        with tempfile.TemporaryDirectory(prefix='engitools-output-qa-') as td:
            root = Path(td)
            for name in names:
                target = (root / Path(name).name)
                with archive.open(name) as source, target.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
                reports.append(_validate_dxf(target))
    return {'status': 'PASS', 'format': 'ZIP', 'files': reports, 'bytes': path.stat().st_size}
