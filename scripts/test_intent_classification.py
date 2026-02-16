"""
意图识别全面测试脚本
测试 core/intent/processor.py 中的意图分类逻辑
"""
import asyncio
import os
import sys
from pathlib import Path

# 确保可以导入项目模块
sys.path.insert(0, str(Path(__file__).parent.parent))

# 设置测试环境变量
os.environ.setdefault("DASHSCOPE_API_KEY", "test-key")
os.environ.setdefault("SEARCH_PROVIDER", "mock")

from core.intent.processor import InputProcessor, _has_explicit_content_request


async def test_intent_classification():
    """测试意图分类"""
    processor = InputProcessor(use_rule_based_intent_filter=True)
    
    test_cases = [
        # (输入, 期望意图, 说明)
        # 闲聊类
        ("你好", "casual_chat", "问候"),
        ("在吗", "casual_chat", "问候"),
        ("今天天气不错", "casual_chat", "闲聊"),
        ("谢谢", "casual_chat", "感谢"),
        ("再见", "casual_chat", "告别"),
        ("还好吧", "casual_chat", "简短寒暄"),
        
        # 明确生成内容
        ("帮我写一篇小红书文案", "free_discussion", "明确要求生成"),
        ("生成一个抖音脚本", "free_discussion", "明确要求生成"),
        ("写一篇B站推广文章", "free_discussion", "明确要求生成"),
        ("帮我写个文案", "free_discussion", "明确要求生成"),
        
        # 营销意图
        ("推广我的产品", "free_discussion", "推广意向"),
        ("怎么做品牌营销", "free_discussion", "营销讨论"),
        ("如何提升账号流量", "free_discussion", "流量问题"),
        ("帮我分析下竞品", "free_discussion", "竞品分析"),
        
        # 结构化请求
        ("品牌是苹果，产品是手机，主题是新品发布", "structured_request", "完整结构化"),
        ("推广华为手机，目标人群是年轻人", "structured_request", "部分结构化"),
        
        # 命令
        ("/new_chat", "command", "命令"),
        ("/help", "command", "命令"),
    ]
    
    print("\n========== Intent Classification Test ==========\n")
    
    results = []
    for text, expected_intent, desc in test_cases:
        try:
            result = await processor.process(
                raw_input=text,
                session_id="test-session",
                user_id="test-user"
            )
            intent = result.get("intent", "")
            
            # 宽松匹配
            if expected_intent in ("casual_chat", "free_discussion") and intent in ("casual_chat", "free_discussion"):
                matched = True
            else:
                matched = intent == expected_intent
            
            results.append(matched)
            status = "PASS" if matched else "FAIL"
            print(f"[{status}] [{desc}]")
            print(f"  Input: {text}")
            print(f"  Expected: {expected_intent}, Actual: {intent}")
            print()
        except Exception as e:
            results.append(False)
            print(f"[ERROR] [{desc}] Input: {text}")
            print(f"  Error: {e}")
            print()
    
    # Test explicit_content_request
    print("\n========== explicit_content_request Test ==========\n")
    explicit_cases = [
        ("帮我写一篇小红书文案", True),
        ("推广我的产品", False),
        ("你好", False),
        ("生成一个抖音脚本", True),
        ("帮我写个文案", True),
        ("怎么做品牌营销", False),
    ]
    
    for text, expected in explicit_cases:
        result = _has_explicit_content_request(text)
        status = "PASS" if result == expected else "FAIL"
        print(f"[{status}] '{text}' -> {result} (expected {expected})")
    
    # Stats
    passed = sum(results)
    total = len(results)
    print(f"\n========== Summary ==========")
    print(f"Passed: {passed}/{total} ({passed/total*100:.1f}%)")
    
    return passed, total


async def test_intent_with_history():
    """测试带上下文的意图识别"""
    processor = InputProcessor(use_rule_based_intent_filter=True)
    
    print("\n========== Context Test ==========\n")
    
    # Test scenario: user says hello first, then makes a request
    conversation_context = "用户: 你好\n助手: 您好！有什么可以帮您？"
    
    result = await processor.process(
        raw_input="我想推广我的产品",
        session_id="test-session",
        user_id="test-user",
        conversation_context=conversation_context
    )
    
    print(f"Input: 我想推广我的产品")
    print(f"Context: contains '你好' + assistant reply + promotion request")
    print(f"Result: {result.get('intent')}")
    print(f"Data: {result.get('structured_data', {})}")


if __name__ == "__main__":
    asyncio.run(test_intent_classification())
    asyncio.run(test_intent_with_history())
