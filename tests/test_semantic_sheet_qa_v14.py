import unittest
from cad_engine.semantic_sheet_qa_v14 import evaluate_sheet, detect_semantic_duplicates


class SemanticSheetQATests(unittest.TestCase):
    def test_gas_sheet_requires_real_gas_geometry(self):
        sheet={"sheet":"M-15","family":"GAS","model_bounds":[0,0,20,30]}
        only_frame=[{"layer":"ENGITOOLS-M-SHEET-FRAME","type":"LWPOLYLINE","extents":[0,0,20,30]}]
        self.assertEqual(evaluate_sheet(sheet,only_frame)["status"],"FAIL")
        real=only_frame+[
            {"layer":"ENGITOOLS-M-GAS","type":"LWPOLYLINE","extents":[2,3,8,3]},
            {"layer":"ENGITOOLS-M-GAS","type":"CIRCLE","extents":[7.8,2.8,8.2,3.2]},
        ]
        self.assertEqual(evaluate_sheet(sheet,real)["status"],"PASS")

    def test_duplicate_family_signatures_are_rejected(self):
        rows=[
            {"sheet":"M-24","family":"EXHAUST","signature":"abc"},
            {"sheet":"M-25","family":"EXHAUST","signature":"abc"},
            {"sheet":"M-26","family":"EXHAUST","signature":"def"},
        ]
        self.assertEqual(detect_semantic_duplicates(rows),[("M-24","M-25","EXHAUST")])

    def test_distinct_general_details_pass(self):
        rows=[
            {"sheet":"M-01","family":"GENERAL_DETAIL","signature":"a"},
            {"sheet":"M-02","family":"GENERAL_DETAIL","signature":"b"},
            {"sheet":"M-03","family":"GENERAL_DETAIL","signature":"c"},
        ]
        self.assertEqual(detect_semantic_duplicates(rows),[])


if __name__ == "__main__":
    unittest.main()
