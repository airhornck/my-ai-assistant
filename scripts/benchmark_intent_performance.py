"""
意图识别性能基准测试
对比规则预过滤启用/禁用时的响应延迟。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# 确保项目根目录在 path 中
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.intent.marketing_intent_classifier import MarketingIntentClassifier
from core.intent.processor import InputProcessor


def _mock_ai_with_delay(delay_ms: int = 800):
    """模拟 LLM 调用延迟（典型 500~1500ms）"""
    async def fake_invoke(messages):
        await asyncio.sleep(delay_ms / 1000.0)
        return MagicMock(content='```json\n{"intent":"casual_chat","brand_name":"","product_desc":"","topic":"","command":"","explicit_content_request":false}\n```')

    client = MagicMock()
    client.ainvoke = AsyncMock(side_effect=fake_invoke)
    router = MagicMock()
    # router.route 需 await，返回 client
    router.route = AsyncMock(return_value=client)
    ai = MagicMock()
    ai.router = router
    return ai


async def run_benchmark():
    print("=" * 60)
    print("意图识别性能基准测试")
    print("=" * 60)

    # 1. 纯规则分类器延迟（无 I/O）
    classifier = MarketingIntentClassifier()
    samples = [
        "你好",
        "今天天气不错",
        "谢谢",
        "再见",
        "怎么推广我的小红书账号？",
    ]
    n = 100
    t0 = time.perf_counter()
    for _ in range(n):
        for s in samples:
            classifier.classify(s)
    elapsed = (time.perf_counter() - t0) * 1000
    per_call = elapsed / (n * len(samples))
    print(f"\n1. 规则分类器 classify()（纯 CPU，无 LLM）")
    print(f"   {n} 轮 x {len(samples)} 样本，总耗时: {elapsed:.1f} ms")
    print(f"   单次约: {per_call:.2f} ms")

    # 2. InputProcessor：规则预过滤 开启 vs 关闭（闲聊类输入会跳过/调用 LLM）
    casual_inputs = ["今天天气不错", "谢谢", "再见"]  # 会命中规则闲聊路径

    # 2a. 规则预过滤 开启：闲聊应跳过 LLM
    proc_on = InputProcessor(ai_service=_mock_ai_with_delay(800), use_rule_based_intent_filter=True)
    times_on = []
    for inp in casual_inputs:
        t0 = time.perf_counter()
        await proc_on.process(raw_input=inp, session_id="bench")
        times_on.append((time.perf_counter() - t0) * 1000)

    # 2b. 规则预过滤 关闭：闲聊会调用 LLM（模拟 800ms 延迟）
    proc_off = InputProcessor(ai_service=_mock_ai_with_delay(800), use_rule_based_intent_filter=False)
    times_off = []
    for inp in casual_inputs:
        t0 = time.perf_counter()
        await proc_off.process(raw_input=inp, session_id="bench")
        times_off.append((time.perf_counter() - t0) * 1000)

    print(f"\n2. InputProcessor.process() 闲聊类输入（会命中规则闲聊路径）")
    print(f"   规则预过滤 开启（跳过 LLM）:")
    for inp, t in zip(casual_inputs, times_on):
        print(f"     '{inp}': {t:.0f} ms")
    print(f"   规则预过滤 关闭（调用 LLM，模拟 800ms 延迟）:")
    for inp, t in zip(casual_inputs, times_off):
        print(f"     '{inp}': {t:.0f} ms")

    avg_on = sum(times_on) / len(times_on)
    avg_off = sum(times_off) / len(times_off)
    speedup = avg_off / avg_on if avg_on > 0 else 0
    print(f"\n   -> 平均: 开启 {avg_on:.0f} ms vs 关闭 {avg_off:.0f} ms")
    print(f"   -> 闲聊场景下，规则预过滤约节省 {avg_off - avg_on:.0f} ms，加速约 {speedup:.1f}x")

    # 3. 营销类输入：两种模式都会调用 LLM，耗时相近
    marketing_input = "帮我写一个抖音营销方案"
    t0 = time.perf_counter()
    r1 = await proc_on.process(raw_input=marketing_input, session_id="bench")
    t_on = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    r2 = await proc_off.process(raw_input=marketing_input, session_id="bench")
    t_off = (time.perf_counter() - t0) * 1000

    print(f"\n3. 营销类输入（两种模式均调用 LLM）")
    print(f"   '{marketing_input}'")
    print(f"   开启: {t_on:.0f} ms, 关闭: {t_off:.0f} ms（预期相近）")

    print("\n" + "=" * 60)
    print("结论：规则预过滤对【闲聊类】输入显著减少延迟（跳过 LLM）；")
    print("      对【营销类】输入无额外开销，仍走 LLM 做细粒度分类。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
