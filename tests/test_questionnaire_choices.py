import ast
import unittest
from pathlib import Path


source = Path('app/main.py').read_text(encoding='utf-8')
tree = ast.parse(source)
wanted = {'COMMON', 'ELECTRICAL', 'MECHANICAL', 'QUESTION_OPTIONS', 'TEXT_QUESTION_KEYS', 'NUMBER_QUESTION_KEYS'}
nodes = [node for node in tree.body if
         (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in wanted for target in node.targets))
         or (isinstance(node, ast.FunctionDef) and node.name in {'present_question', 'qlist'})]
namespace = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'questionnaire-slice', 'exec'), namespace)
COMMON = namespace['COMMON']
ELECTRICAL = namespace['ELECTRICAL']
MECHANICAL = namespace['MECHANICAL']
present_question = namespace['present_question']
qlist = namespace['qlist']


class QuestionnaireChoiceTests(unittest.TestCase):
    def test_cooling_question_never_offers_an_unsupported_authority_system(self):
        cooling = next(question for question in qlist(MECHANICAL) if question['key'] == 'cooling')
        self.assertEqual(cooling['options'], ['اسپلیت دیواری'])

    def test_location_remains_free_text(self):
        location = next(question for question in qlist(COMMON) if question['key'] == 'location')
        self.assertEqual(location['input_type'], 'text')
        self.assertEqual(location['options'], [])

    def test_all_other_questions_offer_suggested_choices(self):
        for questions in (COMMON + ELECTRICAL, COMMON + MECHANICAL):
            for question in qlist(questions):
                if question['key'] == 'location':
                    continue
                self.assertEqual(question['input_type'], 'radio', question['key'])
                minimum = 1 if question['key'] == 'cooling' else 4
                self.assertGreaterEqual(len(question['options']), minimum, question['key'])

    def test_legacy_stored_question_is_enriched_at_render_time(self):
        question = present_question({'key': 'heating', 'question': 'سیستم گرمایش چیست؟'})
        self.assertEqual(question['input_type'], 'radio')
        self.assertIn('پکیج دیواری و رادیاتور', question['options'])

    def test_gas_pressure_is_a_numeric_mbar_field_not_gas_system_choices(self):
        question = present_question({
            'key': 'gas_pressure', 'input_type': 'number', 'unit': 'mbar',
            'question': 'فشار سرویس گاز چند mbar است؟',
        })
        self.assertEqual(question['key'], 'gas_pressure')
        self.assertEqual(question['input_type'], 'number')
        self.assertEqual(question['options'], [])
        self.assertEqual(question['unit'], 'mbar')
        self.assertNotIn('ساختمان گاز ندارد', question['options'])

    def test_other_text_field_selects_other_radio(self):
        template = Path('app/templates/project.html').read_text(encoding='utf-8')
        self.assertIn("field.addEventListener('focus',activate)", template)
        self.assertIn("field.addEventListener('input',activate)", template)
        self.assertIn('data-other-radio', template)


if __name__ == '__main__':
    unittest.main()
