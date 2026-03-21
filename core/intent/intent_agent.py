"""
意图识别Agent：使用大模型理解自然语言，支持多轮上下文和置信度fallback。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

DEFAULT_INTENT = "free_discussion"
CONFIDENCE_THRESHOLD = 0.6

INTENT_CLASSIFY_SYSTEM = """你是一位专业的意图识别专家。你的任务是根据用户输入准确判断用户的意图。

意图类型定义：
- generate_content: 用户明确要求生成内容（文案、脚本、文章、推广方案等）
- casual_chat: 闲聊、寒暄、问候、无明确目的的对话
- query_info: 查询信息、咨询问题
- account_diagnosis: 账号诊断相关
- strategy_planning: 策略规划、推广方案咨询

关键判断规则：
1. 用户说了"帮我生成"、"帮我写"、"制定"、"创建"等动作词，后面跟着具体内容类型，判为 generate_content
2. 用户只是陈述话题、目标人群、推广意向，但没有要求生成具体内容，判为 query_info 或 free_discussion
3. "谢谢"、"你好"、"在吗"等寒暄判为 casual_chat
4. 询问账号数据、流量、粉丝等判为 account_diagnosis
5. 询问如何推广、有什么策略等判为 strategy_planning

输出格式要求：
- 只输出 JSON 对象，不要任何其他文字
- 必须包含 intent, confidence, raw_query, notes 四个字段
"""

INTENT_EXAMPLES = """
示例：
输入: "帮我生成小红书文案"
输出: {"intent": "generate_content", "confidence": 0.95, "raw_query": "帮我生成小红书文案", "notes": "用户明确要求生成小红书文案"}

输入: "我的账号最近流量不好"
输出: {"intent": "account_diagnosis", "confidence": 0.85, "raw_query": "我的账号最近流量不好", "notes": "用户询问账号流量问题"}

输入: "今天天气不错"
输出: {"intent": "casual_chat", "confidence": 0.98, "raw_query": "今天天气不错", "notes": "闲聊寒暄"}

输入: "想提升账号流量，有什么办法"
输出: {"intent": "query_info", "confidence": 0.8, "raw_query": "想提升账号流量，有什么办法", "notes": "用户咨询提升流量的方法"}

输入: "帮我制定一个推广策略"
输出: {"intent": "strategy_planning", "confidence": 0.9, "raw_query": "帮我制定一个推广策略", "notes": "用户要求制定推广策略"}
"""


class IntentAgent:
    """意图识别Agent：使用大模型进行意图分类，支持置信度和fallback"""

    def __init__(self, llm_client: Any) -> None:
        """
        Args:
            llm_client: LLM客户端，需支持 ainvoke(messages) 接口
        """
        self._llm = llm_client

    async def classify_intent(
        self,
        user_input: str,
        conversation_context: str = "",
    ) -> dict[str, Any]:
        """
        使用大模型理解意图

        Args:
            user_input: 用户输入
            conversation_context: 对话上下文

        Returns:
            {
                "intent": "generate_content" | "casual_chat" | "query_info" | "account_diagnosis" | "strategy_planning" | "free_discussion",
                "confidence": 0.0-1.0,
                "raw_query": "原始用户输入",
                "notes": "模型判断依据",
                "need_clarification": False,
                "clarification_question": ""
            }
        """
        if not user_input or not user_input.strip():
            return self._default_result(user_input, "输入为空")

        user_input = user_input.strip()

        prompt_parts = [
            INTENT_EXAMPLES,
            f"\n用户输入：\n{user_input}",
        ]

        if conversation_context and conversation_context.strip():
            prompt_parts.insert(1, f"对话上下文：\n{conversation_context.strip()}\n")

        user_prompt = "\n".join(prompt_parts)

        messages = [
            SystemMessage(content=INTENT_CLASSIFY_SYSTEM),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await self._llm.invoke(messages)
            raw = (response.content or "").strip() if hasattr(response, 'content') else str(response)

            for prefix in ("```json", "```"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix):].strip()
            if raw.endswith("```"):
                raw = raw[:raw.rfind("```")].strip()

            data = json.loads(raw)

            intent = data.get("intent", DEFAULT_INTENT)
            confidence = float(data.get("confidence", 0.5))
            notes = data.get("notes", "")

            # 更自然的澄清问题：避免二选一拷问式提问
            clarification_question = ""
            if confidence < CONFIDENCE_THRESHOLD:
                # 优先问“你想要的产出/场景”，而不是问分类标签
                clarification_question = "我大概明白你的意思了。你希望我最终给你什么结果：一份可直接发布的内容（文案/脚本），还是先给你分析和建议？（也可以说目标平台/受众/语气）"

            result = {
                "intent": intent,
                "confidence": confidence,
                "raw_query": user_input,
                "notes": notes,
                "need_clarification": confidence < CONFIDENCE_THRESHOLD,
                "clarification_question": clarification_question,
            }

            logger.info(f"IntentAgent: intent={intent}, confidence={confidence}, raw={user_input[:30]}")
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"IntentAgent JSON解析失败: {e}, raw={raw[:100] if raw else 'empty'}")
            return self._default_result(user_input, f"JSON解析失败: {e}")
        except Exception as e:
            logger.exception(f"IntentAgent调用异常: {e}")
            return self._default_result(user_input, f"调用异常: {e}")

    def _default_result(self, user_input: str, reason: str = "") -> dict[str, Any]:
        """返回默认结果"""
        return {
            "intent": DEFAULT_INTENT,
            "confidence": 0.3,
            "raw_query": user_input or "",
            "notes": f"fallback: {reason}",
            "need_clarification": True,
            "clarification_question": "我需要确认您的具体需求，请告诉我您是想生成内容还是咨询问题？"
        }
