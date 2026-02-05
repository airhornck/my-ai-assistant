"""营销意图分类器快速测试"""
from core.intent.marketing_intent_classifier import MarketingIntentClassifier

classifier = MarketingIntentClassifier(use_fallback_llm=False)
test_cases = [
    ("怎么推广我的小红书账号？", True),
    ("帮我写一个抖音营销方案", True),
    ("如何打造个人IP实现变现？", True),
    ("你好", False),
    ("今天天气不错", False),
    ("我想推广一下", True),
    ("营销是什么？", True),
    ("谢谢", False),
    ("再见", False),
]
print("营销意图分类器测试：")
for text, expected in test_cases:
    r = classifier.classify(text)
    ok = r.is_marketing == expected
    status = "OK" if ok else "FAIL"
    pred = "营销" if r.is_marketing else "闲聊"
    exp = "营销" if expected else "闲聊"
    print(f"  [{status}] '{text}' -> {pred} (期望{exp}), conf={r.confidence:.2f}, reason={r.reason}")
print("完成")
