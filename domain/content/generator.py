"""
生成脑门面：仅通过插件中心按 output_type 与 generation_plugins 调用插件。
文本/图片/视频/PPT 等能力均以插件方式登记，模型配置由各脑的插件中心 config 管理。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.brain_plugin_center import BrainPluginCenter

logger = logging.getLogger(__name__)

OUTPUT_TYPE_TEXT = "text"
OUTPUT_TYPE_IMAGE = "image"
OUTPUT_TYPE_VIDEO = "video"

# 按 output_type 的默认插件列表（规划脑未指定时使用）
DEFAULT_GENERATION_PLUGINS_BY_TYPE: dict[str, List[str]] = {
    OUTPUT_TYPE_TEXT: ["text_generator"],
    OUTPUT_TYPE_IMAGE: ["image_generator"],
    OUTPUT_TYPE_VIDEO: ["video_generator"],
}


class ContentGenerator:
    """
    生成脑门面：仅通过 plugin_center 调用插件，无内置 _text/_image/_video。
    规划脑通过 generation_plugins 指定插件列表；未指定时按 output_type 使用默认插件。
    """

    def __init__(self, llm_client: Any = None) -> None:
        """llm_client 保留以兼容旧注入，实际生成由插件中心内插件完成。"""
        self.plugin_center: BrainPluginCenter | None = None

    async def generate(
        self,
        analysis: str | dict[str, Any],
        topic: str = "",
        raw_query: str = "",
        session_document_context: str = "",
        output_type: str = OUTPUT_TYPE_TEXT,
        generation_plugins: Optional[List[str]] = None,
        memory_context: str = "",
        source_content: Optional[str] = None,
    ) -> str:
        """仅通过插件中心执行；source_content 非空且 output_type=rewrite 时为对上文的风格改写。"""
        if not self.plugin_center:
            logger.warning("生成脑未挂载 plugin_center，无法生成")
            return "（生成脑未配置插件中心）"
        plugins = generation_plugins or DEFAULT_GENERATION_PLUGINS_BY_TYPE.get(
            output_type, ["text_generator"]
        )
        ctx = {
            "analysis": analysis if isinstance(analysis, dict) else {},
            "topic": topic,
            "raw_query": raw_query,
            "session_document_context": session_document_context,
            "memory_context": memory_context,
            "output_type": output_type,
            "source_content": (source_content or "").strip() or None,
        }
        for name in plugins:
            if not self.plugin_center.has_plugin(name):
                continue
            try:
                out = await self.plugin_center.get_output(name, ctx)
                if out and isinstance(out, dict) and out.get("content"):
                    return (out["content"] or "").strip()
            except Exception as e:
                logger.warning("生成脑插件 %s 失败: %s", name, e)
        return "（无可用生成插件或插件未返回内容）"
