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

    def test_discipline_pages_load_resumable_client(self):
        for path in ('/electrical', '/mechanical'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200)
            self.assertIn('/static/resumable-upload.js', r.text)
            self.assertIn('/static/resumable-upload.js?v=19.1.0', r.text)


if __name__ == '__main__':
    unittest.main()
