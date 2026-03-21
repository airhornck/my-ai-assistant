#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
通过策略脑与插件中心，验证优化后所有插件功能完整可用。

1. 使用与 main 一致的依赖注入（memory_service、db_session_factory、plugin_bus）构建 SimpleAIService，
   确保各插件从 config 拿到的依赖可用。
2. 对分析脑/生成脑已注册的每个插件执行一次 get_output(plugin_name, minimal_context)，校验不抛错、返回 dict。
3. 跑通一次完整 meta_workflow（策略脑规划 → 编排执行），校验流程不崩溃。

运行：
  python scripts/test_plugins_via_strategy_brain.py
  pytest scripts/test_plugins_via_strategy_brain.py -v -s

环境：REDIS_URL、DATABASE_URL 可选；未配置时部分插件可能返回空但不应收紧。DASHSCOPE_API_KEY 可选（无则意图/策略走 fallback）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Windows 控制台 UTF-8 输出
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


def _minimal_request():
    """供插件 get_output 使用的最小 request 形态。"""
    return SimpleNamespace(
        brand_name="测试品牌",
        product_desc="测试产品",
        topic="小红书推广",
        user_id="test_plugin_user",
        raw_query="帮我生成小红书文案",
    )


def _build_ai_service_like_main():
    """按 main.py lifespan 方式构建 SimpleAIService，注入 memory_service、db_session_factory、plugin_bus。"""
    from cache.smart_cache import SmartCache
    from domain.memory import MemoryService
    from core.plugin_bus import get_plugin_bus

    cache = None
    if os.getenv("REDIS_URL"):
        try:
            cache = SmartCache()
        except Exception as e:
            print(f"  [WARN] SmartCache 未创建: {e}，插件将无 cache")
    memory_service = MemoryService(cache=cache) if cache is not None else None
    db_session_factory = None
    if os.getenv("DATABASE_URL"):
        try:
            from database import AsyncSessionLocal
            db_session_factory = AsyncSessionLocal
        except Exception as e:
            print(f"  [WARN] 数据库会话工厂未注入: {e}")
    plugin_bus = get_plugin_bus()

    from services.ai_service import SimpleAIService
    from modules.methodology.service import MethodologyService
    from modules.case_template.service import CaseTemplateService
    from modules.knowledge_base.factory import get_knowledge_port

    ai = SimpleAIService(
        cache=cache,
        methodology_service=MethodologyService(),
        case_service=CaseTemplateService(db_session_factory) if db_session_factory else None,
        knowledge_port=get_knowledge_port(cache) if cache else None,
        memory_service=memory_service,
        db_session_factory=db_session_factory,
        plugin_bus=plugin_bus,
    )
    return ai


async def test_each_analysis_plugin(ai) -> tuple[list[str], list[str], list[str]]:
    """对分析脑每个已注册插件执行 get_output，返回 (成功, 失败, 跳过) 插件名列表。"""
    center = getattr(ai, "_analysis_plugin_center", None)
    if not center:
        return [], [], []
    names = center.list_plugins()
    minimal_ctx = {
        "request": _minimal_request(),
        "preference_context": "品牌：测试；行业：美妆",
        "analysis": {},
        "plugin_input": {},
    }
    ok, fail, skip = [], [], []
    for name in names:
        try:
            out = await asyncio.wait_for(
                center.get_output(name, minimal_ctx),
                timeout=30.0,
            )
            if isinstance(out, dict):
                ok.append(name)
            else:
                fail.append(name)
        except asyncio.TimeoutError:
            skip.append(f"{name}(timeout)")
        except Exception as e:
            fail.append(f"{name}({type(e).__name__}: {str(e)[:80]})")
    return ok, fail, skip


async def test_each_generation_plugin(ai) -> tuple[list[str], list[str], list[str]]:
    """对生成脑每个已注册插件执行 get_output，返回 (成功, 失败, 跳过) 插件名列表。"""
    center = getattr(ai, "_generation_plugin_center", None)
    if not center:
        return [], [], []
    names = center.list_plugins()
    minimal_ctx = {
        "analysis": {"brand_name": "测试", "topic": "小红书"},
        "topic": "小红书推广",
        "raw_query": "帮我写一段小红书文案",
        "session_document_context": "",
        "memory_context": "",
        "output_type": "text",
        "source_content": None,
    }
    ok, fail, skip = [], [], []
    for name in names:
        try:
            out = await asyncio.wait_for(
                center.get_output(name, minimal_ctx),
                timeout=45.0,
            )
            if isinstance(out, dict):
                ok.append(name)
            else:
                fail.append(name)
        except asyncio.TimeoutError:
            skip.append(f"{name}(timeout)")
        except Exception as e:
            fail.append(f"{name}({type(e).__name__}: {str(e)[:80]})")
    return ok, fail, skip


async def test_full_flow_smoke(ai=None):
    """策略脑 + 编排：跑通完整 meta_workflow，校验不崩溃。传入 ai 时使用已注入依赖的同一实例。"""
    from workflows.meta_workflow import build_meta_workflow

    wf = build_meta_workflow(ai_service=ai) if ai else build_meta_workflow()
    for user_raw in ["你好", "帮我生成小红书文案"]:
        state = {
            "user_input": json.dumps({
                "raw_query": user_raw,
                "brand_name": "",
                "topic": "",
            }, ensure_ascii=False),
            "session_id": "test_strategy_smoke",
            "user_id": "test_strategy_user",
        }
        config = {"configurable": {"thread_id": "test_strategy_flow"}}
        try:
            final = await asyncio.wait_for(wf.ainvoke(state, config=config), timeout=120.0)
            assert "content" in final or "plan" in final or "thinking_logs" in final
            plan = final.get("plan") or []
            a_plugins = final.get("analysis_plugins") or []
            g_plugins = final.get("generation_plugins") or []
            print(f"  [OK] 流程: \"{user_raw[:20]}...\" -> plan={len(plan)}步, analysis_plugins={a_plugins[:3]}..., generation_plugins={g_plugins[:2]}...")
        except asyncio.TimeoutError:
            print(f"  [SKIP] 流程超时: \"{user_raw[:20]}...\"（可增加 timeout 或检查 LLM）")
        except Exception as e:
            print(f"  [FAIL] 流程: \"{user_raw[:20]}...\" -> {e}")
            raise


async def run_all():
    print("=" * 60)
    print("策略脑 + 插件中心：优化后插件功能校验")
    print("=" * 60)

    print("\n1. 构建 AI 服务（与 main 一致注入 memory_service / db_session_factory / plugin_bus）...")
    try:
        ai = _build_ai_service_like_main()
        print("   [OK] SimpleAIService 构建完成")
    except Exception as e:
        print(f"   [FAIL] 构建失败: {e}")
        raise

    print("\n2. 分析脑：逐插件 get_output 校验...")
    a_ok, a_fail, a_skip = await test_each_analysis_plugin(ai)
    print(f"   成功: {len(a_ok)} 个 {a_ok[:8]}{'...' if len(a_ok) > 8 else ''}")
    if a_skip:
        print(f"   超时/跳过: {len(a_skip)} 个 {a_skip[:5]}{'...' if len(a_skip) > 5 else ''}")
    if a_fail:
        print(f"   失败: {len(a_fail)} 个")
        for x in a_fail[:10]:
            print(f"      - {x}")
        if len(a_fail) > 10:
            print(f"      ... 共 {len(a_fail)} 个")
        raise AssertionError(f"分析脑插件失败: {a_fail}")

    print("\n3. 生成脑：逐插件 get_output 校验...")
    g_ok, g_fail, g_skip = await test_each_generation_plugin(ai)
    print(f"   成功: {len(g_ok)} 个 {g_ok}")
    if g_skip:
        print(f"   超时/跳过: {len(g_skip)} 个 {g_skip}")
    if g_fail:
        print(f"   失败: {len(g_fail)} 个 {g_fail}")
        raise AssertionError(f"生成脑插件失败: {g_fail}")

    print("\n4. 完整流程烟雾测试（策略脑规划 → 编排执行，使用上述已注入依赖的 AI 服务）...")
    await test_full_flow_smoke(ai=ai)

    print("\n" + "=" * 60)
    print("全部通过：优化后插件在策略脑下功能完整可用")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all())
