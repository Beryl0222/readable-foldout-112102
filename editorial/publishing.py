"""出版检查：自足性、版面预算、优先级排版与发布裁决。

规则要点：

* 可单独领取的页面、可直接播放的片段，其中的动作、限制和必要注释
  必须一同可读；选读性跳转可以保留明确的跳转关系。
* 预算按可见 Unicode 字符计。放不下时只能取更狭义而仍真实的说法，
  或撤下整条并给出到哪里询问的提示；不得打乱读屏顺序或丢限制。
* 同一尺寸内先排高优先问题，再排补充例子。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import lexicon
from .discourse import ResolvedReference, STATUS_CONFLICT, STATUS_UNRESOLVED
from .model import (
    Block,
    Channel,
    CopyItem,
    Finding,
    Plan,
    PlanEntry,
    SEV_ERROR,
    SEV_INFO,
    SEV_WARNING,
)

STATUS_READY = "ready"          # 可交印 / 可朗读
STATUS_GATED = "gated"          # 依赖另一单元，不能独立播放/领取
STATUS_BLOCKED = "blocked"      # 有阻止项，暂不可发布


@dataclass
class UnitResult:
    channel_id: str
    unit: str
    independent: bool
    budget: int
    used: int
    status: str
    delivered_text: str
    order: list[str]
    withdrawn: list[dict]
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel_id,
            "unit": self.unit,
            "independent": self.independent,
            "budget": self.budget,
            "used": self.used,
            "status": self.status,
            "delivered_text": self.delivered_text,
            "reading_order": self.order,
            "withdrawn": self.withdrawn,
            "findings": [finding.to_dict() for finding in self.findings],
        }


# ---------------------------------------------------------------------------
# 条目解析
# ---------------------------------------------------------------------------


def entry_text(entry: PlanEntry,
               blocks: dict[str, Block],
               copy: dict[str, CopyItem]) -> str:
    if entry.withdraw:
        return ""
    if entry.block_id is not None:
        return blocks[entry.block_id].text
    if entry.copy_id is not None:
        return copy[entry.copy_id].text
    return entry.text or ""


def _validate_entries(
    channel: Channel,
    plan: Plan,
    blocks: dict[str, Block],
    copy: dict[str, CopyItem],
) -> list[Finding]:
    findings: list[Finding] = []
    known_units = {spec.unit for spec in channel.units}
    for entry in plan.entries:
        if entry.channel_id != channel.id:
            continue
        if entry.unit not in known_units:
            findings.append(Finding(
                code="unknown_unit",
                severity=SEV_ERROR,
                message=f"方案把内容指派给渠道 {channel.id} 不存在的单元 {entry.unit}",
                units=(entry.unit,),
                blocking=True,
            ))
        if entry.block_id and entry.block_id not in blocks:
            findings.append(Finding(
                code="unknown_block",
                severity=SEV_ERROR,
                message=f"方案引用了不存在的原稿块 {entry.block_id}",
                block_ids=(entry.block_id,),
                blocking=True,
            ))
        if entry.copy_id and entry.copy_id not in copy:
            findings.append(Finding(
                code="unknown_copy",
                severity=SEV_ERROR,
                message=f"方案引用了不存在的改写 {entry.copy_id}",
                copy_ids=(entry.copy_id,),
                blocking=True,
            ))
        if entry.withdraw and not entry.pointer_text:
            findings.append(Finding(
                code="withdraw_without_pointer",
                severity=SEV_ERROR,
                message=(
                    f"单元 {entry.unit} 撤下内容但没有给出到哪里询问的提示"
                ),
                units=(entry.unit,),
                blocking=True,
            ))
        if entry.text is not None and not entry.source_ref:
            findings.append(Finding(
                code="rewrite_without_source",
                severity=SEV_ERROR,
                message="方案内联改写缺少 source_ref，无法追溯原稿",
                units=(entry.unit,),
                blocking=True,
            ))
    return findings


# ---------------------------------------------------------------------------
# 自足性
# ---------------------------------------------------------------------------


def _block_ids_in_unit(entries: list[PlanEntry],
                       blocks: dict[str, Block],
                       copy: dict[str, CopyItem]) -> set[str]:
    present: set[str] = set()
    for entry in entries:
        if entry.block_id:
            present.add(entry.block_id)
        present.update(entry.source_ref)
        if entry.copy_id:
            present.update(copy[entry.copy_id].source_ref)
    return present


def check_self_containment(
    channel: Channel,
    spec_unit: str,
    entries: list[PlanEntry],
    blocks: dict[str, Block],
    copy: dict[str, CopyItem],
    references: list[ResolvedReference],
) -> list[Finding]:
    findings: list[Finding] = []
    unit_block_ids = _block_ids_in_unit(entries, blocks, copy)
    # 本单元实际交付文字里出现过的原稿块（含被改写覆盖的 source_ref）
    delivered_ids = {
        ref
        for entry in entries
        if not entry.withdraw
        for ref in (
            (entry.block_id,) if entry.block_id else entry.source_ref
        )
    }

    for ref in references:
        if ref.block_id not in delivered_ids:
            continue
        if ref.status in (STATUS_CONFLICT, STATUS_UNRESOLVED):
            findings.append(Finding(
                code="unresolved_reading_order",
                severity=SEV_ERROR,
                message=(
                    f"{ref.block_id} 的“{ref.marker}”读序未决，"
                    f"{spec_unit} 不能据此出版"
                ),
                block_ids=(ref.block_id,),
                units=(spec_unit,),
                blocking=True,
            ))
            continue
        if not ref.target_ids or not ref.cross_page:
            continue
        # 跨页指代：选读可保留跳转；必要注释必须就地带上
        carried = all(target in unit_block_ids for target in ref.target_ids)
        if ref.optional:
            if not carried:
                findings.append(Finding(
                    code="optional_jump_kept",
                    severity=SEV_INFO,
                    message=(
                        f"{spec_unit} 保留选读跳转“{ref.marker}”→"
                        f"{', '.join(ref.target_ids)}，目标信息不在本单元"
                    ),
                    block_ids=(ref.block_id, *ref.target_ids),
                    units=(spec_unit,),
                ))
            continue
        if not carried:
            findings.append(Finding(
                code="required_note_missing",
                severity=SEV_ERROR,
                message=(
                    f"{spec_unit} 可独立领取/播放，但 {ref.block_id} 的必要注释"
                    f"“{ref.marker}”（→ {', '.join(ref.target_ids)}）"
                    "没有一同带上；读者看不到的页不能为简写补足原意"
                ),
                block_ids=(ref.block_id, *ref.target_ids),
                units=(spec_unit,),
                blocking=True,
            ))
    return findings


# ---------------------------------------------------------------------------
# 预算与优先级排版
# ---------------------------------------------------------------------------


def _priority_rank(channel: Channel, block_id: str | None,
                   blocks: dict[str, Block], entry: PlanEntry) -> tuple[int, int]:
    labels = []
    if block_id and block_id in blocks:
        labels.append(blocks[block_id].label)
    labels.extend(
        blocks[ref].label for ref in entry.source_ref if ref in blocks
    )
    for index, label in enumerate(channel.priority):
        if label in labels:
            return (index, 0)
    # 补充例子/注释排在高优先问题之后
    return (len(channel.priority), 0)


def _pack(
    channel: Channel,
    spec,
    entries: list[PlanEntry],
    blocks: dict[str, Block],
    copy: dict[str, CopyItem],
) -> tuple[list[PlanEntry], list[PlanEntry], list[Finding], int]:
    findings: list[Finding] = []
    # 撤回条目不占预算，但必须有询问提示（校验阶段已查）
    withdrawn_entries = [entry for entry in entries if entry.withdraw]
    active = [entry for entry in entries if not entry.withdraw]
    # support 条目是就地注释依据，不占预算
    support = [entry for entry in active if entry.support]
    script = [entry for entry in active if not entry.support]

    ordered = sorted(
        script,
        key=lambda entry: _priority_rank(
            channel, entry.block_id, blocks, entry
        ),
    )
    used = 0
    accepted: list[PlanEntry] = []
    overflow: list[PlanEntry] = []
    for entry in ordered:
        length = lexicon.visible_len(entry_text(entry, blocks, copy))
        if used + length <= spec.budget:
            used += length
            accepted.append(entry)
        else:
            overflow.append(entry)

    for entry in overflow:
        if entry.note.startswith("narrowed:"):
            # 编校员已声明这是更狭义而仍真实的说法：若仍超预算则阻止
            findings.append(Finding(
                code="narrowed_still_overflow",
                severity=SEV_ERROR,
                message=(
                    f"单元 {spec.unit} 已取狭义说法仍超预算 "
                    f"（{used} + {lexicon.visible_len(entry_text(entry, blocks, copy))}"
                    f" > {spec.budget}）"
                ),
                units=(spec.unit,),
                blocking=True,
            ))
            accepted.append(entry)
            used += lexicon.visible_len(entry_text(entry, blocks, copy))
        else:
            findings.append(Finding(
                code="budget_overflow",
                severity=SEV_ERROR,
                message=(
                    f"单元 {spec.unit} 预算 {spec.budget} 字，"
                    f"“{entry_text(entry, blocks, copy)[:20]}…”排不下；"
                    "只能改取更狭义而真实的说法（narrowed 说明）"
                    "或撤下并给出询问提示，不得压缩限制或打乱读序"
                ),
                units=(spec.unit,),
                blocking=True,
            ))
    # 保持读屏顺序：accepted 已按优先级排序，顺序即朗读顺序，
    # 任何情况下都不允许为塞内容而重排。
    accepted.extend(support)
    return accepted, withdrawn_entries, findings, used


def _render_text(entries: list[PlanEntry],
                 blocks: dict[str, Block],
                 copy: dict[str, CopyItem]) -> tuple[str, list[str]]:
    parts: list[str] = []
    order: list[str] = []
    for entry in entries:
        if entry.support:
            continue
        text = entry_text(entry, blocks, copy)
        if text:
            parts.append(text)
            order.append(
                entry.block_id or entry.copy_id or f"text#{len(order)}"
            )
    return "\n".join(parts), order


# ---------------------------------------------------------------------------
# 单元裁决
# ---------------------------------------------------------------------------


def evaluate_channel(
    channel: Channel,
    plan: Plan,
    blocks: dict[str, Block],
    copy: dict[str, CopyItem],
    references: list[ResolvedReference],
    copy_findings: dict[str, list[Finding]],
) -> list[UnitResult]:
    results: list[UnitResult] = []
    validation = _validate_entries(channel, plan, blocks, copy)

    for spec in channel.units:
        entries = plan.entries_of(channel.id, spec.unit)
        findings = [f for f in validation if spec.unit in f.units]
        # 关联到本单元所用改写的语义发现
        for entry in entries:
            if entry.copy_id and entry.copy_id in copy_findings:
                for finding in copy_findings[entry.copy_id]:
                    if finding.blocking or finding.severity == SEV_ERROR:
                        findings.append(finding)
        # 自足性
        findings.extend(check_self_containment(
            channel, spec.unit, entries, blocks, copy, references
        ))
        # 预算与排版
        accepted, withdrawn, pack_findings, used = _pack(
            channel, spec, entries, blocks, copy
        )
        findings.extend(pack_findings)
        text, order = _render_text(accepted, blocks, copy)

        withdrawn_view = [
            {
                "source_ref": list(entry.source_ref),
                "pointer_text": entry.pointer_text,
                "note": entry.note,
            }
            for entry in withdrawn
        ]
        if entry_narrowed := [e for e in accepted if e.note.startswith("narrowed:")]:
            for entry in entry_narrowed:
                findings.append(Finding(
                    code="narrowed_claim",
                    severity=SEV_WARNING,
                    message=(
                        f"单元 {spec.unit} 使用了更狭义说法：{entry.note[9:]}；"
                        "编校员须确认限制与求助路径仍完整"
                    ),
                    units=(spec.unit,),
                ))

        blocking = any(finding.blocking or
                       finding.severity == SEV_ERROR for finding in findings)
        if blocking:
            status = STATUS_BLOCKED
        elif not spec.independent:
            status = STATUS_GATED
        else:
            status = STATUS_READY

        results.append(UnitResult(
            channel_id=channel.id,
            unit=spec.unit,
            independent=spec.independent,
            budget=spec.budget,
            used=used,
            status=status,
            delivered_text=text,
            order=order,
            withdrawn=withdrawn_view,
            findings=findings,
        ))
    return results
