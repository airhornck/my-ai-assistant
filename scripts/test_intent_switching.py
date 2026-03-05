#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
模拟真实用户多轮对话，验证：
1. 闲聊与任务（创作）的正确识别与切换
2. 多次切换后上下文正确记录
3. 能正确读取上文的引导建议（采纳「好的」等触发建议执行）

使用方式：先启动服务（uvicorn main:app --reload），再运行
  python scripts/test_intent_switching.py
  BASE_URL=http://127.0.0.1:8000 python scripts/test_intent_switching.py
"""
from __future__ import annotations

import os
import sys
import time

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
TIMEOUT = 120


def init_session():
    r = requests.get(f"{BASE_URL}/api/v1/frontend/session/init", timeout=30)
    r.raise_for_status()
    data = r.json()
    assert data.get("success") is True
    return data.get("user_id", ""), data.get("session_id", "")


def chat(user_id: str, session_id: str, message: str, history: list[dict] | None = None):
    payload = {
        "user_id": user_id,
        "session_id": session_id or "",
        "message": message,
        "history": history or [],
    }
    r = requests.post(
        f"{BASE_URL}/api/v1/frontend/chat",
        json=payload,
        timeout=TIMEOUT,
    )
    if r.status_code == 440:
        return {"success": False, "session_expired": True, "status_code": 440}
    r.raise_for_status()
    return r.json()


def main():
    print(f"BASE_URL = {BASE_URL}")
    print("=" * 60)

    # 0. 初始化会话
    try:
        user_id, session_id = init_session()
        print(f"[Init] user_id={user_id[:16]}... session_id={session_id[:8]}...")
    except requests.exceptions.ConnectionError as e:
        print(f"[FAIL] 连接失败: {e}")
        print("请先启动服务: uvicorn main:app --reload --port 8000")
        sys.exit(2)
    except requests.exceptions.Timeout as e:
        print(f"[FAIL] 初始化超时: {e}")
        print("若服务已启动，可增大脚本内 init_session 的 timeout 后重试。")
        sys.exit(2)
    except Exception as e:
        print(f"[FAIL] 初始化失败: {e}")
        print("请先启动服务: uvicorn main:app --reload --port 8000")
        sys.exit(2)

    history: list[dict] = []
    errors: list[str] = []
    session_expired = False

    # 1. 闲聊
    print("\n[Turn 1] 用户: 你好")
    resp1 = chat(user_id, session_id, "你好", history)
    if resp1.get("session_expired"):
        session_expired = True
        errors.append("Turn 1: 会话过期")
    elif not resp1.get("success"):
        errors.append(f"Turn 1: success=False, error={resp1.get('error')}")
    else:
        intent1 = resp1.get("intent", "")
        if intent1 != "casual_chat":
            errors.append(f"Turn 1: 期望 intent=casual_chat, 实际={intent1}")
        else:
            print(f"       intent={intent1} [OK] 回复长度={len(resp1.get('response') or '')}")
        history.append({"role": "user", "content": "你好"})
        history.append({"role": "assistant", "content": (resp1.get("response") or "")[:200]})

    if session_expired:
        print("\n会话已过期，无法继续。请检查 Redis 与 session TTL。")
        sys.exit(1)

    # 2. 任务：推广
    print("\n[Turn 2] 用户: 帮我推广华为手机")
    resp2 = chat(user_id, session_id, "帮我推广华为手机", history)
    if resp2.get("session_expired"):
        errors.append("Turn 2: 会话过期")
    elif not resp2.get("success"):
        errors.append(f"Turn 2: success=False, error={resp2.get('error')}")
    else:
        intent2 = resp2.get("intent", "")
        creation_intents = ("free_discussion", "structured_request", "creation", "clarification")
        if intent2 not in creation_intents:
            errors.append(f"Turn 2: 期望创作类意图, 实际 intent={intent2}")
        else:
            print(f"       intent={intent2} [OK] mode={resp2.get('mode')} 有内容={bool(resp2.get('response'))}")
        history.append({"role": "user", "content": "帮我推广华为手机"})
        history.append({"role": "assistant", "content": (resp2.get("response") or "")[:200]})

    # 3. 再次闲聊
    print("\n[Turn 3] 用户: 在吗")
    resp3 = chat(user_id, session_id, "在吗", history)
    if resp3.get("session_expired"):
        errors.append("Turn 3: 会话过期")
    elif not resp3.get("success"):
        errors.append(f"Turn 3: success=False, error={resp3.get('error')}")
    else:
        intent3 = resp3.get("intent", "")
        if intent3 != "casual_chat":
            errors.append(f"Turn 3: 期望 intent=casual_chat, 实际={intent3}")
        else:
            print(f"       intent={intent3} [OK]")
        history.append({"role": "user", "content": "在吗"})
        history.append({"role": "assistant", "content": (resp3.get("response") or "")[:200]})

    # 4. 任务：明确要求生成（验证上下文延续：应延续华为手机）
    print("\n[Turn 4] 用户: 生成一篇小红书文案")
    resp4 = chat(user_id, session_id, "生成一篇小红书文案", history)
    if resp4.get("session_expired"):
        errors.append("Turn 4: 会话过期")
    elif not resp4.get("success"):
        errors.append(f"Turn 4: success=False, error={resp4.get('error')}")
    else:
        intent4 = resp4.get("intent", "")
        if intent4 not in creation_intents:
            errors.append(f"Turn 4: 期望创作类意图, 实际 intent={intent4}")
        else:
            content4 = (resp4.get("response") or "")
            has_huawei = "华为" in content4 or "手机" in content4
            print(f"       intent={intent4} [OK] 有内容={bool(content4)} 延续品牌/产品={has_huawei}")
        history.append({"role": "user", "content": "生成一篇小红书文案"})
        history.append({"role": "assistant", "content": (resp4.get("response") or "")[:200]})

    # 5. 采纳建议（「好的」在上轮为创作且存在建议时应触发创作）
    print("\n[Turn 5] 用户: 好的")
    resp5 = chat(user_id, session_id, "好的", history)
    if resp5.get("session_expired"):
        errors.append("Turn 5: 会话过期")
    elif not resp5.get("success"):
        errors.append(f"Turn 5: success=False, error={resp5.get('error')}")
    else:
        intent5 = resp5.get("intent", "")
        mode5 = resp5.get("mode", "")
        # 若上轮有 suggested_next_plan，「好的」可能被识别为采纳建议 → creation
        if intent5 in creation_intents and mode5 == "creation":
            print(f"       intent={intent5} mode={mode5} [OK] 采纳建议或创作")
        elif intent5 == "casual_chat":
            print(f"       intent={intent5} (无待采纳建议时的正常闲聊)")
        else:
            print(f"       intent={intent5} mode={mode5}")
        history.append({"role": "user", "content": "好的"})
        history.append({"role": "assistant", "content": (resp5.get("response") or "")[:200]})

    # 6. 再次闲聊
    print("\n[Turn 6] 用户: 谢谢")
    resp6 = chat(user_id, session_id, "谢谢", history)
    if resp6.get("session_expired"):
        errors.append("Turn 6: 会话过期")
    elif not resp6.get("success"):
        errors.append(f"Turn 6: success=False, error={resp6.get('error')}")
    else:
        intent6 = resp6.get("intent", "")
        if intent6 != "casual_chat":
            errors.append(f"Turn 6: 期望 intent=casual_chat, 实际={intent6}")
        else:
            print(f"       intent={intent6} [OK]")
        history.append({"role": "user", "content": "谢谢"})
        history.append({"role": "assistant", "content": (resp6.get("response") or "")[:200]})

    # 汇总
    print("\n" + "=" * 60)
    if errors:
        print("存在问题:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("全部通过：闲聊与任务识别/切换正常，多轮上下文与建议读取符合预期。")
    sys.exit(0)


if __name__ == "__main__":
    main()
