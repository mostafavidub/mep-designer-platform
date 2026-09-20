import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main_health import app


class ResumableUploadTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_mechanical_chunk_upload_can_resume_and_complete(self):
        init = self.client.post('/api/upload/init/mechanical', json={'name': 'chunk-test'})
        self.assertEqual(init.status_code, 200)
        data = init.json()
        pid = data['project_id']
        url = data['chunk_url']

        r1 = self.client.post(f'{url}?index=0&total=2&filename=plan.dxf', content=b'part-one')
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json()['complete'])

        # Re-sending a chunk must be safe; this is what makes retries resumable.
        retry = self.client.post(f'{url}?index=0&total=2&filename=plan.dxf', content=b'part-one')
        self.assertEqual(retry.status_code, 200)
        self.assertFalse(retry.json()['complete'])

        with patch('app.resumable_upload.legacy.analyze_project_job'):
            r2 = self.client.post(f'{url}?index=1&total=2&filename=plan.dxf', content=b'part-two')
            self.assertEqual(r2.status_code, 200)
            self.assertTrue(r2.json()['complete'])
            self.assertEqual(r2.json()['project_id'], pid)
            self.assertEqual(r2.json()['flow_url'], f'/projects/{pid}/flow')

    def test_invalid_upload_extension_is_rejected(self):
        init = self.client.post('/api/upload/init/electrical', json={})
        url = init.json()['chunk_url']
        r = self.client.post(f'{url}?index=0&total=1&filename=plan.exe', content=b'x')
        self.assertEqual(r.status_code, 400)

    def test_direct_object_upload_is_presigned_and_verified_before_analysis(self):
        init = self.client.post('/api/upload/init/mechanical', json={'name': 'direct-object'})
        self.assertEqual(init.status_code, 200)
        data = init.json(); pid = data['project_id']
        self.assertEqual(data['direct_upload_url'], f'/api/upload/{pid}/presign')
        with patch('app.resumable_upload.artifact_storage.presigned_input_upload', return_value={
            'upload_url': 'https://objects.example/upload',
            'key': f'projects/{pid}/input/plan.dxf',
            'content_type': 'application/dxf',
        }):
            target = self.client.post(data['direct_upload_url'], json={
                'filename': 'plan.dxf', 'size': 2048, 'content_type': 'application/dxf',
            })
        self.assertEqual(target.status_code, 200)
        with patch('app.resumable_upload.artifact_storage.input_object_exists', return_value=True), patch(
            'app.resumable_upload.legacy.schedule_analysis'
        ) as schedule:
            completed = self.client.post(target.json()['complete_url'], json={
                'filename': 'plan.dxf', 'size': 2048,
            })
        self.assertEqual(completed.status_code, 200)
        schedule.assert_called_once_with(pid)

    def test_discipline_pages_load_resumable_client(self):
        for path in ('/electrical', '/mechanical'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200)
            self.assertIn('/static/resumable-upload.js', r.text)
            self.assertIn('/static/resumable-upload.js', r.text)
            self.assertNotIn('/static/resumable-upload.js?v=', r.text)


if __name__ == '__main__':
    unittest.main()
