#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
4 个能力接口单独调用完整测试：校验预期能力输出与结构；
涉及需补全信息时，校验接口能正常反馈（如 200 + 说明或空数据），不 500。
报告保存：能力接口返回 JSON；Word 报告由对话流中 word_report 插件生成，可通过 GET /api/v1/reports/{filename} 下载。
使用：先启动后端，再运行 python scripts/run_capability_apis_full_test.py
  SKIP_SLOW=1 可跳过 content-direction-ranking、weekly-decision-snapshot（需 LLM）
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
PREFIX = f"{BASE_URL}/api/v1/capabilities"
SKIP_SLOW = os.getenv("SKIP_SLOW", "").strip().lower() in ("1", "true", "yes")
TIMEOUT_SLOW = 120
TIMEOUT_FAST = 25


def get(path: str, params: Dict[str, Any] | None = None, timeout: int = TIMEOUT_FAST) -> Tuple[int, Dict[str, Any]]:
    url = f"{PREFIX}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {"_raw": (r.text or "")[:500]}
        return r.status_code, body
    except requests.exceptions.ConnectionError as e:
        return 0, {"error": f"连接失败: {e}"}
    except Exception as e:
        return 0, {"error": str(e)}


def test_content_direction_ranking() -> Tuple[bool, List[str]]:
    """内容方向榜单：期望 200、success、data.items 为列表；可空（缓存未就绪）。"""
    issues: List[str] = []
    code, body = get("/content-direction-ranking", {"platform": "xiaohongshu"}, TIMEOUT_SLOW)
    if code != 200:
        issues.append(f"HTTP {code}")
        return False, issues
    if not body.get("success"):
        issues.append(f"success=False: {body.get('error','')[:80]}")
        return False, issues
    data = body.get("data") or {}
    items = data.get("items")
    if items is not None and not isinstance(items, list):
        issues.append("data.items 非数组")
    return len(issues) == 0, issues


def test_case_library() -> Tuple[bool, List[str]]:
    """定位决策案例库：期望 200、success、data 含 items 或 list 数组。"""
    issues: List[str] = []
    code, body = get("/case-library", {"page": 1, "page_size": 5})
    if code != 200:
        issues.append(f"HTTP {code}")
        return False, issues
    if not body.get("success"):
        issues.append(f"success=False: {body.get('error','')[:80]}")
        return False, issues
    data = body.get("data") or {}
    items = data.get("items", data.get("list", []))
    if not isinstance(items, list):
        issues.append("data 缺少 items/list 或非数组")
    return len(issues) == 0, issues


def test_content_positioning_matrix() -> Tuple[bool, List[str]]:
    """内容定位矩阵：期望 200、success、data.matrix 为数组（9 或 12 格）。"""
    issues: List[str] = []
    code, body = get("/content-positioning-matrix", {"industry": "教育"})
    if code != 200:
        issues.append(f"HTTP {code}")
        return False, issues
    if not body.get("success"):
        issues.append(f"success=False: {body.get('error','')[:80]}")
        return False, issues
    data = body.get("data") or {}
    matrix = data.get("matrix")
    if matrix is None:
        issues.append("缺少 data.matrix")
    elif not isinstance(matrix, list):
        issues.append("data.matrix 非数组")
    elif len(matrix) < 9:
        issues.append(f"matrix 长度至少 9，当前 {len(matrix)}")
    return len(issues) == 0, issues


def test_weekly_decision_snapshot(with_user: bool = True) -> Tuple[bool, List[str]]:
    """每周决策快照：期望 200、success、data 含 stage/priorities/forbidden/weekly_focus/history。
    若缺 user 或上下文导致内容为空，仍为 200 且结构完整即视为可接受（智能识别后反馈）。"""
    issues: List[str] = []
    params = {"user_id": "full_test_user"} if with_user else {}
    code, body = get("/weekly-decision-snapshot", params, TIMEOUT_SLOW)
    if code != 200:
        issues.append(f"HTTP {code}")
        return False, issues
    if not body.get("success"):
        issues.append(f"success=False: {body.get('error','')[:80]}")
        return False, issues
    data = body.get("data") or {}
    for key in ("stage", "priorities", "forbidden", "weekly_focus", "history"):
        if key not in data:
            issues.append(f"缺少 data.{key}")
    if not isinstance(data.get("priorities"), list):
        issues.append("data.priorities 应为数组")
    if not isinstance(data.get("forbidden"), list):
        issues.append("data.forbidden 应为数组")
    if not isinstance(data.get("history"), list):
        issues.append("data.history 应为数组")
    return len(issues) == 0, issues


def main() -> int:
    print("=" * 60)
    print("4 能力接口单独调用完整测试")
    print("=" * 60)
    print(f"BASE_URL = {BASE_URL}, SKIP_SLOW = {SKIP_SLOW}")
    # 连接检查
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code != 200:
            print("警告: /health 返回非 200，请确认后端已启动。")
    except Exception as e:
        print(f"无法连接后端 ({BASE_URL})：{e}")
        print("请先启动：uvicorn main:app --reload --port 8000")
        return 1
    print()

    results: List[Tuple[str, bool, List[str]]] = []

    # 1
    print("[1] content-direction-ranking ...")
    if SKIP_SLOW:
        print("    已跳过 (SKIP_SLOW=1)")
        results.append(("content-direction-ranking", True, []))
    else:
        ok, issues = test_content_direction_ranking()
        results.append(("content-direction-ranking", ok, issues))
        print("    OK" if ok else f"    FAIL: {issues}")

    # 2
    print("[2] case-library ...")
    ok, issues = test_case_library()
    results.append(("case-library", ok, issues))
    print("    OK" if ok else f"    FAIL: {issues}")

    # 3
    print("[3] content-positioning-matrix ...")
    ok, issues = test_content_positioning_matrix()
    results.append(("content-positioning-matrix", ok, issues))
    print("    OK" if ok else f"    FAIL: {issues}")

    # 4
    print("[4] weekly-decision-snapshot ...")
    if SKIP_SLOW:
        print("    已跳过 (SKIP_SLOW=1)")
        results.append(("weekly-decision-snapshot", True, []))
    else:
        ok, issues = test_weekly_decision_snapshot(with_user=True)
        results.append(("weekly-decision-snapshot", ok, issues))
        print("    OK" if ok else f"    FAIL: {issues}")

    # 5 缺参时仍正常返回（不 500），智能识别/默认值
    print("[5] weekly-decision-snapshot 缺 user_id（期望仍 200 + 结构）...")
    if SKIP_SLOW:
        print("    已跳过 (SKIP_SLOW=1)")
    else:
        ok, issues = test_weekly_decision_snapshot(with_user=False)
        results.append(("weekly-decision-snapshot(no user_id)", ok, issues))
        print("    OK" if ok else f"    FAIL: {issues}")

    print()
    print("--- 报告说明 ---")
    print("能力接口返回 JSON，不直接写 Word。Word 报告在对话流中由 word_report 插件生成，")
    print("生成后可通过 GET /api/v1/reports/{filename} 下载。需补全信息时由主流程澄清引导。")
    print()

    failed = [(n, i) for n, ok, i in results if not ok]
    if failed:
        print("=" * 60)
        for name, issues in failed:
            print(f"  [FAIL] {name}: {issues}")
        print("=" * 60)
        return 1
    print("=" * 60)
    print("4 能力接口测试全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
