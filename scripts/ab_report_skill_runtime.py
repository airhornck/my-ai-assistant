#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
基于应用日志聚合 skill runtime 的 A/B 粗报表。

用法：
  python scripts/ab_report_skill_runtime.py --log app.log
  python scripts/ab_report_skill_runtime.py --log logs/server.log --json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="聚合 trace_event A/B 报表")
    p.add_argument("--log", required=True, help="日志文件路径")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    return p.parse_args()


def parse_trace_event(line: str) -> dict[str, Any] | None:
    mark = "trace_event:"
    if mark not in line:
        return None
    idx = line.find(mark)
    payload = line[idx + len(mark) :].strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def main() -> int:
    args = parse_args()
    path = Path(args.log)
    if not path.exists():
        print(f"[ERROR] 日志文件不存在: {path}")
        return 2

    per_trace: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            ev = parse_trace_event(line)
            if not ev:
                continue
            tid = str(ev.get("trace_id") or "").strip()
            if not tid:
                continue
            rec = per_trace.setdefault(
                tid,
                {
                    "trace_id": tid,
                    "bucket": "",
                    "failed": False,
                    "fallback_applied": False,
                    "failure_code": "",
                    "interrupted": False,
                    "evaluation_score": None,
                },
            )
            if ev.get("ab_bucket"):
                rec["bucket"] = ev.get("ab_bucket")
            if ev.get("skill_ab_bucket"):
                rec["bucket"] = ev.get("skill_ab_bucket")
            if ev.get("stage") == "fallback" and ev.get("action") == "fallback_applied":
                rec["fallback_applied"] = True
            fc = str(ev.get("failure_code") or "").strip()
            if fc:
                rec["failed"] = True
                rec["failure_code"] = fc
            if ev.get("interrupted") is True:
                rec["interrupted"] = True
            if ev.get("stage") == "final" and ev.get("evaluation_score") is not None:
                rec["evaluation_score"] = ev.get("evaluation_score")

    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"runs": 0, "failed": 0, "fallback_applied": 0, "interrupted": 0, "scores": [], "satisfied_proxy": 0}
    )
    for rec in per_trace.values():
        bucket = rec.get("bucket") or "UNKNOWN"
        a = agg[bucket]
        a["runs"] += 1
        a["failed"] += 1 if rec.get("failed") else 0
        a["fallback_applied"] += 1 if rec.get("fallback_applied") else 0
        a["interrupted"] += 1 if rec.get("interrupted") else 0
        score = rec.get("evaluation_score")
        if isinstance(score, (int, float)):
            a["scores"].append(float(score))
        # 满意度代理：非中断 + 无失败码 + 评估分 >= 6
        if (not rec.get("interrupted")) and (not rec.get("failed")) and isinstance(score, (int, float)) and float(score) >= 6.0:
            a["satisfied_proxy"] += 1

    out = {}
    for bucket, a in sorted(agg.items()):
        runs = max(a["runs"], 1)
        avg_score = (sum(a["scores"]) / len(a["scores"])) if a["scores"] else None
        out[bucket] = {
            "runs": a["runs"],
            "failed": a["failed"],
            "failed_rate": round(a["failed"] / runs, 4),
            "fallback_applied": a["fallback_applied"],
            "fallback_rate": round(a["fallback_applied"] / runs, 4),
            "interrupted": a["interrupted"],
            "interrupt_rate": round(a["interrupted"] / runs, 4),
            "satisfied_proxy": a["satisfied_proxy"],
            "satisfied_proxy_rate": round(a["satisfied_proxy"] / runs, 4),
            "avg_evaluation_score": round(avg_score, 4) if avg_score is not None else None,
        }

    if args.json:
        print(json.dumps({"summary": out, "trace_count": len(per_trace)}, ensure_ascii=False, indent=2))
    else:
        print("=== Skill Runtime A/B Report ===")
        print(f"trace_count: {len(per_trace)}")
        for bucket, row in out.items():
            print(
                f"- bucket={bucket} runs={row['runs']} failed={row['failed']} "
                f"failed_rate={row['failed_rate']:.2%} fallback={row['fallback_applied']} "
                f"fallback_rate={row['fallback_rate']:.2%} interrupted={row['interrupted']} "
                f"interrupt_rate={row['interrupt_rate']:.2%} satisfied_proxy={row['satisfied_proxy']} "
                f"satisfied_proxy_rate={row['satisfied_proxy_rate']:.2%} avg_score={row['avg_evaluation_score']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
