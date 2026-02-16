"""
意图识别全面测试 - 完整流程（需要 API Key）
测试 core/intent/processor.py 的完整意图分类
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent.processor import InputProcessor


async def test_full_intent_classification():
    """测试完整意图分类流程"""
    processor = InputProcessor(use_rule_based_intent_filter=True)
    
    test_cases = [
        # (输入, 期望意图, 说明)
        
        # 闲聊类
        ("你好", "casual_chat", "问候"),
        ("在吗", "casual_chat", "问候"),
        ("今天天气不错", "casual_chat", "闲聊"),
        ("谢谢", "casual_chat", "感谢"),
        ("再见", "casual_chat", "告别"),
        
        # 明确生成内容
        ("帮我写一篇小红书文案", "free_discussion", "明确要求生成"),
        ("生成一个抖音脚本", "free_discussion", "明确要求生成"),
        ("写一篇B站推广文章", "free_discussion", "明确要求生成"),
        ("帮我写个文案", "free_discussion", "明确要求生成"),
        
        # 营销意图
        ("推广我的产品", "free_discussion", "推广意向"),
        ("怎么做品牌营销", "free_discussion", "营销讨论"),
        ("如何提升账号流量", "free_discussion", "流量问题"),
        
        # 结构化请求
        ("品牌是苹果，产品是手机，主题是新品发布", "structured_request", "完整结构化"),
        ("推广华为手机，目标人群是年轻人", "structured_request", "部分结构化"),
        
        # 命令
        ("/new_chat", "command", "命令"),
        ("/help", "command", "命令"),
    ]
    
    print("\n========== Full Intent Classification Test ==========\n")
    
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
            if result.get("structured_data"):
                print(f"  Data: {result.get('structured_data')}")
            print(f"  Explicit: {result.get('explicit_content_request')}")
            print()
        except Exception as e:
            results.append(False)
            print(f"[ERROR] [{desc}] Input: {text}")
            print(f"  Error: {e}")
            print()
    
    # Stats
    passed = sum(results)
    total = len(results)
    print(f"\n========== Summary ==========")
    print(f"Passed: {passed}/{total} ({passed/total*100:.1f}%)")
    
    return passed, total


async def test_edge_cases():
    """测试边界情况"""
    processor = InputProcessor(use_rule_based_intent_filter=True)
    
    print("\n========== Edge Cases Test ==========\n")
    
    edge_cases = [
        ("帮我写个", "explicit_content_request should be True"),
        ("", "empty input"),
        ("   ", "whitespace only"),
        ("品牌", "only brand keyword"),
        ("产品描述", "only product keyword"),
        ("A和B", "short random"),
    ]
    
    for text, desc in edge_cases:
        try:
            result = await processor.process(
                raw_input=text,
                session_id="test",
                user_id="test"
            )
            print(f"[{desc}]")
            print(f"  Input: '{text}'")
            print(f"  Intent: {result.get('intent')}")
            print(f"  Explicit: {result.get('explicit_content_request')}")
            print()
        except Exception as e:
            print(f"[ERROR] {desc}: {e}")
            print()


if __name__ == "__main__":
    print("Testing with real API...")
    asyncio.run(test_full_intent_classification())
    asyncio.run(test_edge_cases())
