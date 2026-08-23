import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import ezdxf

from app.main_auto import analyze_dxf_enhanced
from app.auto_inference_v2 import infer_architecture_facts
from app.mechanical_workflow import build_scope
from app.mechanical_drawing_set import predict_drawing_set


class LargeDxfArchitectureAnalyzerTests(unittest.TestCase):
    def build_large_architecture(self, path):
        doc = ezdxf.new("R2013")
        doc.header["$INSUNITS"] = 4
        msp = doc.modelspace()
        # Real authority files can contain thousands of unrelated annotations
        # before the architectural plan titles and room names.
        for index in range(1205):
            msp.add_text(f"DETAIL NOTE {index}").set_placement((index, -100))

        plan = doc.blocks.new(name="ARCH_PLANS")
        plan.add_text("پلان معماری طبقه همکف").set_placement((0, 0))
        for text, point in [
            ("آشپزخانه", (3, 4)), ("حمام", (6, 5)), ("سرویس", (7, 8)),
            ("پذیرایی", (12, 5)), ("اتاق خواب", (14, 9)), ("اتاق خواب", (16, 11)),
        ]:
            plan.add_text(text).set_placement(point)

        plan.add_text("پلان معماری طبقه اول و دوم").set_placement((100, 0))
        for text, point in [
            ("آشپزخانه", (103, 4)), ("حمام", (106, 5)), ("سرویس", (107, 8)),
            ("پذیرایی", (112, 5)), ("اتاق خواب", (114, 9)),
        ]:
            plan.add_text(text).set_placement(point)

        plan.add_text("پلان مبلمان طبقه اول و دوم").set_placement((101, 1))
        plan.add_text("پلان معماری بام").set_placement((200, 0))
        plan.add_text("بام").set_placement((203, 4))
        msp.add_blockref("ARCH_PLANS", (0, 0))
        doc.saveas(path)

    def test_large_file_detects_all_levels_and_issues_15_sheet_proposal(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "architecture.dxf"
            self.build_large_architecture(path)
            file_analysis = analyze_dxf_enhanced(path)

            # Semantic labels located after entity 1000 must survive extraction.
            labels = [x["text"] for x in file_analysis["text_labels"]]
            self.assertIn("پلان معماری طبقه همکف", labels)
            self.assertIn("پلان معماری طبقه اول و دوم", labels)
            self.assertIn("پلان معماری بام", labels)

            analysis = {"files": [file_analysis], "discipline": "mechanical"}
            auto = infer_architecture_facts(analysis, "mechanical")
            analysis["architectural_auto"] = auto
            names = [x["name"] for x in auto["level_profiles"]]
            self.assertEqual(names, ["طبقه همکف", "طبقه اول", "طبقه دوم", "بام"])
            self.assertEqual(auto["typical_groups"][0]["levels"], ["طبقه اول", "طبقه دوم"])

            project = SimpleNamespace(
                analysis=analysis,
                answers={"discipline": "mechanical", "heating": "رادیاتور", "cooling": "اسپلیت", "gas": "بله"},
            )
            scope = build_scope(project)
            proposal = predict_drawing_set(scope)
            self.assertEqual(proposal["deliverable_sheet_count"], 15)
            self.assertEqual(proposal["sheet_families"]["water_supply"]["count"], 3)
            self.assertEqual(proposal["sheet_families"]["sanitary_vent"]["count"], 2)
            self.assertEqual(proposal["sheet_families"]["heating"]["count"], 2)
            self.assertEqual(proposal["sheet_families"]["cooling"]["count"], 3)
            self.assertEqual(proposal["sheet_families"]["gas"]["count"], 2)
            self.assertEqual(proposal["sheet_families"]["ventilation_exhaust"]["count"], 2)
            self.assertEqual(proposal["sheet_families"]["roof_rainwater"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
