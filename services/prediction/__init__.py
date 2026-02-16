"""
预测模型服务：爆款预测、CTR 预估等。
按需调用，不进入主流程。供爆款预测、封面诊断等插件使用。
"""
from services.prediction.port import IPredictionPort, ViralPredictionResult, CTRPredictionResult
from services.prediction.factory import get_prediction_port

__all__ = [
    "IPredictionPort",
    "ViralPredictionResult",
    "CTRPredictionResult",
    "get_prediction_port",
]
