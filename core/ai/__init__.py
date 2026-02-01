"""
AI 调用抽象：定义 ILLMClient 协议，支持替换不同供应商实现。
"""
from core.ai.port import ILLMClient
from core.ai.dashscope_client import DashScopeLLMClient

__all__ = ["ILLMClient", "DashScopeLLMClient"]
