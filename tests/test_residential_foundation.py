"""Foundation regressions; synthetic examples are NOT human architecture Golden layouts."""
import copy
import json
import math
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from shapely.geometry import Polygon
from cad_engine import residential_foundation as f
from cad_engine.residential_symbols import create_symbol, symbol_svg

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / 'standards/test-suites/residential'

def program():
    return [{'unit_type_id':'A','count':2,'bedrooms':2,'target_usable_area_min_m2':70,
             'target_usable_area_max_m2':90,'requirement_strength':'MANDATORY'}]

def payload():
    h='a'*64
    return {'schema_version':'architecture-generation-input/1.0','project_id':'synthetic','revision':1,'units':'m',
            'location':{'city':'synthetic','parcel_id':'P','jurisdiction':'fixture','evidence_hash':h},
            'plot':{'boundary':[[0,0],[20,0],[20,20],[0,20],[0,0]],'north_deg':0,'survey_hash':h,'access_edges':[0]},
            'authority':{'profile_hash':h,'edition_decisions':[{'source_id':'fixture','source_hash':h,'decision':'APPLICABLE','reviewer_id':'fixture','evidence_hash':h}],
                         'envelope':[[1,1],[19,1],[19,19],[1,19],[1,1]],'envelope_evidence_hash':h},
            'program':{'answers_hash':h,'questionnaire_version':'0.1.0','confirmed':True,'units_per_floor':2,'unit_types':program()},
            'typical_floors':{'identical_residential':True,'floor_ids':['L1','L2']},'reservations':[],
            'search':{'seed':1,'max_candidates':50,'max_seconds':1,'strategy_version':'synthetic'},'weights':{'privacy':1}}

class CatalogTests(unittest.TestCase):
    def test_catalog_schemas_and_cross_references(self):
        for file in f.DATA.glob('*.json'):
            with self.subTest(catalog=file.name):
                schema=json.loads((SCHEMAS/(file.stem+'.schema.json')).read_text())
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema).validate(json.loads(file.read_text()))
        sources={s['source_id'] for s in f.load_catalog('sources')['sources']}
        rules=f.load_catalog('rulebook')['rules']
        self.assertEqual(len(rules),len({r['rule_id'] for r in rules}))
        for r in rules:
            self.assertIn(r['source_id'],sources)
            self.assertFalse(r['release_enabled'])
            if r['authority_type']=='HARD_RULE':
                for k in ('clause','pdf_page','printed_page','issuer','edition_year'):
                    self.assertTrue(r['source'][k])
    def test_study_is_observed_deduplicated_and_not_golden(self):
        s=f.load_catalog('plan-study');rows=s['records']
        self.assertGreaterEqual(len(rows),100)
        self.assertEqual(len(rows),len({r['source_image_sha256'] for r in rows}))
        self.assertEqual(len(rows),len({r['study_id'] for r in rows}))
        self.assertEqual(s['summary']['human_approved_golden_count'],0)
        for r in rows:
            self.assertEqual(r['review_status'],'VISUALLY_REVIEWED')
            self.assertTrue(r['observation']);self.assertTrue(r['notable_weakness_or_risk'])
            self.assertTrue(r['source_url'].startswith('https://'))
    def test_frequency_counts_distinct_projects(self):
        rows=f.load_catalog('plan-study')['records'];byid={r['study_id']:r for r in rows}
        for h in f.load_catalog('heuristics')['heuristics']:
            rr=[byid[k] for k in h['evidence_ids']]
            self.assertEqual(h['project_frequency'],len({r['project_id'] for r in rr}))
            self.assertEqual(h['plan_frequency'],len(rr));self.assertFalse(h['code_rule'])
            if h['classification']=='SOFT_HEURISTIC':self.assertGreaterEqual(h['project_frequency'],2)
    def test_foundation_audit_cannot_claim_release(self):
        x=f.foundation_audit();self.assertTrue(x['study_target_met'])
        self.assertFalse(x['production_authorized']);self.assertFalse(x['customer_autonomous_ready'])
        self.assertEqual(x['golden_status'],'HUMAN_ARCHITECTURE_GOLDEN_REQUIRED')
        self.assertTrue(x['catalog_hashes']);self.assertTrue(x['build_identity'])
    def test_catalog_rejects_unknown_fields(self):
        x=f.load_catalog('rulebook');x['secret_override']=True
        schema=json.loads((SCHEMAS/'rulebook.schema.json').read_text())
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(x)))

class RuleTests(unittest.TestCase):
    def test_exact_boundary_pass_and_below_fail(self):
        c={'field':'width','unit':'m','op':'>=','value':.9}
        self.assertEqual(f.numeric_check(c,{'width':{'value':.9,'unit':'m'}}),'PASS')
        self.assertEqual(f.numeric_check(c,{'width':{'value':.899,'unit':'m'}}),'FAIL')
    def test_invalid_numbers_and_units_cannot_pass(self):
        c={'field':'width','unit':'m','op':'>=','value':.9}
        for v in [True,float('nan'),float('inf'),'1',None]:
            with self.subTest(value=v):self.assertEqual(f.numeric_check(c,{'width':{'value':v,'unit':'m'}}),'INPUT_REQUIRED')
        self.assertEqual(f.numeric_check(c,{'width':{'value':900,'unit':'mm'}}),'INPUT_REQUIRED')
    def test_empty_and_manual_checks_are_not_pass(self):
        self.assertEqual(f.numeric_check(None,{}),'REVIEW_REQUIRED')
        self.assertEqual(f.numeric_check({'all':[]},{}),'REVIEW_REQUIRED')
    def test_source_qualification_and_stale_input(self):
        r=f.load_catalog('rulebook')['rules'][0];facts={}
        review={'rule_hash':f.stable_hash(r),'facts_hash':f.stable_hash(facts),'status':'APPROVED','reviewer_id':'test','applicable':True}
        self.assertEqual(f.evaluate_rule(r,facts,review)['reason'],'RULE_NOT_RELEASE_QUALIFIED')
        self.assertEqual(f.evaluate_rule(r,{'changed':1},review)['reason'],'MISSING_OR_STALE_APPLICABILITY_REVIEW')
    def test_qualified_synthetic_check_and_manual_review(self):
        r={'rule_id':'SYNTHETIC','release_enabled':True,'check':{'field':'x','unit':'m','op':'>=','value':1}}
        facts={'x':{'value':1,'unit':'m'}};review={'rule_hash':f.stable_hash(r),'facts_hash':f.stable_hash(facts),'status':'APPROVED','reviewer_id':'test','applicable':True}
        self.assertEqual(f.evaluate_rule(r,facts,review)['numeric_result'],'PASS')
        review['applicable']=False;self.assertEqual(f.evaluate_rule(r,facts,review)['status'],'INPUT_REQUIRED')

class OwnerTests(unittest.TestCase):
    def test_missing_mandatory_and_unknown_fields(self):
        self.assertEqual(f.questionnaire_state({})['status'],'INPUT_REQUIRED')
        with self.assertRaises(ValueError):f.questionnaire_state({'city':'do not reask derived city'})
    def test_conditional_branches(self):
        c={'field':'purpose','in':['SALE','RENT']}
        self.assertEqual(f.branch_state(c,{}),'UNRESOLVED')
        self.assertEqual(f.branch_state(c,{'purpose':'OWNER_USE'}),'INACTIVE')
        self.assertEqual(f.branch_state(c,{'purpose':'SALE'}),'ACTIVE')
    def test_bad_array_cannot_crash_or_pass(self):
        for v in [[{}],['COST','COST'],'COST']:
            self.assertIn('priority',f.questionnaire_state({'priority':v})['invalid'])
    def test_unit_totals_and_area_ranges(self):
        p=program();self.assertEqual(f.unit_program_errors(p,2),[])
        self.assertIn('UNIT_TOTAL_MISMATCH',f.unit_program_errors(p,3))
        p[0]['target_usable_area_max_m2']=1;self.assertIn('UNIT_AREA_RANGE',f.unit_program_errors(p,2))
    def test_duplicate_unit_types_and_bool_counts(self):
        p=program();self.assertIn('UNIT_TYPE_ID',f.unit_program_errors(p+p,4))
        p[0]['count']=True;self.assertIn('UNIT_COUNTS',f.unit_program_errors(p,2))
    def test_invalid_parent_and_confirmation(self):
        s=f.questionnaire_state({'unit_program':None,'common_baths':{},'confirmation':False})
        self.assertIn('unit_program',s['invalid']);self.assertIn('confirmation',s['invalid'])

class ContractTests(unittest.TestCase):
    def test_output_cannot_claim_infeasible_without_proof_or_validated_without_candidate(self):
        schema=json.loads((SCHEMAS/'generation-output.schema.json').read_text())
        validator=Draft202012Validator(schema)
        output={'schema_version':'architecture-generation-output/1.0','status':'REVIEW_REQUIRED',
                'input_hash':'a'*64,'rulebook_hash':'b'*64,'build_identity':{'test':True},
                'construction_authorized':False,'candidates':[],'blockers':[], 'infeasibility_proof':None}
        validator.validate(output)
        for status in ('NO_FEASIBLE_LAYOUT','VALIDATED'):
            output['status']=status
            self.assertTrue(list(validator.iter_errors(output)))

    def test_valid_structure_still_requires_review(self):
        x=payload();before=copy.deepcopy(x);r=f.validate_generation_input(x)
        self.assertEqual(r['errors'],[]);self.assertEqual(r['status'],'REVIEW_REQUIRED')
        self.assertEqual(x,before);self.assertFalse(r['construction_authority'])
    def test_geometry_and_scope_failures(self):
        for mutate in [lambda x:x['plot'].update(boundary=[[0,0],[2,2],[0,2],[2,0],[0,0]]),
                       lambda x:x['authority'].update(envelope=[[0,0],[30,0],[30,30],[0,30],[0,0]]),
                       lambda x:x['typical_floors'].update(identical_residential=False),
                       lambda x:x.update(units='mm'),lambda x:x['plot'].update(access_edges=[99]),
                       lambda x:x['program'].update(units_per_floor=3),lambda x:x['plot'].update(north_deg=float('nan'))]:
            x=payload();mutate(x)
            with self.subTest(value=x):self.assertEqual(f.validate_generation_input(x)['status'],'INPUT_REQUIRED')
    def test_unknown_keys_and_zero_weights(self):
        x=payload();x['override']=True;self.assertEqual(f.validate_generation_input(x)['status'],'INPUT_REQUIRED')
        x=payload();x['weights']={'privacy':0};self.assertIn('POSITIVE_WEIGHT_SUM_REQUIRED',f.validate_generation_input(x)['errors'])
    def test_soft_score_never_compensates_hard_failure(self):
        cs=[{'candidate_id':'bad','hard_checks':{'fire':'FAIL'},'owner_mandatory':'PASS','quality':{'q':1}},
            {'candidate_id':'good','hard_checks':{'fire':'PASS'},'owner_mandatory':'PASS','quality':{'q':.1}}]
        r=f.rank_candidates(cs,['fire'],{'q':1});self.assertEqual([x['candidate_id'] for x in r['ranked']],['good'])
    def test_unknown_or_extra_failed_check_blocks(self):
        for checks in [{},{'fire':'SKIPPED'},{'fire':'PASS','light':'FAIL'}]:
            c={'candidate_id':'x','hard_checks':checks,'owner_mandatory':'PASS','quality':{'q':1}}
            self.assertFalse(f.rank_candidates([c],['fire'],{'q':1})['ranked'])
    def test_deterministic_tie_and_no_infeasibility_claim(self):
        cs=[{'candidate_id':k,'hard_checks':{'fire':'PASS'},'owner_mandatory':'PASS','quality':{'q':.5}} for k in ['b','a']]
        self.assertEqual(f.rank_candidates(cs,['fire'],{'q':1}),f.rank_candidates(cs[::-1],['fire'],{'q':1}))
        self.assertEqual(f.rank_candidates([],['fire'],{'q':1})['status'],'REVIEW_REQUIRED')
    def test_nonfinite_weights_and_quality(self):
        with self.assertRaises(ValueError):f.rank_candidates([],['fire'],{'q':float('nan')})
        c={'candidate_id':'a','hard_checks':{'fire':'PASS'},'owner_mandatory':'PASS','quality':{'q':True}}
        self.assertFalse(f.rank_candidates([c],['fire'],{'q':1})['ranked'])

class SymbolTests(unittest.TestCase):
    def make(self,key='AR-WC',**kwargs):
        a=dict(width_m=.5,depth_m=.7,origin_m=[0,0],rotation_deg=0,dimension_basis='VISUALIZATION_ONLY');a.update(kwargs)
        return create_symbol(key,**a)
    def test_all_catalog_symbols_generate_original_vectors(self):
        for row in f.load_catalog('symbols')['symbols']:
            with self.subTest(symbol=row['symbol_id']):
                s=self.make(row['symbol_id'],steps=10)
                self.assertTrue(Polygon(s['footprint']).is_valid);self.assertIn('<metadata>',symbol_svg(s))
                self.assertEqual(s['mep_ports'],[]);self.assertNotEqual(s['fit_status'],'PASS')
    def test_rotation_preserves_area_and_separates_clearance(self):
        a=self.make(rotation_deg=37,usage_clearance_m=.6,clearance_source='synthetic')
        self.assertAlmostEqual(Polygon(a['footprint']).area,.35)
        self.assertAlmostEqual(Polygon(a['usage_envelope']).area,.3)
        self.assertEqual(a['fit_status'],'INPUT_REQUIRED')
    def test_missing_clearance_and_invalid_dimensions(self):
        self.assertIsNone(self.make()['usage_envelope'])
        for n in [0,-1,True,float('inf')]:
            with self.assertRaises(ValueError):self.make(width_m=n)
        with self.assertRaises(ValueError):self.make(usage_clearance_m=.4)
    def test_door_sweep_is_not_leaf_footprint(self):
        row=next(x for x in f.load_catalog('symbols')['symbols'] if x['representation']['primitive']=='DOOR_SWING')
        s=self.make(row['symbol_id'],width_m=.9,depth_m=.04)
        self.assertGreater(Polygon(s['operating_envelope']).area,Polygon(s['footprint']).area)
    def test_stable_hash_and_changed_parameter(self):
        a=self.make();b=self.make();self.assertEqual(a['parameter_hash'],b['parameter_hash'])
        self.assertNotEqual(a['parameter_hash'],self.make(width_m=.6)['parameter_hash'])

if __name__=='__main__':unittest.main()
