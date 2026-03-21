"""测试 PlanningAgent 策略规划模块"""
import asyncio
import sys
sys.path.insert(0, ".")

from services.ai_service import SimpleAIService
from core.intent.planning_agent import PlanningAgent
from core.intent.intent_agent import IntentAgent


async def test_planning_agent():
    """测试策略规划Agent"""
    ai_service = SimpleAIService()
    llm = getattr(ai_service, "_llm", None) or ai_service.router.powerful_model
    planning_agent = PlanningAgent(llm)

    test_cases = [
        {
            "intent_data": {
                "intent": "generate_content",
                "confidence": 0.9,
                "raw_query": "帮我生成小红书文案",
                "notes": "用户明确要求生成小红书文案"
            },
            "user_data": {"brand_name": "华为", "product_desc": "手机", "platform": "小红书"},
            "desc": "生成内容意图"
        },
        {
            "intent_data": {
                "intent": "casual_chat",
                "confidence": 0.95,
                "raw_query": "今天天气不错",
                "notes": "闲聊寒暄"
            },
            "user_data": {},
            "desc": "闲聊意图"
        },
        {
            "intent_data": {
                "intent": "account_diagnosis",
                "confidence": 0.85,
                "raw_query": "我的账号流量不好",
                "notes": "账号诊断"
            },
            "user_data": {"brand_name": "测试账号"},
            "desc": "账号诊断意图"
        },
        {
            "intent_data": {
                "intent": "query_info",
                "confidence": 0.8,
                "raw_query": "如何提升账号流量",
                "notes": "咨询问题"
            },
            "user_data": {},
            "desc": "查询信息意图"
        },
    ]

    print("=" * 60)
    print("PlanningAgent 测试")
    print("=" * 60)

    for case in test_cases:
        result = await planning_agent.plan_steps(
            case["intent_data"],
            case.get("user_data"),
            ""
        )
        print(f"\n[{case['desc']}] 意图: {case['intent_data']['intent']}")
        print(f"  → task_type: {result['task_type']}")
        print(f"  → steps: {len(result['steps'])} 步")
        for i, step in enumerate(result['steps']):
            print(f"    {i+1}. {step['step']} - plugins: {step.get('plugins', [])}")
            print(f"       reason: {step.get('reason', '')[:30]}...")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_planning_agent())
