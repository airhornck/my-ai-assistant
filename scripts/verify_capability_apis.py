#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证 Lumina 四模块能力接口：请求四个 GET 接口，校验响应结构与输出质量。
使用方式：先启动服务 (uvicorn main:app --reload)，再运行本脚本。
  python scripts/verify_capability_apis.py
  BASE_URL=http://127.0.0.1:8000 python scripts/verify_capability_apis.py
  SKIP_SLOW=1  # 跳过需调用 AI 的接口（内容方向榜单、每周决策快照），仅验证案例库与矩阵
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Tuple

# Windows 控制台 UTF-8
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
CAPABILITY_PREFIX = f"{BASE_URL}/api/v1/capabilities"
SKIP_SLOW = os.getenv("SKIP_SLOW", "").strip().lower() in ("1", "true", "yes")
# 内容方向榜单、每周决策快照会调 LLM，超时设长
TIMEOUT_SLOW = 120
TIMEOUT_FAST = 15


def get(path: str, params: Dict[str, Any] | None = None, timeout: int = TIMEOUT_FAST) -> Tuple[int, Dict[str, Any]]:
    """GET 请求，返回 (status_code, json_body)。"""
    url = f"{CAPABILITY_PREFIX}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text[:500]}
        return r.status_code, body
    except requests.exceptions.ConnectionError as e:
        return 0, {"error": f"连接失败（请确认服务已启动）: {e}"}
    except Exception as e:
        return 0, {"error": str(e)}


def verify_content_direction_ranking() -> List[str]:
    """验证 1. 内容方向榜单"""
    issues: List[str] = []
    code, body = get("/content-direction-ranking", params={"platform": "xiaohongshu"})
    if code != 200:
        issues.append(f"HTTP {code}，期望 200")
        return issues
    if not body.get("success"):
        issues.append(f"success 为 False: {body.get('error', '')}")
        return issues
    data = body.get("data") or {}
    items = data.get("items")
    if items is None:
        issues.append("缺少 data.items")
        return issues
    if not isinstance(items, list):
        issues.append("data.items 非数组")
        return issues
    # 质量：若来自 content_direction_ranking，应有适配度/风险/角度等
    source = body.get("source", "")
    if source == "content_direction_ranking" and len(items) > 0:
        first = items[0]
        if not isinstance(first, dict):
            issues.append("items[0] 非对象")
        else:
            if first.get("adaptation_score") is None and first.get("risk_level") is None:
                issues.append("首条缺少 adaptation_score / risk_level（可能 AI 未按约定返回）")
            if not first.get("angles") and not first.get("title_suggestion"):
                issues.append("首条缺少 angles 或 title_suggestion")
    if len(items) == 0 and source == "topic_selection":
        issues.append("回退到 topic_selection 且 items 为空（热点/选题缓存可能未就绪）")
    # 质量：有内容时首条应具备可读性
    if len(items) > 0 and isinstance(items[0], dict):
        t = (items[0].get("title_suggestion") or items[0].get("title") or "").strip()
        if len(t) < 2:
            issues.append("首条标题过短或为空，影响可读性")
    return issues


def verify_case_library() -> List[str]:
    """验证 2. 定位决策案例库"""
    issues: List[str] = []
    code, body = get("/case-library", params={"page": 1, "page_size": 5})
    if code != 200:
        issues.append(f"HTTP {code}，期望 200")
        return issues
    if not body.get("success"):
        issues.append(f"success 为 False: {body.get('error', '')}")
        return issues
    data = body.get("data") or {}
    # 与 CaseTemplateService.list_cases 一致：应有 items 或 list
    items = data.get("items", data.get("list", []))
    if not isinstance(items, list):
        issues.append("data 中缺少 items/list 或非数组")
    return issues


def verify_content_positioning_matrix() -> List[str]:
    """验证 3. 内容定位矩阵"""
    issues: List[str] = []
    code, body = get("/content-positioning-matrix", params={"industry": "教育"})
    if code != 200:
        issues.append(f"HTTP {code}，期望 200")
        return issues
    if not body.get("success"):
        issues.append(f"success 为 False: {body.get('error', '')}")
        return issues
    data = body.get("data") or {}
    matrix = data.get("matrix")
    if matrix is None:
        issues.append("缺少 data.matrix")
        return issues
    if not isinstance(matrix, list):
        issues.append("data.matrix 非数组")
        return issues
    # 3x4 = 12 格
    if len(matrix) != 12:
        issues.append(f"matrix 长度应为 12（3×4），当前 {len(matrix)}")
    for i, cell in enumerate(matrix):
        if not isinstance(cell, dict):
            issues.append(f"matrix[{i}] 非对象")
            continue
        for key in ("priority", "stage", "boundary", "suggestion", "example"):
            if key not in cell:
                issues.append(f"matrix[{i}] 缺少字段 {key}")
    persona = data.get("persona")
    if persona is not None and not isinstance(persona, dict):
        issues.append("data.persona 应为对象")
    return issues


def verify_weekly_decision_snapshot() -> List[str]:
    """验证 4. 每周决策快照"""
    issues: List[str] = []
    code, body = get("/weekly-decision-snapshot", params={"user_id": "verify_user"}, timeout=90)
    if code != 200:
        issues.append(f"HTTP {code}，期望 200")
        return issues
    if not body.get("success"):
        issues.append(f"success 为 False: {body.get('error', '')}")
        return issues
    data = body.get("data") or {}
    for key in ("stage", "max_risk", "priorities", "forbidden", "weekly_focus", "history"):
        if key not in data:
            issues.append(f"缺少 data.{key}")
    if not isinstance(data.get("priorities"), list):
        issues.append("data.priorities 应为数组")
    if not isinstance(data.get("forbidden"), list):
        issues.append("data.forbidden 应为数组")
    if not isinstance(data.get("history"), list):
        issues.append("data.history 应为数组")
    # 质量：禁区应有至少一条建议
    forbidden = data.get("forbidden") or []
    if len(forbidden) == 0:
        issues.append("data.forbidden 为空，期望至少包含默认禁区说明")
    return issues


def main() -> None:
    print(f"BASE_URL = {BASE_URL}")
    print("=" * 60)

    results: List[Tuple[str, List[str], Any]] = []

    # 1. 内容方向榜单（慢，可能 SKIP_SLOW 跳过）
    print("\n[1] GET /api/v1/capabilities/content-direction-ranking ...")
    if SKIP_SLOW:
        print("    已跳过 (SKIP_SLOW=1)")
        results.append(("内容方向榜单", [], {}))
    else:
        issues1 = verify_content_direction_ranking()
        code1, body1 = get("/content-direction-ranking", params={"platform": "xiaohongshu"}, timeout=TIMEOUT_SLOW)
        results.append(("内容方向榜单", issues1, body1))
        if code1 != 200:
            print("    请求失败: HTTP", code1, body1.get("error", "")[:80])
        elif issues1:
            print("    存在问题:", issues1)
        else:
            items = (body1.get("data") or {}).get("items") or []
            print(f"    通过。items 数量={len(items)}, source={body1.get('source')}")
            if items and isinstance(items[0], dict):
                print("    首条示例:", str(items[0].get("title_suggestion") or items[0].get("title") or items[0])[:80])

    # 2. 案例库
    print("\n[2] GET /api/v1/capabilities/case-library ...")
    issues2 = verify_case_library()
    code2, body2 = get("/case-library", params={"page": 1, "page_size": 5})
    results.append(("案例库", issues2, body2))
    if issues2:
        print("    存在问题:", issues2)
    else:
        data2 = body2.get("data") or {}
        items2 = data2.get("items", data2.get("list", []))
        print(f"    通过。案例数量={len(items2) if isinstance(items2, list) else 'N/A'}")

    # 3. 内容定位矩阵
    print("\n[3] GET /api/v1/capabilities/content-positioning-matrix ...")
    issues3 = verify_content_positioning_matrix()
    code3, body3 = get("/content-positioning-matrix")
    results.append(("内容定位矩阵", issues3, body3))
    if issues3:
        print("    存在问题:", issues3)
    else:
        matrix = (body3.get("data") or {}).get("matrix") or []
        print(f"    通过。matrix 格子数={len(matrix)}")

    # 4. 每周决策快照（慢，可能 SKIP_SLOW 跳过）
    print("\n[4] GET /api/v1/capabilities/weekly-decision-snapshot ...")
    if SKIP_SLOW:
        print("    已跳过 (SKIP_SLOW=1)")
        results.append(("每周决策快照", [], {}))
    else:
        issues4 = verify_weekly_decision_snapshot()
        code4, body4 = get("/weekly-decision-snapshot", params={"user_id": "verify_user"}, timeout=TIMEOUT_SLOW)
        results.append(("每周决策快照", issues4, body4))
        if code4 != 200:
            print("    请求失败: HTTP", code4, body4.get("error", "")[:80])
        elif issues4:
            print("    存在问题:", issues4)
        else:
            data4 = body4.get("data") or {}
            print(f"    通过。stage={data4.get('stage')}, priorities 条数={len(data4.get('priorities') or [])}")
            print("    weekly_focus 示例:", (data4.get("weekly_focus") or "")[:60])

    # 汇总
    print("\n" + "=" * 60)
    all_ok = True
    for name, issues, _ in results:
        if issues:
            print(f"  [FAIL] {name}: {issues}")
            all_ok = False
        else:
            print(f"  [OK]   {name}")
    if body1.get("error") and ("连接" in str(body1.get("error", "")) or "Connection" in str(body1.get("error", ""))):
        print("\n[提示] 连接失败，请先启动服务:")
        print("  uvicorn main:app --reload --port 8000")
        print("  需配置 REDIS_URL、DATABASE_URL（及可选 DASHSCOPE_API_KEY）。")
        sys.exit(2)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
