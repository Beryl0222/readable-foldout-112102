"""面向这批社区演练宣传稿的语言识别词典与小工具。

识别规则是针对合成稿的关键词/模式启发式，不依赖任何外部服务。
力度分级只比较“允许或要求的强弱方向”，不做完整句法分析。
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# 力度（情态强度）分级：数字越大，对读者的约束越硬
# ---------------------------------------------------------------------------

FORCE_REQUEST = "request"          # 可以请求/提出（对方受理，不保证办妥）
FORCE_PERMISSION = "permission"    # 可以做
FORCE_OPTION = "option"            # 可（自行选择）
FORCE_OBLIGATION = "obligation"    # 须/必须/一定
FORCE_GUARANTEE = "guarantee"      # 一定（承诺会办）
FORCE_RESTRICTION = "restriction"  # 不/暂不/仅（限制）
FORCE_INSTRUCTION = "instruction"  # 请（指引）
FORCE_STATEMENT = "statement"      # 无标记陈述

# 力度漂移的比较顺序：允许类与义务/承诺类之间的跳跃视为力度漂移
PERMISSIVE = {FORCE_REQUEST, FORCE_PERMISSION, FORCE_OPTION}
STRONG = {FORCE_OBLIGATION, FORCE_GUARANTEE}
NEGATIVE = {FORCE_RESTRICTION}

# 标记按从长到短排列，避免“可以”先于“可以请求”匹配
# 标记按从长到短、先肯定后否定排列，避免单字“不/可”抢先匹配
FORCE_MARKERS: tuple[tuple[str, str], ...] = (
    ("可以请求", FORCE_REQUEST),
    ("可以提请求", FORCE_REQUEST),
    ("可以提", FORCE_REQUEST),
    ("可以递交", FORCE_REQUEST),
    ("可递交", FORCE_REQUEST),
    ("可提交", FORCE_REQUEST),
    ("一定会", FORCE_GUARANTEE),
    ("一定", FORCE_GUARANTEE),
    ("必须", FORCE_OBLIGATION),
    ("须为", FORCE_OBLIGATION),
    ("须", FORCE_OBLIGATION),
    ("不需", FORCE_PERMISSION),
    ("不用", FORCE_PERMISSION),
    ("不必", FORCE_PERMISSION),
    ("无须", FORCE_PERMISSION),
    ("无需", FORCE_PERMISSION),
    ("暂不在", FORCE_RESTRICTION),
    ("暂不", FORCE_RESTRICTION),
    ("不会", FORCE_RESTRICTION),
    ("不能", FORCE_RESTRICTION),
    ("不可", FORCE_RESTRICTION),
    ("不在", FORCE_RESTRICTION),
    ("不指", FORCE_RESTRICTION),
    ("仅", FORCE_RESTRICTION),
    ("不", FORCE_RESTRICTION),
    ("可以", FORCE_PERMISSION),
    ("可", FORCE_OPTION),
    ("请", FORCE_INSTRUCTION),
)

# 否定词：真正把动作方向翻转成限制的否定
NEGATION_WORDS = ("暂不", "不能", "不可", "不会", "不在", "不指", "不",
                  "没", "勿", "别")
# “不 + 助动词”其实是许可/义务的软化，不算限制
NEGATED_MODAL = ("不需", "不用", "不必", "无须", "无需")
# 排他/限定词
EXCLUSIVE_WORDS = ("仅", "只是", "只有")

# ---------------------------------------------------------------------------
# 施事人（谁做/向谁求助）
# ---------------------------------------------------------------------------

# 规范角色 -> 别名（长词优先）
ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "原住居民": ("原住居民",),
    "借住家属": ("借住家属",),
    "登记人": ("本人登记人", "登记人", "本人"),
    "亲属": ("亲属",),
    "委托人": ("委托人",),
    "任何代办": ("任何代办", "代办"),
    "服务台": ("服务台", "台前", "窗口"),
}

# 主问中的求助对象（读者向谁问）
HELP_DESK_ROLES = {"服务台"}

# ---------------------------------------------------------------------------
# 动作规范化
# ---------------------------------------------------------------------------

ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"解释|说明", "解释"),
    (r"会办|一定办|办好|办妥|受理", "承诺办理"),
    (r"现场不改|不会改登记|不在现场改|现场改|改登记|改好|更正", "现场更正"),
    (r"递交|提交|提请求|提出.*请求|提(?!供|问)", "递交更正请求"),
    (r"咨询|问情况|问", "咨询"),
    (r"带.*凭据", "携带原凭据"),
    (r"听", "听讲解"),
)

# ---------------------------------------------------------------------------
# 话语角色标签（由文字块 label 与文本共同判断）
# ---------------------------------------------------------------------------

LABEL_MAIN_QUESTION = {"主问一", "主问二"}
LABEL_EXAMPLE = {"例一", "图例"}
LABEL_NOTE = {"注一", "注二"}
LABEL_CONNECTOR = {"接续"}

# 反例/限制的语言线索
COUNTEREXAMPLE_HINTS = ("只提供咨询", "暂不", "不指", "只是", "现场不改",
                        "现场不会改", "不会改", "撤销")
# 条件线索：真正给出前提的表达；“上列/下列情形”只是指代，不算条件
CONDITION_HINTS = ("仅持", "持有", "如果", "若",
                   "有本人委托", "持委托", "有原凭据", "须为", "即可")
EXAMPLE_HINTS = ("事例", "例子", "图中", "借住")

# ---------------------------------------------------------------------------
# 指代表达
# ---------------------------------------------------------------------------

# 可选/选读性质的指代：允许保留为明确跳转
OPTIONAL_REFERENCE_HINTS = ("备用", "选读", "另听", "可以另")

# 显式跳转目标的正则：见/参见 + 位置
JUMP_PATTERN = re.compile(r"(见|参见)([一-龥A-Za-z0-9]+注?[一二三四五六七八九]?)")
# 注号
NOTE_REF_PATTERN = re.compile(r"注([一二三四五六七八九])")
# 上列/下列
ANAPHORA_PATTERN = re.compile(r"(上列|下列)情形")


def split_clauses(text: str) -> list[str]:
    """按中文句读切分成小句，去掉空白片段。

    逗号也切：一个复句里可能同时承载条件许可（“仅持委托……可以递交”）
    和否定限制（“现场不改”），必须分开识别力度。
    """
    parts = re.split(r"[。；;！!？?，,]", text)
    return [part.strip() for part in parts if part.strip()]


def visible_len(text: str) -> int:
    """渠道约定的预算口径：可见 Unicode 字符（忽略空白）。"""
    return sum(1 for ch in text if not ch.isspace())


def detect_force(clause: str) -> Optional[str]:
    """返回小句的力度。

    先看情态词（“不需/不用”是许可而非限制）；条件句中的“仅/只是”
    是前提的一部分（“仅持委托……可以递交”），不把整句压成限制；
    没有情态词时，否定动词或排他词才构成限制。
    """
    if any(word in clause for word in NEGATED_MODAL):
        return FORCE_PERMISSION
    found: list[str] = []
    for marker, force in FORCE_MARKERS:
        if marker in clause:
            found.append(force)
    has_condition = any(hint in clause for hint in CONDITION_HINTS)
    if found:
        modal_forces = [force for force in found if force != FORCE_RESTRICTION]
        # 条件句里“仅”等排他词服务于前提，情态词决定整句力度
        if has_condition and modal_forces:
            for force in (FORCE_OBLIGATION, FORCE_GUARANTEE, FORCE_REQUEST,
                          FORCE_PERMISSION, FORCE_OPTION, FORCE_INSTRUCTION):
                if force in modal_forces:
                    return force
        # 限制优先：一个小句里出现否定，力度按限制处理
        if FORCE_RESTRICTION in found:
            return FORCE_RESTRICTION
        # 义务/承诺优先于普通许可
        for force in (FORCE_OBLIGATION, FORCE_GUARANTEE, FORCE_REQUEST,
                      FORCE_PERMISSION, FORCE_OPTION, FORCE_INSTRUCTION):
            if force in found:
                return force
        return found[0]
    if any(word in clause for word in EXCLUSIVE_WORDS):
        return FORCE_RESTRICTION
    return FORCE_STATEMENT


def is_negated(clause: str) -> bool:
    if any(word in clause for word in NEGATED_MODAL):
        return False
    return any(word in clause for word in NEGATION_WORDS)


def find_roles(text: str) -> list[str]:
    """按长别名优先扫描文本中出现的规范角色。"""
    hits: list[tuple[int, str]] = []
    for canonical, aliases in ROLE_ALIASES.items():
        for alias in aliases:
            start = text.find(alias)
            if start >= 0:
                hits.append((start, canonical))
    # 同一规范角色去重，保持出现顺序
    seen: set[str] = set()
    ordered: list[str] = []
    for _, role in sorted(hits, key=lambda item: item[0]):
        if role not in seen:
            seen.add(role)
            ordered.append(role)
    return ordered


def normalize_actions(clause: str) -> list[str]:
    """一个小句可能承载多个动作（如“可以递交……现场不改”），全部返回。"""
    actions: list[str] = []
    for pattern, canonical in ACTION_PATTERNS:
        if re.search(pattern, clause) and canonical not in actions:
            actions.append(canonical)
    return actions


def normalize_action(clause: str) -> Optional[str]:
    actions = normalize_actions(clause)
    return actions[0] if actions else None


def find_jump_targets(text: str) -> list[str]:
    """抽取“见背面注二”一类的显式跳转目标短语。"""
    return [match.group(0) for match in JUMP_PATTERN.finditer(text)]


def note_number(target: str) -> Optional[str]:
    match = NOTE_REF_PATTERN.search(target)
    return match.group(1) if match else None


def is_optional_reference(text: str) -> bool:
    return any(hint in text for hint in OPTIONAL_REFERENCE_HINTS)
