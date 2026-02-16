"""
视频结构化拆解服务：将原始内容拆解为 VideoContentStructure。
按需调用，不进入主流程。可组合多模态分析。
"""
from services.video_decomposition.port import IVideoDecompositionPort
from services.video_decomposition.factory import get_video_decomposition_port

__all__ = [
    "IVideoDecompositionPort",
    "get_video_decomposition_port",
]
