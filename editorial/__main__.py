"""命令行入口。

用法：
    python3 -m editorial check   data/layout.json data/copy.json \
                                 data/channels.json [--plan plan.json] \
                                 [--json out.json]
    python3 -m editorial correct data/layout.json data/copy.json \
                                 data/channels.json plan.json E5 [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys

from . import pipeline
from .publishing import STATUS_BLOCKED, STATUS_GATED, STATUS_READY

STATUS_LABEL = {
    STATUS_READY: "可发布",
    STATUS_GATED: "依附单元（不独立）",
    STATUS_BLOCKED: "阻止发布",
}

SEVERITY_LABEL = {"error": "错误", "warning": "警告", "info": "说明"}


def _print_findings(findings, indent="  "):
    for finding in findings:
        flag = "⛔" if finding.blocking else {
            "error": "✗", "warning": "⚠", "info": "ℹ"}[finding.severity]
        print(f"{indent}{flag} [{finding.code}] {finding.message}")


def cmd_check(args) -> int:
    report = pipeline.review(
        args.layout, args.copy, args.channels, args.plan
    )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2)

    print("== 栏位与读序 ==")
    for key, members in report.columns.items():
        print(f"  {key}: " + " → ".join(b.id for b in members))
    print("\n== 指代衔接 ==")
    for ref in report.references:
        print(f"  {ref.block_id} “{ref.marker}” [{ref.kind}/{ref.status}]"
              f" → {', '.join(ref.target_ids) or '未决'}"
              + ("（跨页·选读可跳转）" if ref.optional and ref.cross_page
                 else "（跨页·须就地带上）" if ref.cross_page else ""))
    if report.layout_findings:
        print("\n== 版面发现 ==")
        _print_findings(report.layout_findings)

    print("\n== 改写核对 ==")
    for copy_id, findings in report.copy_findings.items():
        print(f"  {copy_id}:")
        if findings:
            _print_findings(findings)
        else:
            print("    ✓ 与原稿力度、限制、施事人一致")

    print("\n== 出版裁决 ==")
    blocked_any = False
    for channel_id, results in report.unit_results.items():
        print(f"  渠道 {channel_id}")
        for result in results:
            label = STATUS_LABEL[result.status]
            print(f"    {result.unit}：{label}"
                  f"（预算 {result.used}/{result.budget}）")
            if result.status == STATUS_BLOCKED:
                blocked_any = True
            _print_findings(result.findings, indent="      ")
            if result.delivered_text:
                first_line = result.delivered_text.splitlines()[0]
                print(f"      首句：{first_line}")

    print("\n== 阻止项汇总 ==")
    blockers = report.blockers()
    if blockers:
        _print_findings(blockers)
        print(f"\n共 {len(blockers)} 项阻止发布。")
        return 1
    print("无阻止项。")
    return 0


def cmd_correct(args) -> int:
    report = pipeline.correction_report(
        args.layout, args.copy, args.channels, args.plan, args.correction
    )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2)

    print(f"== 更正 {report.correction_id}（原稿 "
          f"{', '.join(report.changed_blocks)}）的换发影响 ==")
    print("\n印刷页面：")
    for unit in report.print_units:
        print(f"  {unit.unit}：{unit.verdict} — {unit.reason}")
        if unit.stale_copies:
            print(f"    待替换的已发件/改写：{', '.join(unit.stale_copies)}")
    print("\n电子单元：")
    for unit in report.audio_units:
        print(f"  [{unit.channel_id}] {unit.unit}：{unit.verdict} — {unit.reason}")
    print("\n发现：")
    _print_findings(report.findings)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="editorial",
        description="街道宣传折页编校工具（多栏读序、易读改写、发布门控）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="全套编校检查")
    check.add_argument("layout")
    check.add_argument("copy")
    check.add_argument("channels")
    check.add_argument("--plan", help="编校员方案 JSON")
    check.add_argument("--json", help="把结构化报告写到文件")
    check.set_defaults(func=cmd_check)

    correct = sub.add_parser("correct", help="更正后的换发影响分析")
    correct.add_argument("layout")
    correct.add_argument("copy")
    correct.add_argument("channels")
    correct.add_argument("plan")
    correct.add_argument("correction")
    correct.add_argument("--json", help="把结构化报告写到文件")
    correct.set_defaults(func=cmd_correct)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
