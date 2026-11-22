"""指代解析与读序冲突测试（使用与数据同构的小型版面）。"""

import unittest

from editorial.discourse import (
    KIND_ANAPHORA,
    KIND_JUMP,
    STATUS_CONFLICT,
    STATUS_DECIDED,
    STATUS_RESOLVED,
    resolve_references,
)
from editorial.geometry import group_columns
from editorial.model import Block, Decision, Plan


def block(block_id, page, bbox, label, text, flows=None):
    return Block(id=block_id, page=page, bbox=bbox, label=label,
                 text=text, flows=flows)


class ReferenceTest(unittest.TestCase):
    def setUp(self):
        # 左栏 L1/L2（L2 是 L1“下列情形”的例一），右栏 L3 用“上列情形”
        self.blocks = {
            "L1": block("L1", "p1", (0, 0, 100, 40), "主问一",
                        "居民可以请服务台解释。下列情形只提供咨询。"),
            "L2": block("L2", "p1", (0, 60, 100, 120), "例一",
                        "借住家属可到台前问情况。代办见背面注二。"),
            "L3": block("L3", "p1", (150, 20, 250, 100), "主问二",
                        "名字写错可以提请求。上列情形暂不在现场改。"),
            "L6": block("L6", "p2", (0, 0, 100, 80), "注二",
                        "仅持委托且有原凭据的亲属可以递交更正请求，现场不改。"),
        }
        self.columns = group_columns(list(self.blocks.values()))

    def test_explicit_jump_resolves_across_page(self):
        refs, _ = resolve_references(self.blocks, self.columns)
        jump = next(ref for ref in refs if ref.kind == KIND_JUMP)
        self.assertEqual(jump.target_ids, ("L6",))
        self.assertTrue(jump.cross_page)
        self.assertFalse(jump.optional)

    def test_same_column_anaphora_resolves(self):
        refs, _ = resolve_references(self.blocks, self.columns)
        down = next(ref for ref in refs
                    if ref.block_id == "L1" and ref.kind == KIND_ANAPHORA)
        self.assertEqual(down.status, STATUS_RESOLVED)
        self.assertEqual(down.target_ids, ("L2",))

    def test_cross_column_anaphora_is_conflict_until_decision(self):
        refs, findings = resolve_references(self.blocks, self.columns)
        up = next(ref for ref in refs
                  if ref.block_id == "L3" and ref.kind == KIND_ANAPHORA)
        self.assertEqual(up.status, STATUS_CONFLICT)
        self.assertTrue(any(f.blocking for f in findings))

        plan = Plan(
            entries=(),
            decisions=(Decision("L3", "上列", "L1", "跨栏回指主问一"),),
        )
        refs2, findings2 = resolve_references(self.blocks, self.columns, plan)
        up2 = next(ref for ref in refs2
                   if ref.block_id == "L3" and ref.kind == KIND_ANAPHORA)
        self.assertEqual(up2.status, STATUS_DECIDED)
        self.assertEqual(up2.target_ids, ("L1",))
        self.assertFalse(any(f.blocking for f in findings2))

    def test_optional_reference_marked(self):
        blocks = dict(self.blocks)
        blocks["L8"] = block("L8", "p1", (150, 130, 250, 170), "接续",
                             "备用情形见背面注一。")
        blocks["L5"] = block("L5", "p2", (0, 90, 100, 140), "注一",
                             "讲解事例可以另听，不需带纸件。")
        columns = group_columns(list(blocks.values()))
        refs, _ = resolve_references(blocks, columns)
        optional = next(ref for ref in refs
                        if ref.block_id == "L8" and ref.kind == KIND_JUMP)
        self.assertTrue(optional.optional)


if __name__ == "__main__":
    unittest.main()
