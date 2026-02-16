"""
意图识别测试 - 纯规则部分（无需 API Key）
测试 core/intent/processor.py 中的规则逻辑
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intent.processor import (
    SHORT_CASUAL_REPLIES,
    _has_explicit_content_request,
    COMMAND_PATTERN,
)


def test_short_casual_replies():
    """测试简短闲聊判断"""
    print("\n========== SHORT_CASUAL_REPLIES Test ==========\n")
    
    test_cases = [
        ("你好", True),
        ("您好", True),
        ("嗨", True),
        ("在吗", True),
        ("哈喽", True),
        ("还好", True),
        ("嗯", True),
        ("不错", True),
        ("还行", True),
        ("一般", True),
        ("谢谢", False),  # 谢谢可能表示采纳建议
        ("帮我写文案", False),
        ("推广产品", False),
    ]
    
    passed = 0
    for text, expected in test_cases:
        result = text.strip() in SHORT_CASUAL_REPLIES
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"[{status}] '{text}' -> {result} (expected {expected})")
    
    print(f"\nPassed: {passed}/{len(test_cases)}")
    return passed


def test_explicit_content_request():
    """测试明确内容请求判断"""
    print("\n========== EXPLICIT_CONTENT_PHRASES Test ==========\n")
    
    test_cases = [
        # 应该返回 True
        ("帮我写一篇小红书文案", True),
        ("生成一个抖音脚本", True),
        ("写一篇B站推广文章", True),
        ("帮我写个文案", True),
        ("写个抖音脚本", True),
        ("出一个知乎文章", True),
        ("创作一篇内容", True),
        ("小红书文案", True),
        ("抖音脚本", True),
        ("B站文案", True),
        
        # 应该返回 False
        ("推广我的产品", False),
        ("你好", False),
        ("怎么做品牌营销", False),
        ("如何提升流量", False),
        ("帮我分析一下", False),
        ("谢谢", False),
    ]
    
    passed = 0
    for text, expected in test_cases:
        result = _has_explicit_content_request(text)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"[{status}] '{text}' -> {result} (expected {expected})")
    
    print(f"\nPassed: {passed}/{len(test_cases)}")
    return passed


def test_command_pattern():
    """测试命令匹配"""
    print("\n========== COMMAND_PATTERN Test ==========\n")
    
    test_cases = [
        ("/new_chat", "new_chat"),
        ("/help", "help"),
        ("/restart  ", "restart"),
        ("  /test", "test"),
        ("这不是命令", None),
        ("/abc/def", "abc"),  # 只匹配第一个词
    ]
    
    passed = 0
    for text, expected in test_cases:
        match = COMMAND_PATTERN.match(text)
        result = match.group(1) if match else None
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"[{status}] '{text}' -> {result} (expected {expected})")
    
    print(f"\nPassed: {passed}/{len(test_cases)}")
    return passed


def test_intent_rules_summary():
    """意图识别规则汇总测试"""
    print("\n========== Intent Rules Summary Test ==========\n")
    
    # 导入新增的函数
    from core.intent.processor import _is_structured_request
    
    # 模拟意图分类逻辑（使用更新后的规则）
    def classify_intent(text):
        text = text.strip()
        
        # 1. 命令检查
        if COMMAND_PATTERN.match(text):
            return "command"
        
        # 2. 简短闲聊
        if text in SHORT_CASUAL_REPLIES:
            return "casual_chat"
        
        # 3. 明确内容请求
        if _has_explicit_content_request(text):
            return "free_discussion"  # 明确要求生成内容
        
        # 4. 结构化请求（使用新增的规则函数）
        if _is_structured_request(text):
            return "structured_request"
        
        # 5. 营销关键词（简化判断）
        marketing_keywords = ["推广", "营销", "品牌", "产品", "流量", "账号", "IP", "变现", "竞品"]
        if any(kw in text for kw in marketing_keywords):
            return "free_discussion"
        
        return "casual_chat"  # 默认闲聊
    
    test_cases = [
        # (输入, 期望意图)
        ("你好", "casual_chat"),
        ("在吗", "casual_chat"),
        ("谢谢", "casual_chat"),
        ("/new_chat", "command"),
        ("帮我写一篇小红书文案", "free_discussion"),
        ("推广我的产品", "free_discussion"),
        ("怎么做品牌营销", "free_discussion"),
        ("如何提升账号流量", "free_discussion"),
        ("品牌是苹果，产品是手机", "structured_request"),
        ("今天天气不错", "casual_chat"),
    ]
    
    passed = 0
    for text, expected in test_cases:
        result = classify_intent(text)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"[{status}] '{text}' -> {result} (expected {expected})")
    
    print(f"\nPassed: {passed}/{len(test_cases)}")
    return passed


if __name__ == "__main__":
    p1 = test_short_casual_replies()
    p2 = test_explicit_content_request()
    p3 = test_command_pattern()
    p4 = test_intent_rules_summary()
    
    total = p1 + p2 + p3 + p4
    print(f"\n========== TOTAL ==========")
    print(f"Total Passed: {total}")
