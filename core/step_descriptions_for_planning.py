"""
策略脑规划用：步骤名 → 规划描述。
用于动态拼接「可用模块」段落，新增/下线步骤只需在此表维护，无需改 meta_workflow 内长 prompt。
与编排侧 step 名、PARALLEL_STEPS 等对齐；未在此表登记的步骤仍可被编排执行，规划时以 step 名展示。
"""
from __future__ import annotations

# step 名（小写）→ 供 LLM 规划用的简短描述
STEP_DESCRIPTIONS: dict[str, str] = {
    "web_search": "网络检索（竞品、热点、行业动态、通用信息；仅在需要实时/外部信息时添加，非固定步骤）",
    "memory_query": "查询用户历史偏好与品牌事实",
    "kb_retrieve": "知识库检索（行业方法论、案例等，供分析/生成时更垂直、更专业；需要专业方案时可加入）",
    "bilibili_hotspot": "B站热点榜单（检索 B站热门内容，提炼结构与风格，供生成 B站文案时借鉴；用户要生成 B站/小破站内容时可加入）",
    "xiaohongshu_hotspot": "小红书热点（检索小红书热门内容与风格，供生成小红书文案时借鉴；用户要生成小红书/种草内容时可加入）",
    "douyin_hotspot": "抖音热点（检索抖音热门内容与风格，供生成抖音脚本时借鉴；用户要生成抖音/短视频内容时可加入）",
    "acfun_hotspot": "AcFun 热点（检索 AcFun 热门内容与风格，供生成对应平台文案时借鉴）",
    "analyze": "分析（营销场景=品牌与热点关联；通用场景=分析如何回答问题、提取关键信息）",
    "generate": "生成内容（文案、脚本等，params 可含 platform、output_type；未来可扩展图片、视频）",
    "evaluate": "评估内容质量",
    "casual_reply": "闲聊回复（当用户处于问候、寒暄、无明确推广/生成需求时，仅此一步，不规划检索/分析/生成）",
}


def get_step_descriptions_for_planning() -> list[tuple[str, str]]:
    """
    返回 (step_name, description) 列表，用于策略脑 system 中「可用模块」段落的动态拼接。
    顺序保持稳定；未在 STEP_DESCRIPTIONS 中的步骤不会出现在此处（编排仍可执行，仅规划时无描述）。
    """
    order = [
        "web_search",
        "memory_query",
        "kb_retrieve",
        "bilibili_hotspot",
        "xiaohongshu_hotspot",
        "douyin_hotspot",
        "acfun_hotspot",
        "analyze",
        "generate",
        "evaluate",
        "casual_reply",
    ]
    return [(name, STEP_DESCRIPTIONS[name]) for name in order if name in STEP_DESCRIPTIONS]


def build_available_modules_section() -> str:
    """
    组装「可用模块」整段文案（含标题行与条目列表），供 planning_node 拼入 system_prompt。
    """
    lines = [
        "可用模块（可扩展：注册自定义插件后，步骤名与注册名一致即可被编排执行）：",
        *[f"- {name}: {desc}" for name, desc in get_step_descriptions_for_planning()],
        "- 自定义插件: 如 competitor_analysis 等，需先在 PluginRegistry 注册",
    ]
    return "\n".join(lines)
