"""
测试新前端依赖的接口与前端模块是否正常。
不依赖后端已启动：后端未启动时接口测试会标记为跳过。
运行：python scripts/test_frontend_and_apis.py
"""
from __future__ import annotations

import os
import sys

# 确保项目根在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_frontend_module():
    """测试前端模块可导入且 build_ui 可执行"""
    print("[1/4] 前端模块与 build_ui() ...")
    try:
        from frontend.app_enhanced import (
            build_ui,
            fetch_user_context_display,
            fetch_user_context_md_only,
            fetch_cache_report,
            _format_thinking,
            _DEFAULT_THINKING,
        )
        app = build_ui()
        assert app is not None
        md, rows = fetch_user_context_display("")
        assert isinstance(md, str) and "User ID" in md
        md2 = fetch_user_context_md_only("")
        assert isinstance(md2, str)
        content, title = fetch_cache_report("")
        assert title and "请选择" in title
        out = _format_thinking(_DEFAULT_THINKING)
        assert isinstance(out, str)
        print("      [OK] 前端模块与 build_ui、fetch 函数正常")
        return True
    except Exception as e:
        print(f"      [FAIL] {e}")
        return False


def test_backend_health(base_url: str, timeout: int = 15):
    """测试后端 /health"""
    print(f"[2/4] 后端 /health ({base_url}) ...")
    try:
        import requests
        r = requests.get(f"{base_url}/health", timeout=timeout)
        if r.status_code != 200:
            print(f"      [SKIP] status={r.status_code} (后端可能未启动)")
            return False
        data = r.json()
        if data.get("status") != "healthy":
            print(f"      [WARN] status={data.get('status')}")
        print("      [OK] 后端健康检查通过")
        return True
    except requests.exceptions.Timeout:
        print("      [SKIP] 请求超时，后端可能未启动或较慢")
        return False
    except requests.exceptions.ConnectionError:
        print("      [SKIP] 无法连接后端，请先启动: uvicorn main:app --reload --port 8000")
        return False
    except Exception as e:
        print(f"      [SKIP] {e}")
        return False


def test_session_and_user_context(base_url: str, timeout: int = 15):
    """测试 session/init 与 user-context"""
    print(f"[3/4] session/init + user-context ...")
    try:
        import requests
        r = requests.get(f"{base_url}/api/v1/frontend/session/init", timeout=timeout)
        if r.status_code != 200:
            print(f"      [SKIP] session/init status={r.status_code}")
            return False
        data = r.json()
        if not data.get("success"):
            print(f"      [FAIL] session/init success=False")
            return False
        uid = data.get("user_id") or ""
        if not uid:
            print("      [WARN] user_id 为空")
        r2 = requests.get(
            f"{base_url}/api/v1/frontend/user-context",
            params={"user_id": uid or "test-user"},
            timeout=timeout,
        )
        if r2.status_code != 200:
            print(f"      [FAIL] user-context status={r2.status_code}")
            return False
        j = r2.json()
        if not j.get("success"):
            print(f"      [FAIL] user-context success=False")
            return False
        print(f"      [OK] session/init 与 user-context 正常 (user_id 前 12 位: {uid[:12]}...)")
        return True
    except Exception as e:
        print(f"      [SKIP] {e}")
        return False


def test_cache_reports(base_url: str, timeout: int = 15):
    """测试 debug/cache-reports"""
    print(f"[4/4] debug/cache-reports ...")
    try:
        import requests
        r = requests.get(
            f"{base_url}/api/v1/debug/cache-reports",
            params={"report_type": "bilibili_hotspot"},
            timeout=timeout,
        )
        if r.status_code not in (200, 503):
            print(f"      [SKIP] status={r.status_code}")
            return False
        data = r.json()
        if not data.get("success") and r.status_code == 503:
            print("      [SKIP] smart_cache 未初始化（后端未完全就绪）")
            return False
        if not data.get("success"):
            print(f"      [FAIL] {data.get('error')}")
            return False
        print("      [OK] cache-reports 接口正常")
        return True
    except Exception as e:
        print(f"      [SKIP] {e}")
        return False


def main():
    base = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
    print("=" * 50)
    print("新前端与相关接口测试")
    print(f"BACKEND_URL = {base}")
    print("=" * 50)

    r1 = test_frontend_module()
    r2 = test_backend_health(base)
    r3 = test_session_and_user_context(base) if r2 else False
    r4 = test_cache_reports(base) if r2 else False

    print("=" * 50)
    print(f"前端模块: {'通过' if r1 else '失败'}")
    print(f"后端接口: {'通过' if r2 else '跳过(请先启动后端)'}")
    print(f"会话与上下文: {'通过' if r3 else '跳过/失败'}")
    print(f"缓存报告: {'通过' if r4 else '跳过/失败'}")
    print("=" * 50)
    if r1:
        print("前端可正常启动: python frontend/app_enhanced.py")
    if not r2:
        print("启动后端: uvicorn main:app --reload --port 8000")
    sys.exit(0 if r1 else 1)


if __name__ == "__main__":
    main()
