"""
分别测试四个能力接口：content-direction-ranking、case-library、content-positioning-matrix、weekly-decision-snapshot。
验证：(1) 缺参时返回 need_clarification + message；(2) 带齐参数时返回 need_clarification=false + data。
用法：需先启动服务（uvicorn main:app --reload --port 8000），再执行：
  python scripts/test_four_capability_apis.py
  python scripts/test_four_capability_apis.py --quick   # 仅测缺参（澄清）响应，不测带参（避免 LLM 超时）
  BASE_URL=http://127.0.0.1:8000 python scripts/test_four_capability_apis.py
"""
from __future__ import annotations

import os
import sys

# Windows 控制台 UTF-8，便于显示中文
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

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 30


def get(path: str, params: dict | None = None) -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=TIMEOUT)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except requests.exceptions.ConnectionError as e:
        return 0, {"error": f"连接失败: {e}", "hint": "请先启动: uvicorn main:app --reload --port 8000"}
    except Exception as e:
        return 0, {"error": str(e)}


def test_one(
    name: str,
    path: str,
    params_none: dict | None,
    params_ok: dict | None,
    expect_clarification_when_none: bool = True,
    quick: bool = False,
):
    print(f"\n{'='*60}")
    print(f"【{name}】 {path}")
    print("=" * 60)

    # 1) 无参或缺参：应返回 need_clarification
    code1, data1 = get(path, params_none)
    print(f"  请求(缺参): GET {path}  params={params_none}")
    print(f"  状态: {code1}")
    if data1.get("error"):
        print(f"  错误: {data1.get('error')}")
        if data1.get("hint"):
            print(f"  提示: {data1['hint']}")
        return
    need1 = data1.get("need_clarification")
    msg1 = data1.get("message", "")
    print(f"  need_clarification: {need1}")
    if msg1:
        print(f"  message: {msg1[:120]}{'...' if len(msg1) > 120 else ''}")
    if expect_clarification_when_none and need1 is not True:
        print("  [预期缺参时应 need_clarification=true；若为 None 请确认已重启服务并加载最新 capability_api]")

    if quick:
        print("  [--quick] 跳过带参请求")
        return

    # 2) 带齐参数：应返回数据、need_clarification=false
    code2, data2 = get(path, params_ok)
    print(f"\n  请求(带参): GET {path}  params={params_ok}")
    print(f"  状态: {code2}")
    if data2.get("error"):
        print(f"  错误: {data2.get('error')}")
        return
    need2 = data2.get("need_clarification")
    success2 = data2.get("success")
    payload = data2.get("data")
    print(f"  success: {success2}, need_clarification: {need2}")
    if payload is not None:
        if isinstance(payload, dict):
            keys = list(payload.keys())[:8]
            print(f"  data keys: {keys}")
        elif isinstance(payload, list):
            print(f"  data: list len={len(payload)}")
        else:
            print(f"  data: {type(payload).__name__}")
    if success2 and need2 is False and payload is not None:
        print("  [OK] 带参时返回定制数据")
    else:
        print("  [检查] 带参时未返回预期 data 或 need_clarification 仍为 true")


def main():
    quick = "--quick" in sys.argv
    print("四个能力接口测试" + (" [仅测缺参/澄清]" if quick else ""))
    print(f"BASE_URL = {BASE_URL}")
    if quick:
        print("提示: 带参请求会调用插件(可能较慢)，使用 --quick 只测缺参时的澄清响应。")

    # 1. 内容方向榜单：缺参需澄清；带 platform + industry 可出数据
    test_one(
        "内容方向榜单",
        "/api/v1/capabilities/content-direction-ranking",
        params_none=None,
        params_ok={"platform": "xiaohongshu", "industry": "美妆"},
        expect_clarification_when_none=True,
        quick=quick,
    )

    # 2. 案例库：缺行业/目标需澄清；带 industry 可出数据
    test_one(
        "案例库",
        "/api/v1/capabilities/case-library",
        params_none=None,
        params_ok={"industry": "教育", "page": 1, "page_size": 5},
        expect_clarification_when_none=True,
        quick=quick,
    )

    # 3. 内容定位矩阵：缺品牌/行业需澄清；带 industry 可出数据
    test_one(
        "内容定位矩阵",
        "/api/v1/capabilities/content-positioning-matrix",
        params_none=None,
        params_ok={"industry": "教育", "brand_name": "测试品牌"},
        expect_clarification_when_none=True,
        quick=quick,
    )

    # 4. 每周决策快照：缺 user_id 或品牌/行业需澄清；带 user_id 或 brand+industry 可出数据
    test_one(
        "每周决策快照",
        "/api/v1/capabilities/weekly-decision-snapshot",
        params_none=None,
        params_ok={"user_id": "test_user"},
        expect_clarification_when_none=True,
        quick=quick,
    )

    print("\n" + "=" * 60)
    print("测试完成。请对照上述 need_clarification 与 data 是否符合预期。")
    print("若缺参时 need_clarification 为 None，请重启服务以加载最新 capability_api。")
    print("=" * 60)


if __name__ == "__main__":
    main()
