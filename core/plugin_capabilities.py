"""
插件能力描述：供「后续建议」等引导用户续聊时使用。
与 brain_plugin_center 中的 ANALYSIS_BRAIN_PLUGINS / GENERATION_BRAIN_PLUGINS 对应，
提供人类可读的「还能帮你做什么」描述。
"""
from __future__ import annotations

# 分析脑插件：插件名 -> 引导话术（用于「如果你需要，我还可以帮你…」）
ANALYSIS_PLUGIN_FOLLOWUP: dict[str, str] = {
    "bilibili_hotspot": "获取 B站热点榜单与创作风格参考，供生成 B站/小破站文案时借鉴",
    "methodology": "获取行业方法论与框架，丰富活动方案的理论支撑",
    "case_library": "获取案例库中的优秀案例，供方案或文案参考",
    "knowledge_base": "从知识库检索行业方法论、案例等，让分析更垂直、更专业",
    "campaign_context": "拼装活动方案上下文（方法论+案例库+知识库），为生成完整方案打基础",
}

# 生成脑插件：插件名 -> 引导话术
GENERATION_PLUGIN_FOLLOWUP: dict[str, str] = {
    "text_generator": "根据当前分析结果生成推广文案、脚本（可指定平台如小红书、B站等）",
    "campaign_plan_generator": "生成完整活动方案或数据接入优先级矩阵（按「业务价值」与「采集复杂度」排序），便于优先接入高价值、易采集的数据快速启动项目",
    "image_generator": "根据方案或文案生成配图",
    "video_generator": "根据方案或脚本生成视频",
}


def get_all_followup_descriptions() -> list[tuple[str, str]]:
    """返回 (插件名, 引导话术) 列表，供 LLM 生成后续建议时使用。"""
    out: list[tuple[str, str]] = []
    for name, desc in ANALYSIS_PLUGIN_FOLLOWUP.items():
        out.append((name, desc))
    for name, desc in GENERATION_PLUGIN_FOLLOWUP.items():
        out.append((name, desc))
    return out
