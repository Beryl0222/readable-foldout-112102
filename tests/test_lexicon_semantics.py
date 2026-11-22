"""语言识别测试：力度、否定、条件、施事人与动作。"""

import unittest
from pathlib import Path

from editorial import lexicon
from editorial.discourse import analyze_clause


class LexiconTest(unittest.TestCase):
    def test_request_not_guarantee(self):
        # “可以请求说明”不得被读成“窗口一定会办”
        self.assertEqual(
            lexicon.detect_force("可以请求说明"),
            lexicon.FORCE_REQUEST,
        )
        self.assertEqual(
            lexicon.detect_force("窗口一定会办"),
            lexicon.FORCE_GUARANTEE,
        )

    def test_negated_modal_is_permission_not_restriction(self):
        self.assertEqual(
            lexicon.detect_force("讲解事例可以另听，不需带纸件"),
            lexicon.FORCE_PERMISSION,
        )
        self.assertFalse(lexicon.is_negated("不需带纸件"))

    def test_real_negation_is_restriction(self):
        self.assertEqual(
            lexicon.detect_force("暂不在现场改"),
            lexicon.FORCE_RESTRICTION,
        )
        self.assertTrue(lexicon.is_negated("暂不在现场改"))

    def test_conditional_permission_keeps_permissive_force(self):
        clause = "仅持委托且有原凭据的亲属可以递交更正请求"
        self.assertIn(lexicon.detect_force(clause),
                      (lexicon.FORCE_PERMISSION, lexicon.FORCE_REQUEST))

    def test_visible_len_ignores_whitespace(self):
        self.assertEqual(lexicon.visible_len("可以 咨询\n"), 4)

    def test_roles_longest_match_first(self):
        roles = lexicon.find_roles("本人登记人可到服务台")
        self.assertEqual(roles[0], "登记人")
        self.assertIn("服务台", roles)


class ClauseSemanticsTest(unittest.TestCase):
    def test_clause_carries_condition_and_permitted_action(self):
        sem = analyze_clause("仅持委托且有原凭据的亲属可以递交更正请求")
        self.assertTrue(sem.is_condition)
        self.assertEqual(sem.actions[0], "递交更正请求")
        self.assertIn("亲属", sem.roles)

    def test_split_keeps_restriction_separate(self):
        clauses = lexicon.split_clauses(
            "仅持委托且有原凭据的亲属可以递交更正请求，现场不改"
        )
        self.assertEqual(len(clauses), 2)
        restriction = analyze_clause(clauses[1])
        self.assertTrue(restriction.is_restriction)
        self.assertEqual(restriction.actions[0], "现场更正")

    def test_multi_action_clause_primary_action(self):
        sem = analyze_clause("可由登记人递交，现场不改")
        self.assertIn("递交更正请求", sem.actions)
        self.assertIn("现场更正", sem.actions)


class ModalDriftTest(unittest.TestCase):
    def test_request_rewritten_as_guarantee_blocks(self):
        from editorial.model import Block, CopyItem, load_layout
        from editorial.semantics import verify_copy_item
        from editorial.discourse import analyze_all

        blocks = load_layout(
            Path(__file__).resolve().parents[1] / "data" / "layout.json"
        )
        sems = analyze_all(blocks)
        bad = CopyItem(
            id="X1", kind="draft", source_ref=("L1",),
            text="服务台一定会改好登记信息。",
        )
        findings = verify_copy_item(bad, blocks, sems)
        drift = next(f for f in findings if f.code == "modal_force_drift")
        self.assertTrue(drift.blocking)

    def test_faithful_rewrite_does_not_drift(self):
        from editorial.model import CopyItem, load_layout
        from editorial.semantics import verify_copy_item
        from editorial.discourse import analyze_all

        blocks = load_layout(
            Path(__file__).resolve().parents[1] / "data" / "layout.json"
        )
        sems = analyze_all(blocks)
        ok = CopyItem(
            id="X2", kind="draft", source_ref=("L1",),
            text="原住居民可以到服务台请工作人员解释登记信息。",
        )
        self.assertFalse(
            any(f.blocking for f in verify_copy_item(ok, blocks, sems))
        )


if __name__ == "__main__":
    unittest.main()
