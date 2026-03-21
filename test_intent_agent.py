"""测试 IntentAgent 意图识别模块"""
import asyncio
import sys
sys.path.insert(0, ".")

from services.ai_service import SimpleAIService
from core.intent.intent_agent import IntentAgent


async def test_intent_agent():
    """测试意图识别Agent"""
    ai_service = SimpleAIService()
    # 与 meta_workflow 一致，使用 _llm（IntentAgent 需 invoke 返回内容）
    llm = getattr(ai_service, "_llm", None) or ai_service.router.powerful_model
    agent = IntentAgent(llm)

    test_cases = [
        ("帮我生成小红书文案", "明确生成内容"),
        ("我的账号最近流量不好", "账号诊断"),
        ("今天天气不错", "闲聊"),
        ("想提升账号流量，有什么办法", "咨询问题"),
        ("帮我制定一个推广策略", "策略规划"),
        ("谢谢", "简短闲聊"),
        ("帮我写一个B站视频脚本", "生成脚本"),
        ("我是卖女装的", "产品介绍"),
    ]

    print("=" * 60)
    print("IntentAgent 测试")
    print("=" * 60)

    for user_input, desc in test_cases:
        result = await agent.classify_intent(user_input)
        print(f"\n[{desc}] 输入: {user_input}")
        print(f"  → intent: {result['intent']}")
        print(f"  → confidence: {result['confidence']}")
        print(f"  → notes: {result['notes'][:50] if result['notes'] else 'N/A'}...")
        print(f"  → need_clarification: {result['need_clarification']}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_intent_agent())
