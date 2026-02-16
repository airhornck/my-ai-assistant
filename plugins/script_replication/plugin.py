"""
脚本复刻插件：分析脑实时插件。
参考 Veogo AI：智能拆解爆款基因。
检索爆款样本、结构化拆解、复刻要点提炼。
依赖：sample_library、video_decomposition_port、ai_service（LLM 提炼）。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

FALLBACK = """【脚本复刻】
复刻要点：开场吸睛、分点阐述、结尾互动
（sample_library 未配置时使用兜底）"""


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册脚本复刻插件。"""
    sample_library = config.get("sample_library")
    decomposition_port = config.get("video_decomposition_port")
    ai_service = config.get("ai_service")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        existing = context.get("analysis") or {}
        if not isinstance(existing, dict):
            existing = {}
        pi = context.get("plugin_input") or {}
        platform = pi.get("platform", "") or "default"
        topic = pi.get("topic", "") or getattr(context.get("request"), "topic", "") or ""
        category = pi.get("category", "")

        if not sample_library:
            return {"analysis": {**existing, "script_replication": FALLBACK}}

        try:
            samples = await sample_library.search(
                platform=platform,
                category=category,
                top_k=5,
            )
            if not samples:
                return {"analysis": {**existing, "script_replication": f"【脚本复刻】未找到平台「{platform}」的爆款样本，请先入库或切换平台"}}

            # 简要描述样本
            sample_summaries = []
            for s in samples[:5]:
                title = getattr(s, "title", "") or (s.get("title", "") if isinstance(s, dict) else "")
                metrics = getattr(s, "metrics", None) or (s.get("metrics", {}) if isinstance(s, dict) else {}) or {}
                play = metrics.get("play_count", metrics.get("play", 0))
                sample_summaries.append(f"- {title[:40]}... 播放/曝光：{play}")

            sample_text = "\n".join(sample_summaries)

            # 若有拆解端口，对首条样本做拆解
            structure_text = ""
            if decomposition_port and samples:
                try:
                    first = samples[0]
                    vid = getattr(first, "video_id", "") or (first.get("video_id", "") if isinstance(first, dict) else "")
                    if vid:
                        struct = await decomposition_port.decompose(
                            platform=platform,
                            raw_text=str(getattr(first, "features", first.get("features", {})) if hasattr(first, "features") else ""),
                        )
                        structure_text = f"\n【首条样本结构】\n开场：{struct.opening_style}\n转折点：{len(struct.turning_points)} 个\n行动召唤：{struct.call_to_action}"
                except Exception as e:
                    logger.debug("脚本复刻：拆解失败 %s", e)

            # LLM 提炼复刻要点
            if ai_service:
                try:
                    prompt = f"""根据以下爆款样本，提炼可复刻的脚本要点。

【平台】{platform}
【目标主题】{topic or '通用'}

【爆款样本】
{sample_text}
{structure_text}

请输出 3-5 条可操作的复刻要点，包含：开场方式、内容结构、话术技巧、互动引导。控制在 200 字以内。"""
                    raw = await ai_service._llm.invoke(
                        [SystemMessage(content="你是爆款脚本复刻专家。"), HumanMessage(content=prompt)],
                        task_type="analysis",
                        complexity="medium",
                    )
                    report = f"【脚本复刻】\n{(raw or '').strip()}" or FALLBACK
                except Exception as e:
                    logger.warning("脚本复刻 LLM 失败: %s", e)
                    report = f"【脚本复刻】\n参考样本：\n{sample_text}\n（LLM 提炼失败，请直接参考上述样本）"
            else:
                report = f"【脚本复刻】\n参考样本：\n{sample_text}"

            return {"analysis": {**existing, "script_replication": report}}
        except Exception as e:
            logger.warning("脚本复刻失败: %s", e)
            return {"analysis": {**existing, "script_replication": FALLBACK}}

    plugin_center.register_plugin(
        "script_replication",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )
