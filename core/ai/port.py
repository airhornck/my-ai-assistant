"""
AI 调用协议：实现者可替换为不同供应商（阿里云、OpenAI 等）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ILLMClient(Protocol):
    """
    LLM 调用协议。
    实现方按 task_type/complexity 内部路由到合适模型。
    """

    async def invoke(
        self,
        messages: list,
        *,
        task_type: str = "chat",
        complexity: str = "medium",
    ) -> str:
        """
        调用 LLM，返回纯文本。
        messages: LangChain 格式 [SystemMessage(...), HumanMessage(...)] 或等价结构
        task_type: planning|analysis|generation|evaluation|chat_reply
        complexity: low|medium|high
        """
        ...
