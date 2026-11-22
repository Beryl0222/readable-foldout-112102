"""版面几何：栏位聚类与两种候选读序。"""

from __future__ import annotations

from collections import defaultdict

from .model import Block


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def group_columns(blocks: list[Block]) -> dict[str, list[Block]]:
    """把同一页的文字块按水平区间聚成栏。

    判定：两块在 x 方向上的重叠达到较窄块宽度的一半即视为同栏；
    接续块（带流向符号或标注“接续”）不参与栏聚类。
    """
    columns: dict[str, list[Block]] = defaultdict(list)
    for page in sorted({block.page for block in blocks}):
        page_blocks = [
            block
            for block in blocks
            if block.page == page and not block.is_connector
        ]
        # 并查集式合并
        parent = {block.id: block.id for block in page_blocks}

        def find(identifier: str) -> str:
            while parent[identifier] != identifier:
                parent[identifier] = parent[parent[identifier]]
                identifier = parent[identifier]
            return identifier

        for i, first in enumerate(page_blocks):
            for second in page_blocks[i + 1:]:
                width = min(first.right - first.left,
                            second.right - second.left)
                if width <= 0:
                    continue
                if _overlap(first.left, first.right,
                            second.left, second.right) >= width / 2:
                    parent[find(first.id)] = find(second.id)

        groups: dict[str, list[Block]] = defaultdict(list)
        for block in page_blocks:
            groups[find(block.id)].append(block)
        # 栏序按栏的左缘排序
        ordered = sorted(groups.values(),
                         key=lambda members: min(b.left for b in members))
        for index, members in enumerate(ordered, start=1):
            key = f"{page}:栏{index}"
            columns[key] = sorted(members, key=lambda b: b.top)
    return dict(columns)


def column_of(block: Block, columns: dict[str, list[Block]]) -> str | None:
    for key, members in columns.items():
        if block.page == key.split(":", 1)[0]:
            if any(member.id == block.id for member in members):
                return key
    return None


def layout_reading_order(blocks: list[Block],
                         columns: dict[str, list[Block]]) -> list[Block]:
    """印刷读序：从左到右逐栏，栏内自上而下；接续块附在同页末尾。"""
    ordered: list[Block] = []
    for key in sorted(columns, key=lambda k: (k.split(":", 1)[0],
                                              int(k.split("栏", 1)[1]))):
        ordered.extend(columns[key])
    connectors = sorted(
        (block for block in blocks if block.is_connector),
        key=lambda b: (b.page, b.top),
    )
    ordered.extend(connectors)
    return ordered


def row_reading_order(blocks: list[Block]) -> list[Block]:
    """整页横向读序：自上而下成行，行内从左到右。

    用于暴露“一段段从左到右抄”时，例外被接到另一问题下的风险。
    """
    pages = defaultdict(list)
    for block in blocks:
        pages[block.page].append(block)
    ordered: list[Block] = []
    for page in sorted(pages):
        page_blocks = pages[page]
        heights = sorted(b.bottom - b.top for b in page_blocks)
        threshold = heights[len(heights) // 2] / 2
        rows: list[list[Block]] = []
        for block in sorted(page_blocks, key=lambda b: b.top):
            for row in rows:
                anchor = row[0]
                if abs(block.top - anchor.top) <= threshold:
                    row.append(block)
                    break
            else:
                rows.append([block])
        for row in rows:
            ordered.extend(sorted(row, key=lambda b: b.left))
    return ordered


def nearest_block(target: Block, candidates: list[Block],
                  vertical_only: bool = False) -> Block | None:
    """几何上最近的文字块。

    vertical_only 时只用纵向距离——同一阅读方向上的“上/下一块”
    不应被横向邻近的另一栏块抢走。
    """
    if not candidates:
        return None
    center = ((target.left + target.right) / 2,
              (target.top + target.bottom) / 2)

    def distance(block: Block) -> float:
        other = ((block.left + block.right) / 2,
                 (block.top + block.bottom) / 2)
        if vertical_only:
            return abs(center[1] - other[1])
        return (center[0] - other[0]) ** 2 + (center[1] - other[1]) ** 2

    return min(candidates, key=distance)


def compare_orders(blocks: list[Block],
                   columns: dict[str, list[Block]]) -> list[tuple[str, str]]:
    """返回两种读序中相对位置发生变化的文字块对。"""
    layout_order = layout_reading_order(blocks, columns)
    row_order = row_reading_order(blocks)
    layout_rank = {block.id: index for index, block in enumerate(layout_order)}
    row_rank = {block.id: index for index, block in enumerate(row_order)}
    swaps: list[tuple[str, str]] = []
    ids = [block.id for block in layout_order]
    for i, first in enumerate(ids):
        for second in ids[i + 1:]:
            if layout_rank[first] < layout_rank[second] and \
                    row_rank[first] > row_rank[second]:
                swaps.append((first, second))
    return swaps
