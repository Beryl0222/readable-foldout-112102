"""编校工具的数据模型与资料装载。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 原稿与渠道数据
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """原稿文字块（layout.json 的一行）。"""

    id: str
    page: str
    bbox: tuple[int, int, int, int]
    label: str
    text: str
    flows: Optional[str] = None

    @property
    def left(self) -> int:
        return self.bbox[0]

    @property
    def top(self) -> int:
        return self.bbox[1]

    @property
    def right(self) -> int:
        return self.bbox[2]

    @property
    def bottom(self) -> int:
        return self.bbox[3]

    @property
    def is_connector(self) -> bool:
        """接续块：带打印流向符号或标注为“接续”。"""
        return self.flows is not None or self.label == "接续"


@dataclass(frozen=True)
class CopyItem:
    """编校稿、签署更正或已发纸件（copy.json 的一行）。"""

    id: str
    kind: str
    source_ref: tuple[str, ...]
    text: str
    page: Optional[str] = None


@dataclass(frozen=True)
class UnitSpec:
    """一个交付单元（印刷页面或音频片段）的承载约定。"""

    unit: str
    budget: int
    independent: bool


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    units: tuple[UnitSpec, ...]
    priority: tuple[str, ...]

    def unit(self, name: str) -> Optional[UnitSpec]:
        for spec in self.units:
            if spec.unit == name:
                return spec
        return None


# ---------------------------------------------------------------------------
# 检查发现
# ---------------------------------------------------------------------------

SEV_ERROR = "error"        # 阻止发布
SEV_WARNING = "warning"    # 需编校员知晓，不阻止
SEV_INFO = "info"          # 记录处理过程


@dataclass
class Finding:
    """一条编校发现。"""

    code: str
    severity: str
    message: str
    finding_id: str = ""
    block_ids: tuple[str, ...] = ()
    copy_ids: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    blocking: bool = False
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.finding_id,
            "code": self.code,
            "severity": self.severity,
            "blocking": self.blocking,
            "message": self.message,
            "blocks": list(self.block_ids),
            "copies": list(self.copy_ids),
            "units": list(self.units),
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# 编校员方案（指派、撤回、读序决定）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanEntry:
    """指派给某渠道单元的一条内容。

    三种来源：
    * block：直接使用原稿文字块；
    * copy：使用 copy.json 中的改写/更正；
    * text：编校员在方案中给出的新易读文字，须带 source_ref。
    另有 withdraw=true 的撤线条目，须带 pointer_text 指明到哪里询问。
    role 为 support 时只作为就地注释/核对依据，不计入交付文字与预算。
    """

    channel_id: str
    unit: str
    source_ref: tuple[str, ...]
    text: Optional[str] = None
    block_id: Optional[str] = None
    copy_id: Optional[str] = None
    withdraw: bool = False
    pointer_text: Optional[str] = None
    support: bool = False
    note: str = ""


@dataclass(frozen=True)
class Decision:
    """布局与语言证据冲突时，编校员对读序/指代的裁决。"""

    block_id: str
    marker: str
    target_id: str
    note: str = ""


@dataclass(frozen=True)
class Plan:
    entries: tuple[PlanEntry, ...]
    decisions: tuple[Decision, ...]

    def decision_for(self, block_id: str, marker: str) -> Optional[Decision]:
        for decision in self.decisions:
            if decision.block_id == block_id and decision.marker in marker:
                return decision
        return None

    def entries_of(self, channel_id: str, unit: str) -> list[PlanEntry]:
        return [
            entry
            for entry in self.entries
            if entry.channel_id == channel_id and entry.unit == unit
        ]


# ---------------------------------------------------------------------------
# 装载与校验
# ---------------------------------------------------------------------------


def load_layout(path: str | Path) -> dict[str, Block]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    blocks: dict[str, Block] = {}
    for row in rows:
        left, top, right, bottom = row["bbox"]
        if not (left < right and top < bottom):
            raise ValueError(f"文字块 {row['id']} 的 bbox 不合法")
        block = Block(
            id=row["id"],
            page=row["page"],
            bbox=(left, top, right, bottom),
            label=row.get("label", ""),
            text=row["text"],
            flows=row.get("flows"),
        )
        if block.id in blocks:
            raise ValueError(f"layout 标识重复：{block.id}")
        blocks[block.id] = block
    return blocks


def load_copy(path: str | Path, layout: dict[str, Block]) -> dict[str, CopyItem]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    items: dict[str, CopyItem] = {}
    for row in rows:
        refs = tuple(row.get("source_ref", ()))
        unknown = [ref for ref in refs if ref not in layout]
        if unknown:
            raise ValueError(f"{row['id']} 引用了不存在的原稿：{unknown}")
        item = CopyItem(
            id=row["id"],
            kind=row["kind"],
            source_ref=refs,
            text=row.get("text", ""),
            page=row.get("page"),
        )
        if item.id in items:
            raise ValueError(f"copy 标识重复：{item.id}")
        items[item.id] = item
    return items


def load_channels(path: str | Path) -> dict[str, Channel]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    channels: dict[str, Channel] = {}
    for row in rows:
        units = tuple(
            UnitSpec(
                unit=u["unit"],
                budget=u["budget"],
                independent=u["independent"],
            )
            for u in row["units"]
        )
        channel = Channel(
            id=row["id"],
            name=row["channel"],
            units=units,
            priority=tuple(row.get("priority", ())),
        )
        channels[channel.id] = channel
    return channels


def load_plan(path: str | Path) -> Plan:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries: list[PlanEntry] = []
    for row in raw.get("assignments", []):
        common = dict(
            channel_id=row["channel"],
            unit=row["unit"],
            source_ref=tuple(row.get("source_ref", ())),
            withdraw=row.get("withdraw", False),
            pointer_text=row.get("pointer_text"),
            support=row.get("role") == "support",
            note=row.get("note", ""),
        )
        if "block" in row:
            common.pop("source_ref", None)
            entries.append(PlanEntry(**common, block_id=row["block"],
                                     source_ref=(row["block"],)))
        elif "copy" in row:
            entries.append(PlanEntry(**common, copy_id=row["copy"]))
        else:
            entries.append(PlanEntry(**common, text=row.get("text")))
    decisions = tuple(
        Decision(
            block_id=row["block"],
            marker=row["marker"],
            target_id=row["target"],
            note=row.get("note", ""),
        )
        for row in raw.get("decisions", [])
    )
    return Plan(entries=tuple(entries), decisions=decisions)
