"""
策略规划Agent：根据意图输出执行计划（步骤+插件），不再硬编码。
插件列表从 brain_plugin_center 动态获取。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

STEP_TYPES = """
可用的步骤类型：
- analyze: 分析（调用分析脑插件）
- generate: 生成内容（调用生成脑插件）
- evaluate: 评估生成内容
- web_search: 网络搜索
- memory_query: 记忆查询
- kb_retrieve: 知识库检索
- casual_reply: 闲聊回复
"""


def _get_available_plugins() -> tuple[str, str]:
    """
    从 brain_plugin_center 获取可用的插件列表
    返回: (analysis_plugins_str, generation_plugins_str)
    """
    try:
        from core.brain_plugin_center import BrainPluginCenter, ANALYSIS_BRAIN_PLUGINS, GENERATION_BRAIN_PLUGINS
        
        # 从插件注册列表中提取名称
        analysis_plugins = []
        for plugin_path, _ in ANALYSIS_BRAIN_PLUGINS:
            # 从 "plugins.xxx.plugin" 提取 "xxx"
            name = plugin_path.replace("plugins.", "").replace(".plugin", "")
            analysis_plugins.append(name)
        
        generation_plugins = []
        for plugin_path, _ in GENERATION_BRAIN_PLUGINS:
            name = plugin_path.replace("plugins.", "").replace(".plugin", "")
            generation_plugins.append(name)
        
        analysis_str = "可用的分析脑插件：\n- " + "\n- ".join(analysis_plugins) if analysis_plugins else "无"
        generation_str = "可用的生成脑插件：\n- " + "\n- ".join(generation_plugins) if generation_plugins else "无"
        
        return analysis_str, generation_str
    except Exception as e:
        logger.warning(f"获取插件列表失败: {e}")
        return "获取插件列表失败", "获取插件列表失败"


PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是策略规划专家，负责根据用户意图规划执行步骤。

{step_types}

{analysis_plugins}

{generation_plugins}

规划原则：
1. generate_content 意图 → 必须包含 generate 步骤，analyze 步骤根据需要添加热点/分析插件；仅在需要实时/外部信息（如竞品、行业动态）时加入 web_search，否则不添加。
2. casual_chat 意图 → 只规划 casual_reply 步骤
3. query_info 意图 → 仅在用户问题需要联网检索（实时数据、外部事实）时加入 web_search；否则只规划 analyze + casual_reply。不要默认加入 web_search。
4. account_diagnosis 意图 → 规划 analyze（调用 account_diagnosis 插件）
5. strategy_planning 意图 → 规划 analyze（可含案例库、方法论） + 策略输出；仅当明确需要外部信息时加入 web_search。
6. free_discussion 意图 → 根据上下文判断，若有明确目标则规划 analyze + generate，否则 casual_reply。web_search 仅在有需要时添加。

输出格式要求：
- 只输出 JSON 对象，不要任何其他文字
- 必须包含 task_type, steps 两个字段
- steps 是数组，每项包含 step, plugins, reason 三个字段
- plugins 字段必须从上述可用插件列表中选择
"""


class PlanningAgent:
    """策略规划Agent：根据意图动态规划执行步骤和插件"""

    def __init__(self, llm_client: Any) -> None:
        """
        Args:
            llm_client: LLM客户端，需支持 ainvoke(messages) 接口
        """
        self._llm = llm_client
        # 动态获取插件列表
        self._analysis_plugins, self._generation_plugins = _get_available_plugins()
        # 生成系统 prompt
        self._system_prompt = PLANNING_SYSTEM_PROMPT_TEMPLATE.format(
            step_types=STEP_TYPES,
            analysis_plugins=self._analysis_plugins,
            generation_plugins=self._generation_plugins,
        )
        logger.info(f"PlanningAgent 初始化，可用分析插件: {self._analysis_plugins[:100]}...")

    async def plan_steps(
        self,
        intent_data: dict[str, Any],
        user_data: Optional[dict[str, Any]] = None,
        conversation_context: str = "",
    ) -> dict[str, Any]:
        """
        根据意图输出执行计划

        Args:
            intent_data: IntentAgent 返回的意图数据
            user_data: 用户数据（品牌、产品、主题等）
            conversation_context: 对话上下文

        Returns:
            {
                "task_type": "campaign_or_copy" | "casual" | "info_query" | ...,
                "steps": [
                    {"step": "analyze", "plugins": ["bilibili_hotspot"], "reason": "..."},
                    {"step": "generate", "plugins": ["text_generator"], "reason": "..."}
                ]
            }
        """
        intent = intent_data.get("intent", "free_discussion")
        confidence = intent_data.get("confidence", 0.5)
        raw_query = intent_data.get("raw_query", "")
        notes = intent_data.get("notes", "")

        user_data = user_data or {}
        brand = user_data.get("brand_name", "")
        product = user_data.get("product_desc", "")
        topic = user_data.get("topic", "")
        platform = user_data.get("platform", "")

        user_prompt = f"""【意图识别结果】
- 意图类型: {intent}
- 置信度: {confidence}
- 用户原始输入: {raw_query}
- 判断依据: {notes}

【用户信息】
- 品牌: {brand or "未指定"}
- 产品: {product or "未指定"}
- 话题/目标: {topic or "未指定"}
- 目标平台: {platform or "未指定"}

【对话上下文】
{conversation_context[:500] if conversation_context else "无"}

请根据上述信息规划执行步骤："""

        messages = [
            SystemMessage(content=self._system_prompt),
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

            plan = json.loads(raw)

            task_type = plan.get("task_type", "campaign_or_copy")
            steps = plan.get("steps", [])

            logger.info(f"PlanningAgent: task_type={task_type}, steps_count={len(steps)}, intent={intent}")
            return {
                "task_type": task_type,
                "steps": steps,
                "intent": intent,
                "confidence": confidence,
            }

        except json.JSONDecodeError as e:
            logger.warning(f"PlanningAgent JSON解析失败: {e}, raw={raw[:100] if raw else 'empty'}")
            return self._fallback_plan(intent)
        except Exception as e:
            logger.exception(f"PlanningAgent调用异常: {e}")
            return self._fallback_plan(intent)

    def _fallback_plan(self, intent: str) -> dict[str, Any]:
        """根据意图返回兜底计划"""
        if intent == "casual_chat":
            return {
                "task_type": "casual",
                "steps": [
                    {"step": "casual_reply", "plugins": [], "reason": "闲聊回复"}
                ],
                "intent": intent,
                "confidence": 0.3,
            }
        elif intent == "generate_content":
            return {
                "task_type": "campaign_or_copy",
                "steps": [
                    {"step": "analyze", "plugins": ["bilibili_hotspot_enhanced"], "reason": "分析热点"},
                    {"step": "generate", "plugins": ["text_generator"], "reason": "生成内容"}
                ],
                "intent": intent,
                "confidence": 0.3,
            }
        elif intent == "account_diagnosis":
            return {
                "task_type": "account_diagnosis",
                "steps": [
                    {"step": "memory_query", "plugins": [], "reason": "查询用户记忆与近期交互"},
                    {"step": "analyze", "plugins": ["account_diagnosis"], "reason": "账号诊断"}
                ],
                "intent": intent,
                "confidence": 0.3,
            }
        else:
            return {
                "task_type": "campaign_or_copy",
                "steps": [
                    {"step": "analyze", "plugins": [], "reason": "分析信息"},
                    {"step": "casual_reply", "plugins": [], "reason": "回复用户"}
                ],
                "intent": intent,
                "confidence": 0.3,
            }
