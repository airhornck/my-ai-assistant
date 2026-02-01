"""
生成脑门面：按输出类型（文本/图片/视频）路由到对应模块。
配置统一从 config.api_config 的 generation_text/image/video 接口获取。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

# 统一接口配置入口：config/api_config
from config.api_config import get_model_config, MODEL_ROLES
from domain.content.generators import ImageGenerator, TextGenerator, VideoGenerator

if TYPE_CHECKING:
    pass

OUTPUT_TYPE_TEXT = "text"
OUTPUT_TYPE_IMAGE = "image"
OUTPUT_TYPE_VIDEO = "video"


def _get_generator_config_if_ready(role: str) -> dict | None:
    """当角色已配置 model 时返回配置，否则返回 None。"""
    if role not in MODEL_ROLES:
        return None
    cfg = MODEL_ROLES[role]
    if not (cfg.get("model") or "").strip():
        return None
    try:
        return get_model_config(role)
    except Exception:
        return None


class ContentGenerator:
    """
    生成脑门面：模块化设计，按 output_type 路由。
    - text: TextGenerator（generation_text）
    - image: ImageGenerator（占位，待配置 generation_image）
    - video: VideoGenerator（占位，待配置 generation_video）
    """

    def __init__(self, llm_client: Any = None) -> None:
        """
        llm_client 保留以兼容旧注入方式，实际生成使用 api_config 中各接口配置。
        """
        self._text = TextGenerator()  # 使用 generation_text 配置
        img_cfg = _get_generator_config_if_ready("generation_image")
        self._image = ImageGenerator(img_cfg)
        vid_cfg = _get_generator_config_if_ready("generation_video")
        self._video = VideoGenerator(vid_cfg)

    async def generate(
        self,
        analysis: str | dict[str, Any],
        topic: str = "",
        raw_query: str = "",
        session_document_context: str = "",
        output_type: str = OUTPUT_TYPE_TEXT,
    ) -> str:
        """按 output_type 路由到对应生成模块。"""
        if output_type == OUTPUT_TYPE_IMAGE:
            prompt = f"{topic or ''} {raw_query or ''}".strip() or str(analysis)
            return await self._image.generate(prompt=prompt)
        if output_type == OUTPUT_TYPE_VIDEO:
            prompt = f"{topic or ''} {raw_query or ''}".strip() or str(analysis)
            return await self._video.generate(prompt=prompt)
        return await self._text.generate(
            analysis,
            topic=topic,
            raw_query=raw_query,
            session_document_context=session_document_context,
        )
