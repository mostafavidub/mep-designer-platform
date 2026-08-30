"""Harden CAD artifact delivery so browsers keep the real DXF extension."""
from pathlib import Path


def _content_type(name: str) -> str:
    suffix = Path(str(name or '')).suffix.lower()
    if suffix == '.dxf':
        return 'application/dxf'
    if suffix == '.zip':
        return 'application/zip'
    return 'application/octet-stream'


def install(storage) -> None:
    """Patch S3/R2 uploads and presigned downloads with explicit MIME metadata."""
    if getattr(storage, '_artifact_delivery_fix_installed', False):
        return

    def upload_input(project_id: int, path: Path):
        client = storage._client()
        if client is None:
            return None
        path = Path(path)
        key = storage.input_key(project_id, path.name)
        client.upload_file(
            str(path), storage.S3_BUCKET, key,
            ExtraArgs={'ContentType': _content_type(path.name)},
        )
        client.head_object(Bucket=storage.S3_BUCKET, Key=key)
        return f's3://{storage.S3_BUCKET}/{key}'

    def upload_output(project_id: int, revision: int, discipline: str, path: Path):
        client = storage._client()
        if client is None:
            return None
        path = Path(path)
        key = storage.output_key(project_id, revision, discipline, path.name)
        client.upload_file(
            str(path), storage.S3_BUCKET, key,
            ExtraArgs={'ContentType': _content_type(path.name)},
        )
        client.head_object(Bucket=storage.S3_BUCKET, Key=key)
        return f's3://{storage.S3_BUCKET}/{key}'

    def presigned_download(uri: str, filename: str) -> str:
        bucket, key = storage._parse_uri(uri)
        # The browser must receive both an attachment filename and a non-text
        # MIME type. Without ResponseContentType some mobile browsers append
        # `.txt` to ASCII DXF files because R2 serves them as text/plain.
        media_type = _content_type(filename or key)
        return storage._client().generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket,
                'Key': key,
                'ResponseContentDisposition': f'attachment; filename="{Path(filename).name}"',
                'ResponseContentType': media_type,
            },
            ExpiresIn=storage.SIGNED_URL_TTL_SECONDS,
        )

    storage.upload_input = upload_input
    storage.upload_output = upload_output
    storage.presigned_download = presigned_download
    storage._artifact_delivery_fix_installed = True
