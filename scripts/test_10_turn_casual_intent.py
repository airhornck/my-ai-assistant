#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
10 轮闲聊意图测试（依赖外部模型）：
- 通过 InputProcessor 直接调用意图识别链
- 读取 .env 中 DASHSCOPE_API_KEY（仅用于是否存在校验，不打印值）
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    for _f in (".env", ".env.dev", ".env.prod"):
        _p = ROOT / _f
        if _p.exists():
            load_dotenv(_p)
            break
except Exception:
    pass

from core.intent.processor import InputProcessor


TURNS = ["北京天气如何", "需要", "继续", "然后呢", "好的", "再说说", "行", "还有吗", "嗯", "谢谢"]


def _env_has_dashscope_key() -> bool:
    p = Path(".env")
    if not p.exists():
        return False
    txt = p.read_text(encoding="utf-8", errors="ignore")
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("DASHSCOPE_API_KEY=") and s.split("=", 1)[1].strip():
            return True
    return False


async def main() -> int:
    has_key = _env_has_dashscope_key()
    if not has_key:
        print(json.dumps({"ok": False, "reason": "DASHSCOPE_API_KEY missing in .env"}, ensure_ascii=False))
        return 2

    proc = InputProcessor(use_rule_based_intent_filter=True)
    history: list[str] = []
    rows = []
    wrong_switch_turns: list[int] = []

    # 这里将 structured_request/document_query/command 视为“明显切到创作或任务执行轨”
    creation_like = {"structured_request", "document_query", "command"}

    for i, msg in enumerate(TURNS, 1):
        conv = "\n".join(history[-10:])
        out = await proc.process(
            raw_input=msg,
            session_id="test_10_turn_session",
            user_id="test_10_turn_user",
            conversation_context=conv,
        )
        intent = out.get("intent", "")
        explicit = bool(out.get("explicit_content_request"))
        switched = intent in creation_like or explicit
        if switched:
            wrong_switch_turns.append(i)
        rows.append(
            {
                "turn": i,
                "input": msg,
                "intent": intent,
                "explicit_content_request": explicit,
                "wrong_switch_to_creation_like": switched,
            }
        )
        history.append(f"用户：{msg}")
        history.append(f"系统意图：{intent}")

    print(
        json.dumps(
            {
                "ok": len(wrong_switch_turns) == 0,
                "wrong_switch_turns": wrong_switch_turns,
                "results": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if len(wrong_switch_turns) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
