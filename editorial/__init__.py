"""街道宣传折页编校工具。

在印刷与送读屏之前，对多栏原稿与易读改写做统一检查：

* 布局读序与语言衔接（跨栏、跨页指代）；
* 允许/要求力度、例外归属、施事人—帮助对照；
* 独立页面/音频片段的自足性与版面预算；
* 窗口更正后的换发与播放门控。

只使用 Python 3.11 标准库。
"""

from .model import Block, CopyItem, Channel, UnitSpec, Finding, PlanEntry, Plan

__all__ = [
    "Block",
    "CopyItem",
    "Channel",
    "UnitSpec",
    "Finding",
    "PlanEntry",
    "Plan",
]
