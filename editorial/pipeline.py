"""主编排：装载资料、跑全部检查、汇总可交印/可朗读结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import corrections as corrections_mod
from . import discourse, geometry, publishing, semantics
from .model import (
    Block,
    Finding,
    Plan,
    load_channels,
    load_copy,
    load_layout,
    load_plan,
)


@dataclass
class ReviewReport:
    blocks: dict[str, Block]
    columns: dict[str, list[Block]]
    references: list[discourse.ResolvedReference]
    block_sems: dict[str, discourse.BlockSem]
    copy_findings: dict[str, list[Finding]]
    layout_findings: list[Finding]
    unit_results: dict[str, list[publishing.UnitResult]]
    all_findings: list[Finding] = field(default_factory=list)

    def blockers(self) -> list[Finding]:
        return [finding for finding in self.all_findings if finding.blocking]

    def to_dict(self) -> dict:
        return {
            "columns": {
                key: [block.id for block in members]
                for key, members in self.columns.items()
            },
            "references": [ref.to_dict() for ref in self.references],
            "block_semantics": {
                block_id: {
                    "discourse_role": sem.discourse_role,
                    "clauses": [
                        {
                            "clause": clause.clause,
                            "force": clause.force,
                            "action": clause.action,
                            "roles": list(clause.roles),
                            "negated": clause.negated,
                            "is_condition": clause.is_condition,
                            "is_counterexample": clause.is_counterexample,
                            "is_example": clause.is_example,
                        }
                        for clause in sem.clauses
                    ],
                    "help_desk_present": sem.help_desk_present,
                }
                for block_id, sem in self.block_sems.items()
            },
            "copy_findings": {
                copy_id: [f.to_dict() for f in findings]
                for copy_id, findings in self.copy_findings.items()
            },
            "layout_findings": [f.to_dict() for f in self.layout_findings],
            "publication": {
                channel_id: [result.to_dict() for result in results]
                for channel_id, results in self.unit_results.items()
            },
            "blockers": [f.to_dict() for f in self.blockers()],
        }


def review(
    layout_path: str | Path,
    copy_path: str | Path,
    channels_path: str | Path,
    plan_path: str | Path | None = None,
) -> ReviewReport:
    blocks = load_layout(layout_path)
    copy = load_copy(copy_path, blocks)
    channels = load_channels(channels_path)
    plan = load_plan(plan_path) if plan_path else Plan((), ())

    columns = geometry.group_columns(list(blocks.values()))
    references, ref_findings = discourse.resolve_references(
        blocks, columns, plan
    )
    swap_findings = discourse.reading_order_swap_findings(blocks, columns)
    layout_findings = ref_findings + swap_findings

    block_sems, copy_findings = semantics.verify_all(copy, blocks)

    unit_results: dict[str, list[publishing.UnitResult]] = {}
    for channel in channels.values():
        unit_results[channel.id] = publishing.evaluate_channel(
            channel, plan, blocks, copy, references, copy_findings
        )

    all_findings = list(layout_findings)
    for findings in copy_findings.values():
        all_findings.extend(findings)
    for results in unit_results.values():
        for result in results:
            all_findings.extend(result.findings)

    return ReviewReport(
        blocks=blocks,
        columns=columns,
        references=references,
        block_sems=block_sems,
        copy_findings=copy_findings,
        layout_findings=layout_findings,
        unit_results=unit_results,
        all_findings=all_findings,
    )


def correction_report(
    layout_path: str | Path,
    copy_path: str | Path,
    channels_path: str | Path,
    plan_path: str | Path,
    correction_id: str,
) -> corrections_mod.CorrectionReport:
    blocks = load_layout(layout_path)
    copy = load_copy(copy_path, blocks)
    channels = load_channels(channels_path)
    plan = load_plan(plan_path)
    columns = geometry.group_columns(list(blocks.values()))
    references, _ = discourse.resolve_references(blocks, columns, plan)
    if correction_id not in copy:
        raise KeyError(f"找不到更正 {correction_id}")
    return corrections_mod.analyze_correction(
        copy[correction_id], blocks, copy, channels, plan, references
    )
