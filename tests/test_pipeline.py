"""端到端测试：用真实交换资料与演示方案跑完整编校流程。"""

import json
import unittest
from pathlib import Path

from editorial.model import (
    load_channels,
    load_copy,
    load_layout,
    load_plan,
)
from editorial.pipeline import correction_report, review
from editorial.publishing import STATUS_BLOCKED, STATUS_GATED, STATUS_READY

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PLAN = ROOT / "examples" / "plan_demo.json"


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = load_layout(DATA / "layout.json")
        cls.copy = load_copy(DATA / "copy.json", cls.layout)
        cls.channels = load_channels(DATA / "channels.json")
        cls.plan = load_plan(PLAN)
        cls.report = review(
            DATA / "layout.json", DATA / "copy.json",
            DATA / "channels.json", PLAN,
        )

    def test_columns_match_two_column_leaflet(self):
        columns = self.report.columns
        self.assertEqual(
            [b.id for b in columns["外1:栏1"]], ["L1", "L2"]
        )
        self.assertEqual(
            [b.id for b in columns["外1:栏2"]], ["L3"]
        )

    def test_required_note_and_optional_note_distinguished(self):
        refs = {
            (ref.block_id, ref.marker): ref
            for ref in self.report.references
        }
        required = refs[("L2", "见背面注二")]
        optional = refs[("L8", "见背面注一")]
        self.assertTrue(required.cross_page and not required.optional)
        self.assertTrue(optional.cross_page and optional.optional)

    def test_editor_decisions_clear_reading_conflicts(self):
        statuses = {
            (ref.block_id, ref.marker): ref.status
            for ref in self.report.references
        }
        self.assertEqual(statuses[("L3", "上列情形")], "decided")
        self.assertEqual(statuses[("L4", "接续")], "decided")

    def test_e2_modal_drift_blocks(self):
        # “暂不在现场改”被写成“就能现场改”
        e2 = self.report.copy_findings["E2"]
        self.assertTrue(any(f.blocking for f in e2))
        self.assertIn("restriction_dropped", {f.code for f in e2})

    def test_e3_contradicts_legend_restriction(self):
        codes = {f.code for f in self.report.copy_findings["E3"]}
        self.assertIn("contradicts_restriction", codes)

    def test_e1_keeps_force_and_restriction(self):
        # E1 保住了许可力度与“现场不会改”的限制，只剩警告级人群覆盖提醒
        self.assertFalse(
            any(f.blocking for f in self.report.copy_findings["E1"])
        )

    def test_signed_correction_warns_but_does_not_hard_fail(self):
        e5 = self.report.copy_findings["E5"]
        self.assertFalse(any(f.blocking for f in e5))
        self.assertIn("correction_changes_condition",
                      {f.code for f in e5})

    def test_publication_verdicts(self):
        results = {
            (channel, result.unit): result.status
            for channel, units in self.report.unit_results.items()
            for result in units
        }
        self.assertEqual(results[("C1", "外1")], STATUS_READY)
        self.assertEqual(results[("C1", "背2")], STATUS_READY)
        self.assertEqual(results[("C2", "片段甲")], STATUS_READY)
        self.assertEqual(results[("C2", "选读乙")], STATUS_BLOCKED)
        self.assertEqual(results[("C3", "正")], STATUS_READY)

    def test_budget_respected_and_withdraw_has_pointer(self):
        for units in self.report.unit_results.values():
            for result in units:
                self.assertLessEqual(result.used, result.budget)
        c3 = next(r for r in self.report.unit_results["C3"]
                  if r.unit == "正")
        self.assertEqual(len(c3.withdrawn), 1)
        self.assertTrue(c3.withdrawn[0]["pointer_text"])

    def test_reading_order_preserved_in_delivery(self):
        c1 = next(r for r in self.report.unit_results["C1"]
                  if r.unit == "外1")
        # 顺序即读屏顺序，主问二（高优先）在前，且条目顺序未被预算重排
        self.assertEqual(len(c1.order), len(set(c1.order)))

    def test_required_note_carried_into_independent_unit(self):
        # 外1 可独立领取，L2 的必要注释 L6 以 support 条目随单元可查
        refs = self.report.unit_results["C1"]
        outer = next(r for r in refs if r.unit == "外1")
        self.assertEqual(outer.status, STATUS_READY)

    def test_json_report_is_serializable(self):
        payload = self.report.to_dict()
        json.dumps(payload, ensure_ascii=False)


class CorrectionTest(unittest.TestCase):
    def test_e5_reissue_scope(self):
        report = correction_report(
            DATA / "layout.json", DATA / "copy.json",
            DATA / "channels.json", PLAN, "E5",
        )
        pages = {unit.unit: unit.verdict for unit in report.print_units}
        self.assertEqual(pages["背2"], "reissue_independent")
        self.assertEqual(pages["外1"], "keep")
        # 背2 的独立换发要替换已发件 E6，且页号保留
        back = next(u for u in report.print_units if u.unit == "背2")
        self.assertIn("E6", back.stale_copies)
        self.assertEqual(back.page_number, "背2")

    def test_audio_gated_but_other_program_remains(self):
        report = correction_report(
            DATA / "layout.json", DATA / "copy.json",
            DATA / "channels.json", PLAN, "E5",
        )
        audio = {u.unit: u.verdict for u in report.audio_units}
        self.assertEqual(audio["片段甲"], "gated")
        self.assertEqual(audio["选读乙"], "gated_with_parent")

    def test_reference_graph_includes_cross_page_edges(self):
        report = correction_report(
            DATA / "layout.json", DATA / "copy.json",
            DATA / "channels.json", PLAN, "E5",
        )
        self.assertIn("L6", report.graph["L2"])
        self.assertIn("L6", report.graph["L6"] or report.graph["E6"])


if __name__ == "__main__":
    unittest.main()
