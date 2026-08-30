import tempfile
import unittest
from pathlib import Path

from app.artifact_delivery_fix import install


class FakeClient:
    def __init__(self):
        self.uploads = []
        self.presigned = []
        self.heads = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploads.append({
            'filename': filename, 'bucket': bucket, 'key': key,
            'ExtraArgs': ExtraArgs or {},
        })

    def head_object(self, **kwargs):
        self.heads.append(kwargs)
        return {'ContentLength': 1}

    def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
        self.presigned.append({
            'operation': operation, 'Params': Params or {}, 'ExpiresIn': ExpiresIn,
        })
        return 'https://r2.example/signed'


class FakeStorage:
    S3_BUCKET = 'engitools-test'
    SIGNED_URL_TTL_SECONDS = 3600

    def __init__(self):
        self.client = FakeClient()

    def _client(self):
        return self.client

    @staticmethod
    def input_key(project_id, filename):
        return f'projects/{project_id}/input/{Path(filename).name}'

    @staticmethod
    def output_key(project_id, revision, discipline, filename):
        return f'projects/{project_id}/outputs/R{revision:03d}/{discipline}/{Path(filename).name}'

    @staticmethod
    def _parse_uri(uri):
        bucket, key = uri[5:].split('/', 1)
        return bucket, key


class ArtifactDeliveryFixTests(unittest.TestCase):
    def test_dxf_upload_is_stored_with_binary_dxf_content_type(self):
        storage = FakeStorage(); install(storage)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'mechanical_design.dxf'
            path.write_bytes(b'  0\nSECTION\n  0\nEOF\n')
            uri = storage.upload_output(77, 1, 'mechanical', path)
        self.assertEqual(uri, 's3://engitools-test/projects/77/outputs/R001/mechanical/mechanical_design.dxf')
        self.assertEqual(storage.client.uploads[0]['ExtraArgs']['ContentType'], 'application/dxf')

    def test_zip_upload_is_stored_as_application_zip(self):
        storage = FakeStorage(); install(storage)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'mechanical_design.zip'
            path.write_bytes(b'PK')
            storage.upload_output(77, 1, 'mechanical', path)
        self.assertEqual(storage.client.uploads[0]['ExtraArgs']['ContentType'], 'application/zip')

    def test_presigned_dxf_forces_filename_and_content_type(self):
        storage = FakeStorage(); install(storage)
        filename = 'EngiTools_mechanical_77_R1.dxf'
        url = storage.presigned_download(
            's3://engitools-test/projects/77/outputs/R001/mechanical/design.dxf',
            filename,
        )
        self.assertEqual(url, 'https://r2.example/signed')
        params = storage.client.presigned[0]['Params']
        self.assertEqual(params['ResponseContentType'], 'application/dxf')
        self.assertEqual(
            params['ResponseContentDisposition'],
            'attachment; filename="EngiTools_mechanical_77_R1.dxf"',
        )
        self.assertNotIn('.txt', params['ResponseContentDisposition'])

    def test_presigned_zip_forces_zip_filename_and_content_type(self):
        storage = FakeStorage(); install(storage)
        storage.presigned_download(
            's3://engitools-test/projects/77/outputs/R001/mechanical/design.zip',
            'EngiTools_mechanical_77_R1_DXF.zip',
        )
        params = storage.client.presigned[0]['Params']
        self.assertEqual(params['ResponseContentType'], 'application/zip')
        self.assertTrue(params['ResponseContentDisposition'].endswith('_DXF.zip"'))


if __name__ == '__main__':
    unittest.main()
