import unittest
from cad_engine.reference_parity_engine_v17 import *


def ctx(pid, systems, levels=("GROUND","LEVEL-01","LEVEL-02"), use="residential"):
    routes=[]
    for s in systems:
        c=canonical_system(s)
        if c in {"SANITARY_VENT","WATER","HEATING","GAS"}:
            for l in levels:
                routes.append({"system":c,"level":l,"dn":25})
    return ProjectContext(project_id=pid,building_use=use,levels=list(levels),active_systems=list(systems),routes=routes)

class ReferenceParityV17Tests(unittest.TestCase):
    def setUp(self):
        self.p=ctx("P",["SANITARY_VENT","WATER","HEATING","GAS","SPLIT_AC","EXHAUST","RAINWATER"])

    def test_stage_01_reference_decomposition(self):
        s=decompose_reference_sheet({"title":"Heating Riser","level":"L1","systems":["heating"]})
        self.assertEqual(s.family,"RISER"); self.assertIn("HEATING",s.systems)

    def test_stage_02_detail_library(self):
        d=select_details(self.p); self.assertIn("D-AC-01 INDOOR UNIT",d); self.assertIn("D-HT-01 RADIATOR WALL",d)

    def test_stage_03_detail_parameters(self):
        p=resolve_detail_parameters(self.p,select_details(self.p)); self.assertEqual(p["D-AC-04 CONDENSATE DRAIN"]["drain_dn"],25)

    def test_stage_04_detail_composer(self):
        d=compose_detail_sheet_model(self.p); self.assertGreaterEqual(len(d["sheets"]),3); self.assertTrue(all(s["grid"]["columns"]==2 for s in d["sheets"]))

    def test_stage_05_riser_graph(self):
        g=build_riser_graph(self.p); self.assertTrue(g["nodes"]); self.assertTrue(any(e["type"]=="PLAN_BRANCH" for e in g["edges"]))

    def test_stage_06_riser_reconciliation(self):
        g=build_riser_graph(self.p); self.assertTrue(reconcile_plan_riser(self.p,g)["pass"])

    def test_stage_07_riser_geometry(self):
        m=compose_riser_geometry_model(self.p,build_riser_graph(self.p)); self.assertTrue(m["columns"]); self.assertEqual(m["level_lines"],self.p.levels)

    def test_stage_08_calculation_dependencies(self):
        d=build_calculation_dependencies(self.p); self.assertIn("pump_h",d); self.assertIn("gas_pipe_dn",d)

    def test_stage_09_calculation_traceability(self):
        rows=build_calculation_rows(self.p,build_calculation_dependencies(self.p)); self.assertTrue(all(r["source_refs"] for r in rows))

    def test_stage_10_calculation_format(self):
        m=format_calculation_sheet_model(self.p); self.assertTrue(m["sections"]); self.assertTrue(m["summary_required"])

    def test_stage_11_notes_knowledge_base(self):
        notes=select_general_notes(self.p); self.assertGreater(len(notes),10)

    def test_stage_12_project_specific_filter(self):
        p=ctx("water-only",["WATER"],["GROUND"]); systems={n["system"] for n in select_general_notes(p)}; self.assertEqual(systems,{"WATER"})

    def test_stage_13_provenance(self):
        notes=attach_provenance(self.p,select_general_notes(self.p)); self.assertTrue(all(n["provenance_status"]=="TRACEABLE" for n in notes))

    def test_stage_14_reference_grammar(self):
        g=infer_reference_grammar({"density":"HIGH","leader_style":"ORTHO"}); self.assertEqual(g["density"],"HIGH")

    def test_stage_15_sheet_consistency(self):
        detail=compose_detail_sheet_model(self.p); r=build_riser_graph(self.p); c=format_calculation_sheet_model(self.p); n=attach_provenance(self.p,select_general_notes(self.p)); self.assertTrue(sheet_consistency_gate(self.p,detail,r,c,n)["pass"])

    def test_stage_16_semantic_pairing(self):
        refs=[{"family":"HEATING","level":"GROUND","systems":["heating"]},{"family":"SPLIT_AC","level":"LEVEL-01","systems":["split"]}]
        gens=list(reversed(refs)); out=pair_sheets(refs,gens); self.assertTrue(out["pass"]); self.assertEqual(len(out["pairs"]),2)

    def test_stage_17_four_component_scoring(self):
        s={"family":"RISER","level":"GROUND","systems":["water"],"annotations":["DN","LEVEL"]}
        out=score_sheet(s,s); self.assertEqual(out["score"],100.0)

    def test_stage_18_gap_fix_loop(self):
        r={"family":"RISER","level":"GROUND","systems":["water"],"annotations":["DN","LEVEL"]}
        g={"family":"RISER","level":"LEVEL-01","systems":["water"],"annotations":["DN"]}
        sc=score_sheet(r,g); self.assertLess(sc["score"],100); self.assertTrue(gap_to_fix(sc))

    def test_stage_19_multi_project_regression(self):
        projects=[ctx("4",["WATER","HEATING","GAS","SPLIT_AC"]),ctx("6",["WATER","SANITARY_VENT","HEATING","EXHAUST"]),ctx("7",["WATER","HEATING","GAS","SPLIT_AC","EXHAUST"])]
        out=run_regression_suite(projects); self.assertTrue(out["pass"]); self.assertEqual(len(out["projects"]),3)

    def test_stage_20_unseen_project_acceptance(self):
        bench=[ctx("4",["WATER","HEATING","GAS","SPLIT_AC"]),ctx("6",["WATER","SANITARY_VENT","HEATING","EXHAUST"]),ctx("7",["WATER","HEATING","GAS","SPLIT_AC","EXHAUST"])]
        unseen=[ctx("UNSEEN-A",["SANITARY_VENT","WATER","RAINWATER"],["BASEMENT","GROUND","LEVEL-01"],"mixed-use"),ctx("UNSEEN-B",["WATER","SPLIT_AC","EXHAUST"],["GROUND"],"commercial"),ctx("UNSEEN-C",["GAS","HEATING","WATER"],["GROUND","MEZZANINE","LEVEL-01","ROOF"],"office")]
        self.assertEqual(acceptance_gate(bench,unseen)["status"],"PASS")

if __name__=='__main__': unittest.main()
