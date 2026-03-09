#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
模拟 3 个不同行业用户完成「闲聊 → 智能识别需求 → 策略脑规划 → 账号提升」完整流程。
需先启动后端：uvicorn main:app --reload --port 8000
使用：python scripts/run_e2e_three_industries.py
  BASE_URL=http://127.0.0.1:8000 python scripts/run_e2e_three_industries.py
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

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
INIT_URL = f"{BASE_URL}/api/v1/frontend/session/init"
CHAT_URL = f"{BASE_URL}/api/v1/frontend/chat"
TIMEOUT_INIT = 15
TIMEOUT_CHAT = 180  # 策略脑+分析可能较久


def init_session() -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """GET 初始化会话，返回 (user_id, session_id, thread_id, error_msg)。"""
    try:
        r = requests.get(INIT_URL, timeout=TIMEOUT_INIT)
        r.raise_for_status()
        data = r.json()
        return (
            data.get("user_id"),
            data.get("session_id"),
            data.get("thread_id"),
            "",
        )
    except Exception as e:
        return None, None, None, str(e)


def chat(user_id: str, session_id: Optional[str], message: str) -> Tuple[bool, Dict[str, Any], str]:
    """POST 发送一条消息，返回 (success, body, error_msg)。"""
    payload: Dict[str, Any] = {"message": message, "user_id": user_id}
    if session_id:
        payload["session_id"] = session_id
    try:
        r = requests.post(CHAT_URL, json=payload, timeout=TIMEOUT_CHAT)
        if r.status_code == 440:
            return False, r.json() if r.content else {}, "SESSION_EXPIRED"
        r.raise_for_status()
        return True, r.json(), ""
    except requests.exceptions.Timeout:
        return False, {}, "请求超时"
    except requests.exceptions.ConnectionError as e:
        return False, {}, f"连接失败: {e}"
    except Exception as e:
        try:
            body = r.json() if r.content else {}
        except Exception:
            body = {}
        return False, body, str(e)


# 3 个行业用户的对话脚本：(行业名, [(消息, 期望结果描述), ...])
SCENARIOS: List[Tuple[str, List[Tuple[str, str]]]] = [
    (
        "教育",
        [
            ("你好", "闲聊回复"),
            ("我是做教育培训的，想提升一下账号，帮我看看怎么优化", "策略脑规划并给出建议或诊断"),
        ],
    ),
    (
        "美妆",
        [
            ("在吗", "闲聊回复"),
            ("我们做美妆的，想诊断下账号问题", "策略脑规划并给出诊断/建议"),
        ],
    ),
    (
        "科技",
        [
            ("嗨", "闲聊回复"),
            ("科技数码类账号，想提升流量和转化", "策略脑规划并给出方向或建议"),
        ],
    ),
]


def run_one_user(industry: str, messages: List[Tuple[str, str]]) -> Tuple[int, int, List[str]]:
    """跑一个用户的完整对话，返回 (通过轮数, 总轮数, 错误列表)。"""
    errs: List[str] = []
    user_id, session_id, _, init_err = init_session()
    if init_err:
        return 0, len(messages), [f"初始化失败: {init_err}"]
    passed = 0
    for i, (msg, expect_desc) in enumerate(messages):
        ok, body, err = chat(user_id, session_id, msg)
        if err:
            errs.append(f"第{i+1}轮「{msg[:20]}…」请求失败: {err}")
            continue
        if not body.get("success"):
            errs.append(f"第{i+1}轮 success=False: {body.get('error', '')[:80]}")
            continue
        # 会话可能更新
        session_id = body.get("session_id") or session_id
        # 期望：有回复内容（response）或思维过程；澄清时 response 为引导文案
        resp_text = body.get("response") or body.get("data") or ""
        thinking = body.get("thinking_process") or []
        if resp_text and len(str(resp_text).strip()) > 0:
            passed += 1
        elif isinstance(thinking, list) and len(thinking) > 0:
            passed += 1
        else:
            errs.append(f"第{i+1}轮 无 response/thinking")
    return passed, len(messages), errs


def main() -> int:
    print("=" * 60)
    print("E2E：3 行业用户 闲聊→需求识别→策略脑→账号提升")
    print("=" * 60)
    print(f"BASE_URL = {BASE_URL}")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=10)
        if r.status_code != 200:
            print("警告: /health 返回非 200")
    except Exception as e:
        print(f"无法连接后端: {e}")
        print("请先启动：uvicorn main:app --reload --port 8000")
        return 1
    print()

    total_pass = 0
    total_rounds = 0
    all_errors: List[str] = []

    for industry, messages in SCENARIOS:
        print(f"\n--- 行业: {industry} ---")
        p, r, errs = run_one_user(industry, messages)
        total_pass += p
        total_rounds += r
        all_errors.extend([f"[{industry}] {e}" for e in errs])
        if errs:
            for e in errs:
                print(f"  [FAIL] {e}")
        else:
            print(f"  [OK] {p}/{r} 轮通过")
        time.sleep(0.5)

    print("\n" + "=" * 60)
    if all_errors:
        print(f"合计: {total_pass}/{total_rounds} 轮通过，{len(all_errors)} 个问题")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    print(f"合计: {total_pass}/{total_rounds} 轮全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
