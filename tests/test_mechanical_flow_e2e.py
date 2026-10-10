import unittest
from pathlib import Path

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
            self.assertEqual(project.questions[project.current_question]['key'], 'cooling_system')
        finally: db.close()

        cooling = self.client.post(f'/projects/{pid}/answer-json', data={'answer': 'اسپلیت دیواری'})
        self.assertEqual(cooling.status_code, 200); self.assertEqual(cooling.json()['status'], 'asking')

        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.questions[project.current_question]['key'], 'heating_system')
            self.assertEqual(project.answers['cooling_system'], 'wall_mounted_split_ac')
        finally: db.close()

        heating = self.client.post(f'/projects/{pid}/answer-json', data={'answer': 'پکیج دیواری و رادیاتور'})
        self.assertEqual(heating.status_code, 200); self.assertEqual(heating.json()['status'], 'asking')

        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.questions[project.current_question]['key'], 'water_inlet_pressure')
            self.assertEqual(project.answers['heating_system'], 'package_radiator')
        finally: db.close()

        invalid = self.client.post(f'/projects/{pid}/answer-json', data={'answer': 'نامشخص'})
        self.assertEqual(invalid.status_code, 422); self.assertEqual(invalid.json()['status'], 'asking'); self.assertIn('answer_error', invalid.json())

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
        source = Path('app/templates/project.html').read_text(encoding='utf-8')
        self.assertIn("expected_question_index", source)
        self.assertIn("for(let attempt=0;attempt<4;attempt++)", source)
        self.assertIn("X-Idempotent-Answer", source)
        self.assertIn("data.answer_persisted===true", source)
        self.assertIn("data.answer_error", source)
        self.assertIn("if(submitting)return", source)

    def _fixture_question_project(self, name='fixture-question-contract'):
        init = self.client.post('/api/upload/init/mechanical', json={'name': name})
        self.assertEqual(init.status_code, 200)
        pid = init.json()['project_id']
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            project.status = 'asking'
            project.questions = [
                {'key': f'kept_{index}', 'question': f'پرسش قبلی {index}'}
                for index in range(20)
            ] + [{
                'key': 'fixture_schedule',
                'question': 'تعداد تجهیزات لوله‌کشی بام را مشخص کنید.',
            }]
            project.current_question = 20
            project.answers = {
                'discipline': 'mechanical',
                **{f'kept_{index}': f'value-{index}' for index in range(20)},
            }
            project.analysis = {'discipline': 'mechanical'}
            db.commit()
        finally:
            db.close()
        return pid

    def test_fixture_question_presentation_matches_flow_and_requires_quantities(self):
        pid = self._fixture_question_project()
        flow = self.client.get(f'/projects/{pid}/flow')
        page = self.client.get(f'/projects/{pid}')
        self.assertEqual(flow.status_code, 200)
        self.assertEqual(page.status_code, 200)
        question = flow.json()['question']
        self.assertEqual(question['key'], 'fixture_schedule')
        self.assertEqual(question['input_type'], 'text')
        self.assertEqual(question['options'], [])
        self.assertEqual(question['answer_format'], 'quantified_fixture_schedule')
        self.assertIn(question['placeholder'], page.text)
        self.assertNotIn('تأیید پیشنهاد خودکار تجهیزات', page.text)
        self.assertNotIn('بدون تجهیزات لوله‌کشی', page.text)

    def test_invalid_fixture_answer_is_422_and_preserves_all_prior_answers(self):
        pid = self._fixture_question_project()
        db = legacy.Session()
        try:
            before = dict(db.get(legacy.Project, pid).answers)
        finally:
            db.close()
        response = self.client.post(
            f'/projects/{pid}/answer-json',
            data={'answer': 'تأیید پیشنهاد خودکار تجهیزات', 'expected_question_index': '20'},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['answer_outcome'], 'validation_error')
        self.assertFalse(response.json()['answer_persisted'])
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.current_question, 20)
            self.assertEqual(project.answers, before)
            self.assertNotIn('fixture_schedule', project.answers)
        finally:
            db.close()

    def test_unscoped_zero_fixture_answer_is_rejected(self):
        pid = self._fixture_question_project('fixture-zero-rejected')
        response = self.client.post(
            f'/projects/{pid}/answer-json',
            data={'answer': 'بدون تجهیزات لوله‌کشی', 'expected_question_index': '20'},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['error_code'], 'invalid_answer')

    def test_quantified_fixture_answer_advances_once_and_replay_is_idempotent(self):
        pid = self._fixture_question_project('fixture-answer-idempotency')
        payload = {
            'answer': 'سینک ۲، روشویی ۲، توالت ۲، دوش ۰',
            'expected_question_index': '20',
        }
        accepted = self.client.post(f'/projects/{pid}/answer-json', data=payload)
        replay = self.client.post(f'/projects/{pid}/answer-json', data=payload)
        stale = self.client.post(
            f'/projects/{pid}/answer-json',
            data={'answer': 'سینک ۳، روشویی ۲، توالت ۲، دوش ۰', 'expected_question_index': '20'},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()['answer_persisted'])
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['idempotent_replay'])
        self.assertEqual(stale.status_code, 409)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.current_question, 21)
            self.assertEqual(project.answers['fixture_schedule'], payload['answer'])
        finally:
            db.close()

    def test_malformed_question_index_is_rejected_without_advancing(self):
        pid = self._fixture_question_project('fixture-bad-index')
        response = self.client.post(
            f'/projects/{pid}/answer-json',
            data={'answer': 'سینک ۲، توالت ۲', 'expected_question_index': '../20'},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error_code'], 'invalid_question_index')
        db = legacy.Session()
        try:
            self.assertEqual(db.get(legacy.Project, pid).current_question, 20)
        finally:
            db.close()

    def test_legacy_html_fixture_validation_uses_same_contract(self):
        pid = self._fixture_question_project('fixture-legacy-html')
        rejected = self.client.post(
            f'/projects/{pid}/answer',
            data={'answer': 'تجهیزات مطابق سمبل‌های پلان معماری', 'expected_question_index': '20'},
            follow_redirects=False,
        )
        self.assertEqual(rejected.status_code, 303)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            self.assertEqual(project.current_question, 20)
            self.assertIn('تعداد عددی', (project.analysis or {})['answer_error'])
        finally:
            db.close()

    def test_wrong_owner_fixture_submission_remains_non_disclosing(self):
        pid = self._fixture_question_project('fixture-owner-isolation')
        other = TestClient(app)
        self.assertEqual(
            other.post('/api/upload/init/mechanical', json={'name': 'unrelated-owner'}).status_code,
            200,
        )
        response = other.post(
            f'/projects/{pid}/answer-json',
            data={'answer': 'سینک ۲، توالت ۲', 'expected_question_index': '20'},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__': unittest.main()
