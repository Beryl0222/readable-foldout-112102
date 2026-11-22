"""几何读序测试：分栏、逐栏/逐行读序、纵向邻近。"""

import unittest

from editorial.geometry import (
    compare_orders,
    group_columns,
    layout_reading_order,
    nearest_block,
    row_reading_order,
)
from editorial.model import Block


def make(block_id, page, bbox, label="问", text="", flows=None):
    return Block(id=block_id, page=page, bbox=bbox, label=label,
                 text=text, flows=flows)


class GeometryTest(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            make("A", "p1", (0, 0, 100, 50), "主问一", "左栏上"),
            make("B", "p1", (0, 60, 100, 110), "例一", "左栏下"),
            make("C", "p1", (150, 10, 250, 70), "主问二", "右栏上"),
            make("D", "p1", (150, 90, 250, 130), "接续",
                 "这一项请带原凭据", flows="→"),
        ]

    def test_columns_grouped_by_overlap(self):
        columns = group_columns(self.blocks)
        members = {
            key: [block.id for block in value]
            for key, value in columns.items()
        }
        self.assertEqual(members["p1:栏1"], ["A", "B"])
        self.assertEqual(members["p1:栏2"], ["C"])

    def test_connector_excluded_from_columns(self):
        columns = group_columns(self.blocks)
        all_members = [b for value in columns.values() for b in value]
        self.assertNotIn("D", {b.id for b in all_members})

    def test_layout_order_is_column_by_column(self):
        columns = group_columns(self.blocks)
        order = [b.id for b in layout_reading_order(self.blocks, columns)]
        self.assertEqual(order, ["A", "B", "C", "D"])

    def test_row_order_interleaves_columns(self):
        order = [b.id for b in row_reading_order(self.blocks)]
        self.assertLess(order.index("A"), order.index("C"))
        self.assertLess(order.index("C"), order.index("B"))

    def test_order_swap_detects_cross_column_risk(self):
        columns = group_columns(self.blocks)
        swaps = compare_orders(self.blocks, columns)
        self.assertIn(("B", "C"), swaps)

    def test_vertical_nearest_ignores_other_column(self):
        target = make("X", "p1", (150, 200, 250, 240))
        self.blocks.append(target)
        above_same_col = make("Y", "p1", (150, 150, 250, 190))
        self.blocks.append(above_same_col)
        # 另一栏的块横向近，但纵向离得远
        near_other_col = make("Z", "p1", (0, 40, 100, 90))
        self.blocks.append(near_other_col)
        self.assertEqual(
            nearest_block(target, [above_same_col, near_other_col],
                          vertical_only=True),
            above_same_col,
        )


if __name__ == "__main__":
    unittest.main()
