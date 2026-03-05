#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
四能力接口全面测试：请求四个 GET 接口并输出访问产出的内容摘要，便于查看返回质量。
使用：先启动服务 (uvicorn main:app --reload)，再运行：
  python scripts/run_capability_apis_content.py
  BASE_URL=http://127.0.0.1:8000 python scripts/run_capability_apis_content.py
  SKIP_SLOW=1  # 跳过需 LLM 的接口（内容方向榜单、每周决策快照）
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Tuple

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
TIMEOUT_SLOW = 120
TIMEOUT_FAST = 30
# 控制输出长度
MAX_ITEM_PREVIEW = 400
MAX_CELL_PREVIEW = 200


def get(path: str, params: Dict[str, Any] | None = None, timeout: int = TIMEOUT_FAST) -> Tuple[int, Dict[str, Any]]:
    url = f"{CAPABILITY_PREFIX}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {"_raw": (r.text or "")[:1000]}
        return r.status_code, body
    except requests.exceptions.ConnectionError as e:
        return 0, {"error": f"连接失败（请确认服务已启动）: {e}"}
    except Exception as e:
        return 0, {"error": str(e)}


def _preview(obj: Any, max_len: int = 300) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=0)
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s


def test_content_direction_ranking() -> None:
    print("\n" + "=" * 60)
    print("1. GET /api/v1/capabilities/content-direction-ranking（内容方向榜单）")
    print("=" * 60)
    if SKIP_SLOW:
        print("已跳过 (SKIP_SLOW=1)")
        return
    code, body = get("/content-direction-ranking", params={"platform": "xiaohongshu"}, timeout=TIMEOUT_SLOW)
    print(f"HTTP {code}")
    if code != 200:
        print("响应:", _preview(body, 500))
        return
    print("success:", body.get("success"))
    print("source:", body.get("source"))
    data = body.get("data") or {}
    items = data.get("items") or []
    print(f"items 数量: {len(items)}")
    if items:
        for i, it in enumerate(items[:3]):
            if isinstance(it, dict):
                print(f"  [{i+1}] title_suggestion: {str(it.get('title_suggestion') or it.get('title') or '')[:80]}")
                print(f"      adaptation_score: {it.get('adaptation_score')}, risk_level: {it.get('risk_level')}")
                print(f"      angles: {_preview(it.get('angles') or [], 120)}")
            else:
                print(f"  [{i+1}] {_preview(it, MAX_ITEM_PREVIEW)}")
    else:
        print("  （无 items 或为空）")
    print()


def test_case_library() -> None:
    print("\n" + "=" * 60)
    print("2. GET /api/v1/capabilities/case-library（定位决策案例库）")
    print("=" * 60)
    code, body = get("/case-library", params={"page": 1, "page_size": 5})
    print(f"HTTP {code}")
    if code != 200:
        print("响应:", _preview(body, 500))
        return
    print("success:", body.get("success"))
    data = body.get("data") or {}
    items = data.get("items", data.get("list", []))
    if not isinstance(items, list):
        items = []
    print(f"案例数量: {len(items)}")
    if items:
        for i, c in enumerate(items[:3]):
            if isinstance(c, dict):
                print(f"  [{i+1}] title: {(c.get('title') or '')[:60]}")
                print(f"      industry: {c.get('industry')}, goal_type: {c.get('goal_type')}")
            else:
                print(f"  [{i+1}] {_preview(c, MAX_ITEM_PREVIEW)}")
    else:
        print("  （无案例数据）")
    print()


def test_content_positioning_matrix() -> None:
    print("\n" + "=" * 60)
    print("3. GET /api/v1/capabilities/content-positioning-matrix（内容定位矩阵）")
    print("=" * 60)
    code, body = get("/content-positioning-matrix", params={"industry": "教育"}, timeout=TIMEOUT_FAST)
    print(f"HTTP {code}")
    if code != 200:
        print("响应:", _preview(body, 500))
        return
    print("success:", body.get("success"))
    print("source:", body.get("source"))
    data = body.get("data") or {}
    matrix = data.get("matrix") or []
    persona = data.get("persona") or {}
    print(f"matrix 格子数: {len(matrix)}")
    print("persona 摘要:", _preview(persona, 200))
    if matrix:
        for i, cell in enumerate(matrix[:4]):
            if isinstance(cell, dict):
                print(f"  格[{i}] priority={cell.get('priority')}, stage={cell.get('stage')}")
                print(f"       boundary: {(str(cell.get('boundary') or ''))[:60]}")
                print(f"       suggestion: {(str(cell.get('suggestion') or ''))[:80]}")
            else:
                print(f"  格[{i}] {_preview(cell, MAX_CELL_PREVIEW)}")
    else:
        print("  （无 matrix）")
    print()


def test_weekly_decision_snapshot() -> None:
    print("\n" + "=" * 60)
    print("4. GET /api/v1/capabilities/weekly-decision-snapshot（每周决策快照）")
    print("=" * 60)
    if SKIP_SLOW:
        print("已跳过 (SKIP_SLOW=1)")
        return
    code, body = get("/weekly-decision-snapshot", params={"user_id": "test_content_user"}, timeout=TIMEOUT_SLOW)
    print(f"HTTP {code}")
    if code != 200:
        print("响应:", _preview(body, 500))
        return
    print("success:", body.get("success"))
    print("source:", body.get("source"))
    data = body.get("data") or {}
    print("stage:", data.get("stage"))
    print("max_risk:", data.get("max_risk"))
    priorities = data.get("priorities") or []
    print(f"priorities 条数: {len(priorities)}")
    for i, p in enumerate(priorities[:5]):
        print(f"  [{i+1}] {_preview(p, 150)}")
    forbidden = data.get("forbidden") or []
    print(f"forbidden 条数: {len(forbidden)}")
    for i, f in enumerate(forbidden[:3]):
        print(f"  [{i+1}] {_preview(f, 150)}")
    print("weekly_focus:", (data.get("weekly_focus") or "")[:200])
    history = data.get("history") or []
    print(f"history 条数: {len(history)}")
    print()


def main() -> int:
    print(f"BASE_URL = {BASE_URL}")
    if SKIP_SLOW:
        print("SKIP_SLOW=1，将跳过内容方向榜单与每周决策快照")
    test_content_direction_ranking()
    test_case_library()
    test_content_positioning_matrix()
    test_weekly_decision_snapshot()
    print("=" * 60)
    print("四能力接口内容测试完成")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
