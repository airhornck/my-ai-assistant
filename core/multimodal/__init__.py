"""
多模态内容理解：图像/视频分析能力。
按需调用，不进入主流程。供封面诊断、限流诊断、视频结构拆解等插件使用。
"""
from core.multimodal.port import IMultimodalPort, ImageAnalysisResult, VideoAnalysisResult
from core.multimodal.factory import get_multimodal_port

__all__ = [
    "IMultimodalPort",
    "ImageAnalysisResult",
    "VideoAnalysisResult",
    "get_multimodal_port",
]
