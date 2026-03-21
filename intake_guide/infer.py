"""
用户友好引导：从用户自然语言做轻量字段/意图补全（不依赖 LLM）。

目标：
- 第二轮用户改变方向（如从“推广产品”转为“打造账号”）时，能更新 topic，避免被上一轮 topic 锁死。
- 用户明确表示“还没有账号/未命名”时，自动填入 brand_name 占位，避免重复追问同一问题。
"""
from __future__ import annotations

import re
from typing import Any


_RE_NO_ACCOUNT = re.compile(r"(还没有|没有|暂无|暂时没有).{0,6}(账号|品牌|名字|名称)")
_RE_EDU = re.compile(r"(教育|教培|培训|课程|考研|英语|数学|语文|留学)")


def infer_fields(raw_text: str, *, existing_ip_context: dict[str, Any] | None = None) -> dict[str, str]:
    """
    从 raw_text 推断可用字段，尽量少做“过度理解”，只做明显的关键字补全。

    Returns:
        { "topic": "...", "brand_name": "...", "product_desc": "..." } 的子集。
    """
    t = (raw_text or "").strip()
    if not t:
        return {}

    out: dict[str, str] = {}
    lower = t.lower()

    # 1) 账号打造意图：用户明确说要打造账号/个人IP（含「建账号/开账号」等常见说法）
    _want_account = "账号" in t or "个人ip" in lower or re.search(r"\bip\b", lower)
    if _want_account and (
        "打造" in t
        or "搭建" in t
        or "做" in t
        or "建" in t
        or "开" in t
        or "注册" in t
    ):
        out["topic"] = "账号打造/个人IP"

    # 2) 推广/营销意图：更偏“产品推广”
    if ("推广" in t or "营销" in t or "投放" in t) and "topic" not in out:
        out["topic"] = "产品推广"

    # 2b) 内容矩阵 / 选题规划（与固定模板 content_matrix 选择器、用户自然表述对齐）
    if "矩阵" in t or ("选题" in t and ("内容" in t or "小红书" in t or "抖音" in t or "b站" in lower)):
        out.setdefault("topic", "内容矩阵与选题")

    # 3) “暂无账号/未命名”：自动填 brand_name 占位，避免重复追问
    if _RE_NO_ACCOUNT.search(t):
        out["brand_name"] = "未命名账号"

    # 4) 简单行业/产品补全：教育类
    if _RE_EDU.search(t):
        # 不覆盖已有更具体描述
        out.setdefault("product_desc", "教育")

    # 5) 品牌/账号名称：「品牌叫X」「品牌名叫X」「账号名X」（短名，避免整句当品牌）
    m = re.search(
        r"(?:品牌名|品牌|账号名|账号名称|名字叫)(?:叫|名为|是|：|:)\s*([^\s，,。]{1,32})",
        t,
    )
    if m:
        cand = m.group(1).strip()
        if cand and len(cand) <= 32:
            out["brand_name"] = cand

    # 6) 账号问题/诊断诉求（与 ip_diagnosis 模板、必填 topic 对齐）
    if any(k in t for k in ("流量", "诊断", "掉粉", "限流", "数据很差")):
        out.setdefault("topic", "账号诊断与流量")

    return out

