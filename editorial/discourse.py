"""话语衔接与小句语义识别。

两类产出：

* ``ResolvedReference``：文字块中的指代表达落到哪个原稿块，
  以及布局证据与语言证据是否矛盾；矛盾时交编校员裁决，不擅自决定。
* ``ClauseSem``：小句的力度、动作、施事人、条件/反例性质。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import lexicon
from .geometry import nearest_block
from .model import Block, Finding, Plan, SEV_ERROR, SEV_INFO, SEV_WARNING
from .lexicon import (
    ANAPHORA_PATTERN,
    CONDITION_HINTS,
    COUNTEREXAMPLE_HINTS,
    EXAMPLE_HINTS,
    LABEL_CONNECTOR,
    LABEL_EXAMPLE,
    LABEL_MAIN_QUESTION,
    LABEL_NOTE,
    NOTE_REF_PATTERN,
)


KIND_JUMP = "explicit_jump"          # 见背面注二
KIND_ANAPHORA = "anaphora"           # 上列/下列情形
KIND_CONNECTOR = "connector"         # 接续块（含流向符号）

STATUS_RESOLVED = "resolved"
STATUS_CONFLICT = "conflict"
STATUS_DECIDED = "decided"
STATUS_UNRESOLVED = "unresolved"


@dataclass
class ClauseSem:
    clause: str
    force: str
    action: str | None
    actions: tuple[str, ...]
    roles: tuple[str, ...]
    negated: bool
    is_condition: bool
    is_counterexample: bool
    is_example: bool

    @property
    def is_restriction(self) -> bool:
        return self.force == lexicon.FORCE_RESTRICTION or self.negated


@dataclass
class BlockSem:
    block_id: str
    discourse_role: str  # main_question/example/note/connector/other
    clauses: list[ClauseSem]
    help_desk_present: bool


def analyze_clause(clause: str) -> ClauseSem:
    force = lexicon.detect_force(clause)
    actions = tuple(lexicon.normalize_actions(clause))
    if len(actions) > 1:
        condition_verbs = {"递交更正请求", "咨询", "解释"}
        if force in (lexicon.FORCE_PERMISSION, lexicon.FORCE_REQUEST,
                     lexicon.FORCE_OPTION, lexicon.FORCE_OBLIGATION):
            # 条件/许可复句的主动作是被允许的动作，不是顺带提到的限制
            ordered = ([a for a in actions if a in condition_verbs]
                       + [a for a in actions if a not in condition_verbs])
            actions = tuple(dict.fromkeys(ordered))
        else:
            # 限制复句的主动作是否定动作
            restricted = [a for a in actions if a != "递交更正请求"]
            if restricted:
                actions = tuple(restricted) + tuple(
                    a for a in actions if a not in restricted
                )
    return ClauseSem(
        clause=clause,
        force=force,
        action=actions[0] if actions else None,
        actions=actions,
        roles=tuple(lexicon.find_roles(clause)),
        negated=lexicon.is_negated(clause),
        is_condition=(
            any(hint in clause for hint in CONDITION_HINTS)
            and force in (lexicon.FORCE_PERMISSION, lexicon.FORCE_REQUEST,
                          lexicon.FORCE_OPTION, lexicon.FORCE_OBLIGATION)
        ),
        is_counterexample=any(hint in clause for hint in COUNTEREXAMPLE_HINTS),
        is_example=any(hint in clause for hint in EXAMPLE_HINTS),
    )


@dataclass
class ResolvedReference:
    block_id: str
    marker: str
    kind: str
    status: str
    language_targets: tuple[str, ...]
    geometry_targets: tuple[str, ...]
    target_ids: tuple[str, ...]
    cross_page: bool
    optional: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "block": self.block_id,
            "marker": self.marker,
            "kind": self.kind,
            "status": self.status,
            "language_targets": list(self.language_targets),
            "geometry_targets": list(self.geometry_targets),
            "targets": list(self.target_ids),
            "cross_page": self.cross_page,
            "optional": self.optional,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# 文字块语义
# ---------------------------------------------------------------------------


def discourse_role_of(block: Block) -> str:
    if block.is_connector or block.label in LABEL_CONNECTOR:
        return "connector"
    if block.label in LABEL_MAIN_QUESTION:
        return "main_question"
    if block.label in LABEL_EXAMPLE:
        return "example"
    if block.label in LABEL_NOTE:
        return "note"
    return "other"


def analyze_block(block: Block) -> BlockSem:
    clauses = [analyze_clause(clause)
               for clause in lexicon.split_clauses(block.text)]
    return BlockSem(
        block_id=block.id,
        discourse_role=discourse_role_of(block),
        clauses=clauses,
        help_desk_present=any(
            role in lexicon.HELP_DESK_ROLES
            for clause in clauses
            for role in clause.roles
        ),
    )


def analyze_all(blocks: dict[str, Block]) -> dict[str, BlockSem]:
    return {block_id: analyze_block(block)
            for block_id, block in blocks.items()}


# ---------------------------------------------------------------------------
# 指代解析
# ---------------------------------------------------------------------------


def _find_note_block(blocks: dict[str, Block], number: str) -> Block | None:
    wanted = f"注{number}"
    for block in blocks.values():
        if block.label == wanted:
            return block
    return None


def _language_candidates_for_situation(
    blocks: dict[str, Block], origin: Block,
    columns: dict[str, list[Block]] | None = None,
) -> list[Block]:
    """“上列/下列情形”的语言候选：同页同栏内含情形清单的文字块。

    跨栏块即便出现“情形”字样也不算候选——这正是逐段横抄会制造的
    错接；同栏约束来自版面分栏证据。
    """
    same_column: set[str] = set()
    if columns is not None:
        for members in columns.values():
            ids = {member.id for member in members}
            if origin.id in ids:
                same_column = ids
                break
    candidates = []
    for block in blocks.values():
        if block.id == origin.id or block.page != origin.page:
            continue
        if block.is_connector:
            continue
        if same_column and block.id not in same_column:
            continue
        if block.label in LABEL_EXAMPLE or "情形" in block.text or \
                any(hint in block.text for hint in CONDITION_HINTS) or \
                any(hint in block.text for hint in COUNTEREXAMPLE_HINTS):
            candidates.append(block)
    return candidates


def resolve_references(
    blocks: dict[str, Block],
    columns: dict[str, list[Block]],
    plan: Plan | None = None,
) -> tuple[list[ResolvedReference], list[Finding]]:
    refs: list[ResolvedReference] = []
    findings: list[Finding] = []
    block_list = list(blocks.values())

    for block in block_list:
        # --- 显式跳转：见背面注二 -------------------------------
        for jump in lexicon.find_jump_targets(block.text):
            note_match = NOTE_REF_PATTERN.search(jump)
            optional = lexicon.is_optional_reference(block.text)
            if note_match:
                target = _find_note_block(blocks, note_match.group(1))
                if target is None:
                    refs.append(ResolvedReference(
                        block.id, jump, KIND_JUMP, STATUS_UNRESOLVED,
                        (), (), (), False, optional,
                        f"找不到 {jump} 对应的注释块",
                    ))
                    findings.append(Finding(
                        code="dangling_reference",
                        severity=SEV_ERROR,
                        message=f"{block.id} 的“{jump}”找不到对应注释",
                        block_ids=(block.id,),
                        blocking=True,
                    ))
                    continue
                cross_page = target.page != block.page
                refs.append(ResolvedReference(
                    block.id, jump, KIND_JUMP, STATUS_RESOLVED,
                    (target.id,), (target.id,), (target.id,),
                    cross_page, optional,
                    "可选读跳转" if optional else "必要注释跳转",
                ))
                findings.append(Finding(
                    code="cross_page_reference",
                    severity=SEV_INFO,
                    message=(
                        f"{block.id}“{jump}”指向{target.page}的{target.id}"
                        + ("（选读，可保留跳转）" if optional
                           else "（必要注释，独立单元须就地带上）")
                    ),
                    block_ids=(block.id, target.id),
                    evidence={"optional": optional},
                ))

        # --- 上列/下列情形 --------------------------------------
        for match in ANAPHORA_PATTERN.finditer(block.text):
            marker = match.group(0)
            direction = match.group(1)  # 上列=向上找，下列=向下找
            lang_candidates = _language_candidates_for_situation(
                blocks, block, columns
            )
            # 栏内没有情形块时，回退到同页（可能是跨栏回指，需谨慎）
            same_column_candidates = list(lang_candidates)
            if not lang_candidates:
                lang_candidates = _language_candidates_for_situation(
                    blocks, block, None
                )
            # 按指代方向筛选：上列情形只看上方块，下列情形只看下方块。
            # 分栏块之间有正常行距，纵向边界留出行距余量。
            if direction == "上列":
                lang_candidates = [b for b in lang_candidates
                                   if b.bottom <= block.bottom]
            else:
                lang_candidates = [b for b in lang_candidates
                                   if b.top >= block.top]
            same_page = [b for b in block_list
                         if b.page == block.page and not b.is_connector
                         and b.id != block.id]
            # 上列/下列是纵向阅读关系：几何证据只在同栏上下方向取最近
            same_column_blocks = [
                b for b in same_page
                if b.id in {member.id for members in columns.values()
                            if any(m.id == block.id for m in members)
                            for member in members}
            ]
            geo = nearest_block(block, same_column_blocks or same_page,
                                vertical_only=True)
            lang_ids = tuple(b.id for b in lang_candidates)
            geo_ids = (geo.id,) if geo else ()
            decision = plan.decision_for(block.id, marker) if plan else None

            if decision and decision.target_id in blocks:
                target = blocks[decision.target_id]
                refs.append(ResolvedReference(
                    block.id, marker, KIND_ANAPHORA, STATUS_DECIDED,
                    lang_ids, geo_ids, (target.id,),
                    False, False,
                    f"编校员裁决：{decision.note or target.id}",
                ))
                continue

            lang_set = set(lang_ids)
            geo_set = set(geo_ids)
            if lang_set and geo_set and not (lang_set & geo_set):
                refs.append(ResolvedReference(
                    block.id, marker, KIND_ANAPHORA, STATUS_CONFLICT,
                    lang_ids, geo_ids, (), False, False,
                    "语言证据指向含“情形/条件”的块，几何最近块不同",
                ))
                findings.append(Finding(
                    code="reading_order_conflict",
                    severity=SEV_ERROR,
                    message=(
                        f"{block.id}的“{marker}”：语言证据指向 "
                        f"{', '.join(lang_ids) or '无'}，"
                        f"版面几何最近为 {', '.join(geo_ids) or '无'}；"
                        "读序交编校员裁决后才能出版"
                    ),
                    block_ids=tuple([block.id, *lang_ids, *geo_ids]),
                    blocking=True,
                    evidence={"language": list(lang_ids),
                              "geometry": list(geo_ids)},
                ))
            elif lang_set:
                refs.append(ResolvedReference(
                    block.id, marker, KIND_ANAPHORA, STATUS_RESOLVED,
                    lang_ids, geo_ids, lang_ids, False, False,
                    "语言与几何证据一致",
                ))
            else:
                refs.append(ResolvedReference(
                    block.id, marker, KIND_ANAPHORA, STATUS_UNRESOLVED,
                    (), geo_ids, (), False, False,
                    "找不到含情形清单的候选块",
                ))
                findings.append(Finding(
                    code="dangling_reference",
                    severity=SEV_WARNING,
                    message=f"{block.id}的“{marker}”无可识别的先行块",
                    block_ids=(block.id,),
                ))

        # --- 接续块 ---------------------------------------------
        if block.is_connector:
            same_page = [b for b in block_list
                         if b.page == block.page and not b.is_connector
                         and b.id != block.id]
            geo = nearest_block(block, same_page)
            geo_ids = (geo.id,) if geo else ()
            # 流向符号 → 指向其右缘一侧的同页块
            arrow_targets = [
                b for b in same_page
                if block.flows == "→"
                and b.left >= block.left - 5
                and not (b.right < block.left)
            ]
            arrow_ids = tuple(b.id for b in arrow_targets)
            # 语言锚点：接续文字中的实词（如“原凭据”）落在哪个块
            anchor_blocks: list[str] = []
            anchors = [word for word in ("原凭据", "凭据", "委托")
                       if word in block.text]
            for word in anchors:
                for other in block_list:
                    if other.id != block.id and word in other.text:
                        anchor_blocks.append(other.id)
            lang_ids = tuple(dict.fromkeys(anchor_blocks))
            decision = plan.decision_for(block.id, block.label) if plan else None

            if decision and decision.target_id in blocks:
                refs.append(ResolvedReference(
                    block.id, block.label, KIND_CONNECTOR, STATUS_DECIDED,
                    lang_ids or arrow_ids, geo_ids,
                    (decision.target_id,),
                    False, False,
                    f"编校员裁决：{decision.note or decision.target_id}",
                ))
                continue

            evidence_sets = [set(geo_ids), set(arrow_ids), set(lang_ids)]
            union = set().union(*evidence_sets)
            non_empty = [one for one in evidence_sets if one]
            agreed = len(non_empty) <= 1 or \
                all(one == non_empty[0] for one in non_empty[1:])
            if union and not agreed:
                refs.append(ResolvedReference(
                    block.id, block.label, KIND_CONNECTOR, STATUS_CONFLICT,
                    lang_ids or arrow_ids, geo_ids, (),
                    any(blocks[t].page != block.page
                        for t in lang_ids if t in blocks),
                    lexicon.is_optional_reference(block.text),
                    "流向符号、几何邻近与语言锚点指向不一致",
                ))
                findings.append(Finding(
                    code="reading_order_conflict",
                    severity=SEV_ERROR,
                    message=(
                        f"接续块{block.id}（{block.text}）指向不明："
                        f"几何最近 {', '.join(geo_ids) or '无'}，"
                        f"流向侧 {', '.join(arrow_ids) or '无'}，"
                        f"语言锚点 {', '.join(lang_ids) or '无'}；"
                        "请裁决读序"
                    ),
                    block_ids=tuple([block.id, *sorted(union)]),
                    blocking=True,
                    evidence={
                        "geometry": list(geo_ids),
                        "arrow": list(arrow_ids),
                        "language": list(lang_ids),
                    },
                ))
            elif union:
                targets = tuple(sorted(union))
                refs.append(ResolvedReference(
                    block.id, block.label, KIND_CONNECTOR, STATUS_RESOLVED,
                    lang_ids or arrow_ids, geo_ids, targets,
                    any(blocks[t].page != block.page for t in targets),
                    lexicon.is_optional_reference(block.text),
                    "证据一致",
                ))
            else:
                refs.append(ResolvedReference(
                    block.id, block.label, KIND_CONNECTOR,
                    STATUS_UNRESOLVED, (), (), (), False, False,
                    "没有任何可识别的接续目标",
                ))

    return refs, findings


def reading_order_swap_findings(
    blocks: dict[str, Block],
    columns: dict[str, list[Block]],
) -> list[Finding]:
    """两种读序给出不同先后关系时，提醒逐栏抄录的错接风险。

    只报告承载条件、反例或限制的实质块之间的互换；
    纯接续/图例块的顺序差异不构成例外错接，不打扰编校员。
    """
    from .geometry import compare_orders

    def substantial(block_id: str) -> bool:
        block = blocks[block_id]
        if block.is_connector:
            return False
        return any(
            hint in block.text
            for hint in ("情形", "限制", "暂不", "仅", "不", "情形",
                         "条件", "例外")
        )

    findings: list[Finding] = []
    for first, second in compare_orders(list(blocks.values()), columns):
        if not (substantial(first) and substantial(second)):
            continue
        findings.append(Finding(
            code="reading_order_swap",
            severity=SEV_WARNING,
            message=(
                f"{first} 与 {second} 在逐栏读序和逐行读序中先后相反；"
                "逐段从左到右抄录可能把例外接到另一问题下"
            ),
            block_ids=(first, second),
        ))
    return findings
