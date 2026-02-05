"""测试反馈意图分类"""
from core.intent import classify_feedback_after_creation

tests = [
    # (msg, has_plan, last_role, previous_was_creation)
    ("还不错", True, "assistant", True),
    ("好的", True, "assistant", True),
    ("需要", True, "assistant", True),
    ("还行", True, "assistant", True),
    ("一般", True, "assistant", True),
    ("还不错", False, "assistant", True),
    ("好的", False, "assistant", True),
    # 闲聊延续：「还好吧」在 casual_reply 后表示「我还好」，不应视为模糊评价
    ("还好吧", True, "assistant", False),
    ("还好吧", True, "assistant", True),
]
for item in tests:
    msg, has_plan, last_role = item[0], item[1], item[2]
    prev_creation = item[3] if len(item) > 3 else False
    r = classify_feedback_after_creation(msg, has_plan, last_role, prev_creation)
    print(f"'{msg}' has_plan={has_plan} prev_creation={prev_creation} -> accept={r.accepted_suggestion} ambiguous={r.ambiguous_feedback} reason={r.reason}")
