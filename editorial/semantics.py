"""易读改写与原稿的语义核对。

核对四件事，任何一件不过都会形成发现：

1. 允许或要求的力度是否被改变（“可以请求”变成“一定办”）；
2. 限制/反例是否被保留，以及是否仍归属原来的那个动作；
3. 施事人范围与求助对象（问不同人得到什么帮助）；
4. 改写里出现原稿没有的新动作或新承诺。

限制可以用两种方式保留：直接的否定限制（“暂不现场改”），
或条件式许可（“仅持委托……可以递交”）。两者都算约束在位。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import lexicon
from .discourse import BlockSem, ClauseSem, analyze_all
from .model import Block, CopyItem, Finding, SEV_ERROR, SEV_WARNING
from .lexicon import FORCE_RESTRICTION, PERMISSIVE, STRONG


@dataclass(frozen=True)
class ClauseKey:
    action: str
    role: str | None


def _matrix(sems: list[BlockSem]) -> dict[ClauseKey, list[ClauseSem]]:
    matrix: dict[ClauseKey, list[ClauseSem]] = {}
    for block_sem in sems:
        for clause in block_sem.clauses:
            if not clause.actions:
                continue
            # 一个小句只归到其主动作（actions[0]）：限制句里顺带提到的
            # 动作不应与另一小句的许可互相错配。
            roles = clause.roles or (None,)
            for role in roles:
                matrix.setdefault(
                    ClauseKey(clause.actions[0], role), []
                ).append(clause)
    return matrix


def _draft_sem(text: str) -> list[ClauseSem]:
    from .discourse import analyze_clause

    return [analyze_clause(clause)
            for clause in lexicon.split_clauses(text)]


def _constraint_actions(clauses: list[ClauseSem]) -> set[str]:
    """动作上承载的约束。

    否定限制直接约束同小句动作；条件只约束被允许的动作本身
    （“仅持委托……可以递交，现场不改”里条件约束递交，不约束现场更正）。
    """
    actions: set[str] = set()
    for clause in clauses:
        if not clause.actions:
            continue
        if clause.is_restriction:
            actions.update(clause.actions)
        elif clause.is_condition and clause.force in PERMISSIVE:
            actions.add(clause.actions[0])
    return actions


def _source_parts_for(
    key: ClauseKey,
    source_matrix: dict[ClauseKey, list[ClauseSem]],
) -> tuple[list[ClauseSem], bool]:
    """先按动作+施事人精确匹配；施事人对不上时退回同动作任意施事人。"""
    if key in source_matrix:
        return source_matrix[key], True
    same_action = [
        clause
        for matrix_key, clauses in source_matrix.items()
        if matrix_key.action == key.action
        for clause in clauses
    ]
    return same_action, False


def verify_copy_item(
    item: CopyItem,
    blocks: dict[str, Block],
    block_sems: dict[str, BlockSem],
) -> list[Finding]:
    findings: list[Finding] = []
    source_sems = [block_sems[ref] for ref in item.source_ref if ref in block_sems]
    source_matrix = _matrix(source_sems)
    draft_clauses = _draft_sem(item.text)
    draft_matrix = _matrix([
        BlockSem(block_id=item.id, discourse_role="draft",
                 clauses=draft_clauses, help_desk_present=False)
    ])

    source_constraints = _constraint_actions(
        [clause for clauses in source_matrix.values() for clause in clauses]
    )
    source_actions = {
        action
        for key in source_matrix
        for action in (key.action,)
    }
    main_question_sourced = any(
        blocks[ref].label in ("主问一", "主问二")
        for ref in item.source_ref
    )
    contradicted_actions: set[str] = set()

    # --- 逐动作核对 ----------------------------------------------------
    for key, draft_parts in sorted(draft_matrix.items(),
                                   key=lambda kv: kv[0].action):
        source_parts, exact_role = _source_parts_for(key, source_matrix)
        if not source_parts:
            # 请求/许可被改写成承诺（动作换了说法，力度方向也变了）：
            # “可以请求说明”不能变成“窗口一定会办”
            permissive_sources = [
                clause
                for clauses in source_matrix.values()
                for clause in clauses
                if clause.force in PERMISSIVE
            ]
            strong_draft = any(
                part.force in STRONG for part in draft_parts
            )
            if strong_draft and permissive_sources:
                findings.append(Finding(
                    code="modal_force_drift",
                    severity=SEV_ERROR,
                    message=(
                        f"{item.id} 把原稿的请求/许可"
                        f"“{permissive_sources[0].clause}”写成承诺"
                        f"“{draft_parts[0].clause}”；请求说明不等于窗口一定办"
                    ),
                    copy_ids=(item.id,),
                    block_ids=tuple(item.source_ref),
                    blocking=True,
                ))
                continue
            findings.append(Finding(
                code="invented_action",
                severity=SEV_WARNING,
                message=(
                    f"{item.id} 出现原稿没有的动作“{key.action}”，"
                    "简写不得加入原稿未承诺的内容"
                ),
                copy_ids=(item.id,),
                block_ids=tuple(item.source_ref),
            ))
            continue
        if not exact_role:
            source_roles = sorted({
                matrix_key.role
                for matrix_key in source_matrix
                if matrix_key.action == key.action and matrix_key.role
            })
            findings.append(Finding(
                code="agent_scope_changed",
                severity=SEV_WARNING,
                message=(
                    f"{item.id} 中“{key.action}”的施事人 "
                    f"{key.role or '（未指明）'} 与原稿 {source_roles} 不一致，"
                    "请确认问不同人得到的帮助是否被改写"
                ),
                copy_ids=(item.id,),
                block_ids=tuple(item.source_ref),
            ))

        for draft_clause in draft_parts:
            for source_clause in source_parts:
                # 只比较同一动作：限制的是 A 动作，不能用来判 B 动作矛盾
                shared = set(source_clause.actions) & set(draft_clause.actions)
                if not shared:
                    continue
                # 条件只挂在条件句的许可动作上；同小句的否定动作不受条件保护
                source_is_conditional = (
                    source_clause.is_condition
                    and source_clause.force in PERMISSIVE
                    and shared == {source_clause.actions[0]}
                )
                # 普通改写：被否定限制的动作被写成可做/承诺，即方向相反
                if source_clause.is_restriction and not source_is_conditional \
                        and draft_clause.force in PERMISSIVE | STRONG:
                    contradicted_actions.update(shared)
                    findings.append(Finding(
                        code="contradicts_restriction",
                        severity=SEV_ERROR,
                        message=(
                            f"{item.id} 将原稿对“{next(iter(shared))}”的限制"
                            f"“{source_clause.clause}”改写成"
                            f"“{draft_clause.clause}”，允许方向与原稿相反"
                        ),
                        copy_ids=(item.id,),
                        block_ids=tuple(item.source_ref),
                        blocking=True,
                        evidence={"action": next(iter(shared))},
                    ))
                    continue
                # 签署更正允许重订条件，按警告提示编校员核对归属
                if source_is_conditional and item.kind == "signed_correction" \
                        and draft_clause.force in PERMISSIVE | STRONG:
                    contradicted_actions.update(shared)
                    findings.append(Finding(
                        code="correction_changes_condition",
                        severity=SEV_WARNING,
                        message=(
                            f"签署更正 {item.id} 重订了“{next(iter(shared))}”的条件："
                            f"原稿“{source_clause.clause}”→"
                            f"“{draft_clause.clause}”；请核对例外归属与施事人"
                        ),
                        copy_ids=(item.id,),
                        block_ids=tuple(item.source_ref),
                    ))
                    continue
                # 力度漂移：允许类与义务/承诺类互相跳
                source_force = source_clause.force
                draft_force = draft_clause.force
                if source_force != draft_force and \
                        draft_force != lexicon.FORCE_STATEMENT and \
                        source_force != FORCE_RESTRICTION:
                    drifted = (
                        (source_force in PERMISSIVE and draft_force in STRONG)
                        or (source_force in STRONG and draft_force in PERMISSIVE)
                    )
                    if drifted:
                        findings.append(Finding(
                            code="modal_force_drift",
                            severity=SEV_ERROR,
                            message=(
                                f"{item.id} 力度漂移：原稿“{source_clause.clause}”"
                                f"（{source_force}）被写成“{draft_clause.clause}”"
                                f"（{draft_force}）；请求说明不等于窗口一定办"
                            ),
                            copy_ids=(item.id,),
                            block_ids=tuple(item.source_ref),
                            blocking=True,
                        ))

    # --- 限制/反例丢失 -------------------------------------------------
    # 已报“方向相反”的动作不再重复报丢失；条件式许可视为约束保留。
    draft_constraints = _constraint_actions(draft_clauses)
    for action in sorted(source_constraints - contradicted_actions):
        if action in draft_constraints:
            continue
        severity = SEV_ERROR if main_question_sourced else SEV_WARNING
        findings.append(Finding(
            code="restriction_dropped",
            severity=severity,
            message=(
                f"{item.id} 丢掉了原稿对“{action}”的限制或条件"
                + ("（主问的必要限制，阻止发布）" if severity == SEV_ERROR
                   else "（注释/图例中的限制）")
            ),
            copy_ids=(item.id,),
            block_ids=tuple(item.source_ref),
            blocking=severity == SEV_ERROR,
        ))

    # --- 施事人—帮助对照 -----------------------------------------------
    source_roles = {
        role
        for clauses in source_matrix.values()
        for clause in clauses
        for role in clause.roles
    }
    draft_roles = {
        role
        for clauses in draft_matrix.values()
        for clause in clauses
        for role in clause.roles
    }
    missing_roles = source_roles - draft_roles
    if missing_roles:
        findings.append(Finding(
            code="agent_scope_changed",
            severity=SEV_WARNING,
            message=(
                f"{item.id} 未覆盖原稿施事人 {sorted(missing_roles)}，"
                "请确认不同人群得到的帮助差别仍然可读"
            ),
            copy_ids=(item.id,),
            block_ids=tuple(item.source_ref),
        ))
    if any(block_sems[ref].help_desk_present
           for ref in item.source_ref if ref in block_sems) and \
            not any(role in lexicon.HELP_DESK_ROLES
                    for clause in draft_clauses for role in clause.roles):
        findings.append(Finding(
            code="help_desk_lost",
            severity=SEV_WARNING,
            message=f"{item.id} 没有保留“到哪里问/向谁问”的服务台指向",
            copy_ids=(item.id,),
            block_ids=tuple(item.source_ref),
        ))

    # --- source_ref 复核：改写里的动作是否都有原稿出处 -----------------
    for clause in draft_clauses:
        for action in clause.actions:
            if action not in source_actions:
                findings.append(Finding(
                    code="source_ref_gap",
                    severity=SEV_WARNING,
                    message=(
                        f"{item.id} 的动作“{action}”在所列 source_ref "
                        f"{list(item.source_ref)} 中找不到出处"
                    ),
                    copy_ids=(item.id,),
                    block_ids=tuple(item.source_ref),
                ))

    # 同一（代码、动作）的发现只保留一条，信息取首条
    unique: list[Finding] = []
    seen: set[tuple] = set()
    for finding in findings:
        signature = (finding.code, finding.evidence.get("action"))
        if signature not in seen:
            seen.add(signature)
            unique.append(finding)
    return unique


def verify_all(
    copy: dict[str, CopyItem],
    blocks: dict[str, Block],
) -> tuple[dict[str, BlockSem], dict[str, list[Finding]]]:
    block_sems = analyze_all(blocks)
    results: dict[str, list[Finding]] = {}
    for item in copy.values():
        results[item.id] = verify_copy_item(item, blocks, block_sems)
    return block_sems, results
