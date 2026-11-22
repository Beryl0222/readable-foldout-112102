"""窗口更正后的换发影响分析。

更正一个例外（如 copy.json 中的 signed_correction）后：

* 构造“原稿块—注释—改写—已发页—交付单元”的引用图；
* 印刷侧判定哪些页可独立换发、哪些必须整份换发，
  已发纸件的页号保留供读者询问；
* 电子侧在残缺内容不能独立成立时暂停对应片段，其余照常朗读；
* 输出每条结论被哪个读法或说明不足所阻止，附原稿位置与当前改写。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .discourse import ResolvedReference
from .model import (
    Block,
    Channel,
    CopyItem,
    Finding,
    Plan,
    SEV_ERROR,
    SEV_WARNING,
)


@dataclass
class ReissueUnit:
    channel_id: str
    unit: str
    independent: bool
    verdict: str          # reissue / keep / gated / whole_document
    reason: str
    affected_blocks: list[str] = field(default_factory=list)
    stale_copies: list[str] = field(default_factory=list)
    page_number: str | None = None


@dataclass
class CorrectionReport:
    correction_id: str
    changed_blocks: list[str]
    graph: dict[str, list[str]]
    print_units: list[ReissueUnit]
    audio_units: list[ReissueUnit]
    findings: list[Finding]

    def to_dict(self) -> dict:
        return {
            "correction": self.correction_id,
            "changed_blocks": self.changed_blocks,
            "reference_graph": self.graph,
            "print": [unit.__dict__ for unit in self.print_units],
            "audio": [unit.__dict__ for unit in self.audio_units],
            "findings": [finding.to_dict() for finding in self.findings],
        }


def build_reference_graph(
    blocks: dict[str, Block],
    copy: dict[str, CopyItem],
    references: list[ResolvedReference],
) -> dict[str, list[str]]:
    """返回有向邻接表：节点 id -> 它依赖的节点 id。"""
    graph: dict[str, list[str]] = {block_id: [] for block_id in blocks}
    for item in copy.values():
        graph.setdefault(item.id, [])
        for ref in item.source_ref:
            graph[item.id].append(ref)
    for ref in references:
        for target in ref.target_ids:
            graph.setdefault(ref.block_id, [])
            if target not in graph[ref.block_id]:
                graph[ref.block_id].append(target)
    # 去重并保持顺序
    return {node: list(dict.fromkeys(neighbors))
            for node, neighbors in graph.items()}


def _reachable(graph: dict[str, list[str]], starts: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(starts)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return seen


def _embeds(block_id: str, changed: str,
            graph: dict[str, list[str]]) -> bool:
    """block_id 是否把 changed 的内容就地嵌进自身（而非只留跳转指针）。"""
    return changed in _reachable(graph, [block_id])


def analyze_correction(
    correction: CopyItem,
    blocks: dict[str, Block],
    copy: dict[str, CopyItem],
    channels: dict[str, Channel],
    plan: Plan,
    references: list[ResolvedReference],
) -> CorrectionReport:
    assert correction.kind == "signed_correction"
    findings: list[Finding] = []
    graph = build_reference_graph(blocks, copy, references)
    changed = list(correction.source_ref)
    # 反向可达：所有依赖到被更正块的节点（含传递依赖）
    dependents: set[str] = set()
    for node in graph:
        if node in changed:
            continue
        if _reachable(graph, [node]) & set(changed):
            dependents.add(node)

    stale_copies = sorted(
        node for node in dependents
        if node in copy and copy[node].id != correction.id
    )
    findings.append(Finding(
        code="stale_copy",
        severity=SEV_WARNING,
        message=(
            f"更正 {correction.id} 影响原稿 {', '.join(changed)}；"
            f"以下改写/已发件需要复核：{', '.join(stale_copies) or '无'}"
        ),
        block_ids=tuple(changed),
        copy_ids=tuple(stale_copies),
    ))

    print_units: list[ReissueUnit] = []
    audio_units: list[ReissueUnit] = []

    # --- 印刷页面：以原稿页为单位 --------------------------------------
    pages: dict[str, list[str]] = {}
    for block_id, block in blocks.items():
        pages.setdefault(block.page, []).append(block_id)

    changed_set = set(changed)
    for page in sorted(pages):
        page_blocks = pages[page]
        changed_on_page = [b for b in page_blocks if b in changed_set]
        related_refs = [
            ref for ref in references
            if ref.block_id in page_blocks
            and set(ref.target_ids) & changed_set
        ]
        # 就地嵌入：本页的已发件把被更正块列为出处，或本页块本身被更正。
        # 无 page 字段的编校稿是候选改写，不代表任何印刷页已嵌入；
        # 仅出现“见注二”一类跳转则是指针，不算嵌入。
        embedding_copies = sorted({
            item.id
            for item in copy.values()
            if set(item.source_ref) & changed_set
            and item.page == page
        })
        embeds_here = bool(changed_on_page) or bool(embedding_copies)

        if embeds_here:
            # 独立换发条件：被更正内容本身在本页，且其条件/限制不依赖
            # 他页（跨页跳转只出现在别的页时，不影响本页自足）
            own_refs = [
                ref for ref in related_refs
                if any(target in changed_set for target in ref.target_ids)
                and ref.block_id in page_blocks
            ]
            self_contained = bool(changed_on_page) and all(
                target in page_blocks
                for ref in own_refs
                for target in ref.target_ids
            )
            verdict = "reissue_independent" if self_contained \
                else "whole_document"
            reason = (
                "本页承载被更正内容，且限制与条件可在本页内读全，可独立换发；"
                "已发纸件页号保留供读者询问"
                if self_contained else
                "本页被更正内容依赖他页语义，单独换发无法恢复，须整份换发"
            )
            print_units.append(ReissueUnit(
                channel_id="print", unit=page, independent=True,
                verdict=verdict, reason=reason,
                affected_blocks=sorted(
                    set(page_blocks) & (dependents | changed_set)),
                stale_copies=embedding_copies,
                page_number=page,
            ))
        elif related_refs:
            print_units.append(ReissueUnit(
                channel_id="print", unit=page, independent=True,
                verdict="keep",
                reason=(
                    "本页仅以明确跳转指向被更正注释，页号保留供读者询问，"
                    "不必换发；目标页换发后读者按页号可查到新页"
                ),
                affected_blocks=[ref.block_id for ref in related_refs],
                page_number=page,
            ))
        else:
            print_units.append(ReissueUnit(
                channel_id="print", unit=page, independent=True,
                verdict="keep",
                reason="本页与被更正内容无引用关系",
                page_number=page,
            ))

    # --- 电子片段：只处理朗读/音频渠道；印刷渠道已在上面按页处理 --------
    for channel in channels.values():
        is_audio = "朗读" in channel.name or "音频" in channel.name
        if not is_audio:
            continue
        for spec in channel.units:
            entries = plan.entries_of(channel.id, spec.unit)
            unit_refs = {
                ref for entry in entries for ref in entry.source_ref
            }
            unit_copies = {
                entry.copy_id for entry in entries if entry.copy_id
            }
            hits_blocks = unit_refs & set(changed)
            hits_stale = unit_copies & set(stale_copies)
            if not entries or not (
                hits_blocks or hits_stale or unit_refs & dependents
            ):
                verdict = "keep"
                reason = "片段不含被更正内容，可继续播放"
            elif not spec.independent:
                verdict = "gated_with_parent"
                reason = "选读单元本身不独立，随所依附的独立片段一并暂停"
            else:
                verdict = "gated"
                reason = (
                    "片段含被更正内容或陈旧改写，残缺内容不能独立成立，"
                    "暂停该片段；补齐更正前其余片段仍可朗读"
                )
                findings.append(Finding(
                    code="audio_gated",
                    severity=SEV_ERROR,
                    message=(
                        f"{channel.name} {spec.unit} 因更正 "
                        f"{correction.id} 暂不可播放"
                        + (f"，陈旧改写：{', '.join(sorted(hits_stale))}"
                           if hits_stale else "")
                    ),
                    units=(spec.unit,),
                    copy_ids=tuple(sorted(hits_stale)),
                    block_ids=tuple(sorted(hits_blocks)),
                    blocking=True,
                ))
            audio_units.append(ReissueUnit(
                channel_id=channel.id,
                unit=spec.unit,
                independent=spec.independent,
                verdict=verdict,
                reason=reason,
                affected_blocks=sorted(unit_refs &
                                       (dependents | set(changed))),
                stale_copies=sorted(hits_stale),
            ))

    return CorrectionReport(
        correction_id=correction.id,
        changed_blocks=changed,
        graph=graph,
        print_units=print_units,
        audio_units=audio_units,
        findings=findings,
    )
