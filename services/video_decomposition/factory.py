"""
视频拆解工厂：按配置选择实现。
"""
from __future__ import annotations

import os
from typing import Any, Optional

from services.video_decomposition.port import IVideoDecompositionPort
from services.video_decomposition.mock_adapter import MockVideoDecompositionAdapter


def get_video_decomposition_port(
    *,
    provider: str | None = None,
    multimodal_port: Any = None,
) -> IVideoDecompositionPort:
    """
    获取视频拆解 Port。
    环境变量：VIDEO_DECOMPOSITION_PROVIDER=mock|full
    full 时可注入 multimodal_port，实现视频 URL 的多模态分析 + 拆解。
    """
    p = (provider or os.getenv("VIDEO_DECOMPOSITION_PROVIDER", "mock")).strip().lower()
    if p == "full" and multimodal_port is not None:
        # TODO: 返回组合多模态的完整实现
        pass
    return MockVideoDecompositionAdapter()
