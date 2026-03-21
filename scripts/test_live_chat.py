#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对已启动的服务做实际聊天测试。默认 BASE_URL=http://127.0.0.1:8000"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
CHAT_URL = f"{BASE_URL}/api/v1/frontend/chat"
INIT_URL = f"{BASE_URL}/api/v1/frontend/session/init"
TIMEOUT = 120


def main():
    try:
        import requests
    except ImportError:
        print("请安装 requests: pip install requests")
        return 1

    print("=" * 60)
    print("实际服务测试（需先启动: uvicorn main:app --port 8000）")
    print("=" * 60)
    print(f"BASE_URL: {BASE_URL}\n")

    # 1. 初始化会话
    try:
        r = requests.get(INIT_URL, timeout=15)
        r.raise_for_status()
        data = r.json()
        user_id = data.get("user_id") or "test_user"
        session_id = data.get("session_id") or ""
        print(f"[会话] user_id={user_id}, session_id={session_id[:16] if session_id else 'N/A'}...")
    except Exception as e:
        print(f"[FAIL] 会话初始化失败: {e}")
        return 1

    cases = [
        "你好",
        "帮我生成一篇小红书文案，品牌测试，话题新品推广",
        "我的账号最近流量不好",
        "想提升账号流量有什么办法",
    ]
    for msg in cases:
        print(f"\n--- 输入: {msg[:50]}{'...' if len(msg) > 50 else ''} ---")
        try:
            payload = {"user_id": user_id, "message": msg}
            if session_id:
                payload["session_id"] = session_id
            t0 = time.perf_counter()
            r = requests.post(CHAT_URL, json=payload, timeout=TIMEOUT)
            elapsed = time.perf_counter() - t0
            print(f"  状态: {r.status_code}, 耗时: {elapsed:.1f}s")
            if r.status_code == 440:
                print("  会话过期，请重新初始化")
                break
            data = r.json()
            if data.get("success"):
                # 接口返回: response=正文字符串, thinking_process=列表
                content = data.get("response") or data.get("data") or ""
                content = content if isinstance(content, str) else ""
                thinking = data.get("thinking_process") or []
                print(f"  思考步骤: {len(thinking)}")
                preview = (content or "").strip()[:200]
                try:
                    print(f"  回复预览: {preview}{'...' if len((content or '').strip()) > 200 else ''}")
                except UnicodeEncodeError:
                    print(f"  回复预览: (长度 %d 字符，含特殊字符)" % len((content or "").strip()))
            else:
                print(f"  错误: {data.get('error', data)}")
        except requests.exceptions.Timeout:
            print("  请求超时")
        except Exception as e:
            print(f"  请求失败: {e}")
    print("\n" + "=" * 60)
    print("测试结束")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
