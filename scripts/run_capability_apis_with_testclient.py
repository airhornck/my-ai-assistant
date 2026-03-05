#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
四能力接口全面测试（TestClient，无需启动 HTTP 服务）：请求四个 GET 并打印产出内容。
需 REDIS_URL、DATABASE_URL；涉及 LLM 的接口需 DASHSCOPE_API_KEY（否则可能 503 或回退）。
使用：python scripts/run_capability_apis_with_testclient.py
  SKIP_SLOW=1  # 跳过内容方向榜单、每周决策快照（不调 LLM）
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

# Windows 控制台 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

SKIP_SLOW = os.getenv("SKIP_SLOW", "").strip().lower() in ("1", "true", "yes")
TIMEOUT_SLOW = 120
TIMEOUT_FAST = 30
MAX_PREVIEW = 350


def _preview(obj: Any, max_len: int = MAX_PREVIEW) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=0)
    return (s[:max_len] + "…") if len(s) > max_len else s


def run() -> None:
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)

    print("=" * 60)
    print("四能力接口全面测试（TestClient，无需启动服务）")
    print("=" * 60)
    if SKIP_SLOW:
        print("SKIP_SLOW=1，将跳过内容方向榜单与每周决策快照")
    print()

    # 1. 内容方向榜单
    print("\n[1] GET /api/v1/capabilities/content-direction-ranking（内容方向榜单）")
    if SKIP_SLOW:
        print("    已跳过")
    else:
        r = client.get("/api/v1/capabilities/content-direction-ranking", params={"platform": "xiaohongshu"}, timeout=TIMEOUT_SLOW)
        print("    HTTP", r.status_code)
        try:
            body = r.json()
        except Exception:
            print("    响应非 JSON:", (r.text or "")[:300])
        else:
            print("    success:", body.get("success"), "source:", body.get("source"))
            data = body.get("data") or {}
            items = data.get("items") or []
            print("    items 数量:", len(items))
            for i, it in enumerate(items[:3]):
                if isinstance(it, dict):
                    print("      [%d] title_suggestion: %s" % (i + 1, (str(it.get("title_suggestion") or it.get("title") or ""))[:70]))
                    print("          adaptation_score: %s, risk_level: %s" % (it.get("adaptation_score"), it.get("risk_level")))
                else:
                    print("      [%d] %s" % (i + 1, _preview(it)))

    # 2. 案例库
    print("\n[2] GET /api/v1/capabilities/case-library（定位决策案例库）")
    r = client.get("/api/v1/capabilities/case-library", params={"page": 1, "page_size": 5}, timeout=TIMEOUT_FAST)
    print("    HTTP", r.status_code)
    try:
        body = r.json()
    except Exception:
        print("    响应非 JSON:", (r.text or "")[:300])
    else:
        print("    success:", body.get("success"))
        data = body.get("data") or {}
        items = data.get("items", data.get("list", []))
        if not isinstance(items, list):
            items = []
        print("    案例数量:", len(items))
        for i, c in enumerate(items[:3]):
            if isinstance(c, dict):
                print("      [%d] title: %s" % (i + 1, (str(c.get("title") or ""))[:60]))
                print("          industry: %s, goal_type: %s" % (c.get("industry"), c.get("goal_type")))
            else:
                print("      [%d] %s" % (i + 1, _preview(c)))

    # 3. 内容定位矩阵
    print("\n[3] GET /api/v1/capabilities/content-positioning-matrix（内容定位矩阵）")
    r = client.get("/api/v1/capabilities/content-positioning-matrix", params={"industry": "教育"}, timeout=TIMEOUT_FAST)
    print("    HTTP", r.status_code)
    try:
        body = r.json()
    except Exception:
        print("    响应非 JSON:", (r.text or "")[:300])
    else:
        print("    success:", body.get("success"), "source:", body.get("source"))
        data = body.get("data") or {}
        matrix = data.get("matrix") or []
        persona = data.get("persona") or {}
        print("    matrix 格子数:", len(matrix))
        print("    persona 摘要:", _preview(persona, 180))
        for i, cell in enumerate(matrix[:4]):
            if isinstance(cell, dict):
                print("      格[%d] priority=%s stage=%s" % (i, cell.get("priority"), cell.get("stage")))
                print("            boundary: %s" % (str(cell.get("boundary") or ""))[:60])
                print("            suggestion: %s" % (str(cell.get("suggestion") or ""))[:70])
            else:
                print("      格[%d] %s" % (i, _preview(cell)))

    # 4. 每周决策快照
    print("\n[4] GET /api/v1/capabilities/weekly-decision-snapshot（每周决策快照）")
    if SKIP_SLOW:
        print("    已跳过")
    else:
        r = client.get("/api/v1/capabilities/weekly-decision-snapshot", params={"user_id": "test_content_user"}, timeout=TIMEOUT_SLOW)
        print("    HTTP", r.status_code)
        try:
            body = r.json()
        except Exception:
            print("    响应非 JSON:", (r.text or "")[:300])
        else:
            print("    success:", body.get("success"), "source:", body.get("source"))
            data = body.get("data") or {}
            print("    stage:", data.get("stage"), "max_risk:", data.get("max_risk"))
            priorities = data.get("priorities") or []
            print("    priorities 条数:", len(priorities))
            for i, p in enumerate(priorities[:4]):
                print("      [%d] %s" % (i + 1, _preview(p, 120)))
            forbidden = data.get("forbidden") or []
            print("    forbidden 条数:", len(forbidden))
            print("    weekly_focus:", (str(data.get("weekly_focus") or ""))[:150])

    print("\n" + "=" * 60)
    print("四能力接口内容测试完成")
    print("=" * 60)


if __name__ == "__main__":
    run()
    sys.exit(0)
