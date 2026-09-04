import unittest

from fastapi.testclient import TestClient

from app.main_health import app
from app import main as legacy


class MechanicalFlowE2ETests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_answers_reach_drawing_set_proposal_over_real_http_routes(self):
        init = self.client.post('/api/upload/init/mechanical', json={'name': 'mechanical-flow-e2e'})
        self.assertEqual(init.status_code, 200)
        payload = init.json(); pid = payload['project_id']

        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid); self.assertIsNotNone(project)
            project.status = 'asking'
            project.questions = [
                {'key': 'location', 'question': 'محل پروژه کجاست؟'},
                {'key': 'gas', 'question': 'ساختمان گاز دارد؟'},
            ]
            project.current_question = 0
            project.answers = {'discipline': 'mechanical'}
            project.analysis = {
                'discipline': 'mechanical',
                'files': [{'file': 'architecture.dxf','texts': ['همکف پلان معماری', 'طبقه اول پلان معماری', 'بام پلان معماری']}],
                'auto_summary': ['سه تراز معماری برای تست شناسایی شد'],
            }
            db.commit()
        finally: db.close()
        flow = self.client.get(payload['flow_url']); self.assertEqual(flow.status_code, 200); self.assertEqual(flow.json()['status'], 'asking'); self.assertEqual(flow.json()['current_index'], 0)
        first = self.client.post(f'/projects/{pid}/answer-json', data={'answer': 'مشهد'}); self.assertEqual(first.status_code, 200); self.assertEqual(first.json()['status'], 'asking'); self.assertEqual(first.json()['current_index'], 1)

        gas = self.client.post(f'/projects/{pid}/answer-json', data={'answer': 'خیر، ساختمان گاز ندارد'})
        self.assertEqual(gas.status_code, 200); self.assertEqual(gas.json()['status'], 'asking')

        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.questions[project.current_question]['key'], 'water_inlet_pressure')
        finally: db.close()

        invalid = self.client.post(f'/projects/{pid}/answer-json', data={'answer': 'نامشخص'})
        self.assertEqual(invalid.status_code, 200); self.assertEqual(invalid.json()['status'], 'asking'); self.assertIn('answer_error', invalid.json())

        water = self.client.post(f'/projects/{pid}/answer-json', data={'answer': '2.8 bar'})
        self.assertEqual(water.status_code, 200); self.assertEqual(water.json()['status'], 'asking')
        rain = self.client.post(f'/projects/{pid}/answer-json', data={'answer': '95 mm/h'})
        self.assertEqual(rain.status_code, 200); self.assertEqual(rain.json()['status'], 'asking')
        shaft = self.client.post(f'/projects/{pid}/answer-json', data={'answer': 'پیشنهاد نزدیک هسته فضاهای تر'})
        self.assertEqual(shaft.status_code, 200); final_data = shaft.json(); self.assertEqual(final_data['status'], 'drawing_set_review')
        self.assertIn('drawing_set', final_data); self.assertTrue(final_data['drawing_set']); self.assertGreater(final_data['drawing_set']['total_plans'], 0); self.assertIn('systems', final_data['drawing_set'])

        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.answers['water_inlet_pressure'], '2.8 bar')
            self.assertEqual(project.answers['rainfall_intensity'], '95 mm/h')
            self.assertEqual((project.analysis or {})['basis_preflight']['status'], 'PASS')
        finally: db.close()

        proposal = self.client.get(f'/projects/{pid}/drawing-set'); self.assertEqual(proposal.status_code, 200); proposal_data = proposal.json()
        self.assertGreater(proposal_data['total_plans'], 0); self.assertIn('water_supply', proposal_data['systems']); self.assertEqual(proposal_data['systems']['gas']['count'], 0)
        self.assertFalse(proposal_data['approved']); self.assertTrue(proposal_data['approval_required'])

    def test_flow_poll_does_not_regress_an_active_design(self):
        init = self.client.post('/api/upload/init/mechanical', json={'name': 'active-design-poll'}); self.assertEqual(init.status_code, 200); pid = init.json()['project_id']
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid); project.status = 'queued'; project.questions = []; project.current_question = 0; project.answers = {'discipline': 'mechanical'}
            project.analysis = {'discipline': 'mechanical','architecture_analyzer_version': '3.5-project-evidence-gate','drawing_set': {'approved': True,'drawing_manifest': {'schema_version': 'legacy', 'sheets': []}}}
            db.commit()
        finally: db.close()
        flow = self.client.get(f'/projects/{pid}/flow'); self.assertEqual(flow.status_code, 200); self.assertEqual(flow.json()['status'], 'queued')
        db = legacy.Session()
        try: self.assertEqual(db.get(legacy.Project, pid).status, 'queued')
        finally: db.close()

    def test_answer_replay_after_lost_response_is_idempotent(self):
        init = self.client.post('/api/upload/init/mechanical', json={'name': 'answer-idempotency'})
        pid = init.json()['project_id']
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            project.status = 'asking'
            project.questions = [
                {'key': 'location', 'question': 'محل پروژه کجاست؟'},
                {'key': 'gas', 'question': 'ساختمان گاز دارد؟'},
            ]
            project.current_question = 0
            project.answers = {'discipline': 'mechanical'}
            db.commit()
        finally:
            db.close()

        payload = {'answer': 'گنبد کاووس', 'expected_question_index': '0'}
        first = self.client.post(f'/projects/{pid}/answer-json', data=payload)
        replay = self.client.post(f'/projects/{pid}/answer-json', data=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['idempotent_replay'])
        self.assertEqual(replay.json()['current_index'], 1)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.current_question, 1)
            self.assertNotIn('gas', project.answers)
        finally:
            db.close()

    def test_project_answer_ui_retries_transient_gateway_failures(self):
        source = open('app/templates/project.html', encoding='utf-8').read()
        self.assertIn("expected_question_index", source)
        self.assertIn("for(let attempt=0;attempt<4;attempt++)", source)
        self.assertIn("X-Idempotent-Answer", source)


if __name__ == '__main__': unittest.main()
