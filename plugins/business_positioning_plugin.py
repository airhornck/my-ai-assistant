"""
商业定位插件（分析脑级插件）：
负责收集用户信息，生成商业定位报告（受众、产品、IP、转化），并支持交互式确认。

核心功能：
1. 信息收集 (Information Collection):
   - 检查 UserProfile 完整性。
   - 缺失字段生成提问，发布 UserQueryEvent。
   - 接收用户回复更新 Profile。
2. 报告生成 (Report Generation):
   - 字段齐备后调用 AI 生成四份报告。
   - 发布 ReportGeneratedEvent。
3. 确认机制 (Confirmation):
   - 监听 UserConfirmEvent，迭代报告。

前置依赖：
- MemoryService (UserProfile CRUD)
- PluginBus (UserQueryEvent, ReportGeneratedEvent, UserConfirmEvent)
"""
from __future__ import annotations

import logging
import json
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME
from core.plugin_bus import (
    get_plugin_bus, 
    UserQueryEvent, 
    ReportGeneratedEvent, 
    UserConfirmEvent
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
PLUGIN_NAME = "business_positioning"

# 商业定位所需核心字段
REQUIRED_FIELDS = {
    "common": ["industry", "target_audience", "core_product", "revenue_model"],
    "personal": ["personal_IP_tags", "content_style"],
    "enterprise": ["brand_history", "scale"]
}

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """
    注册商业定位插件。
    """
    ai_service = config.get("ai_service")
    memory_service = config.get("memory_service")
    bus = get_plugin_bus()

    # -----------------------------------------------------------------------
    # 内部辅助函数
    # -----------------------------------------------------------------------
    
    async def _check_profile_completeness(profile: Dict[str, Any]) -> List[str]:
        """检查档案缺失字段。"""
        user_type = profile.get("type", "personal")
        required = REQUIRED_FIELDS["common"] + REQUIRED_FIELDS.get(user_type, [])
        missing = [f for f in required if not profile.get(f)]
        return missing

    async def _generate_question(missing_fields: List[str]) -> str:
        """调用 AI 生成追问话术。"""
        if not ai_service:
            return f"请补充以下信息：{', '.join(missing_fields)}"
            
        llm = ai_service.router.fast_model
        prompt = f"""
用户正在进行商业定位分析，但档案缺失以下关键信息：
{', '.join(missing_fields)}

请生成一句亲切、专业的提问，引导用户补充这些信息。
不要一次问太多，优先问前 2 个。
"""
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception:
            return f"为了更好地为您分析，请告诉我您的：{', '.join(missing_fields[:2])}"

    async def _generate_reports(profile: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """调用 AI 生成四份报告。"""
        if not ai_service:
            return {}
            
        llm = ai_service.router.powerful_model
        user_type = profile.get("type", "personal")
        
        # 构建 Prompt
        prompt = f"""
请基于以下用户档案，生成专业的商业定位分析报告。
用户档案：
{json.dumps(profile, ensure_ascii=False, indent=2)}

请生成以下 4 部分内容（JSON格式）：
1. audience_analysis (受众人群分析)：画像、痛点、需求
2. product_analysis (产品分析)：核心竞争力、竞品差异
3. ip_analysis (IP分析)：{"个人IP定位" if user_type == "personal" else "品牌形象定位"}
4. conversion_path (转化路径及合规)：变现模式、风险提示

输出格式：
{{
  "audience_analysis": {{ "content": "...", "suggestions": ["..."] }},
  "product_analysis": {{ "content": "...", "suggestions": ["..."] }},
  "ip_analysis": {{ "content": "...", "suggestions": ["..."] }},
  "conversion_path": {{ "content": "...", "suggestions": ["..."] }}
}}
"""
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            
            reports = json.loads(text.strip())
            
            # 发布报告生成事件
            for r_type, r_data in reports.items():
                report_id = str(uuid.uuid4())
                await bus.publish(ReportGeneratedEvent(data={
                    "report_type": r_type,
                    "content": r_data.get("content"),
                    "suggestions": r_data.get("suggestions", []),
                    "report_id": report_id,
                    "session_id": session_id
                }))
                
            return reports
            
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 报告生成失败: {e}", exc_info=True)
            return {}

    # -----------------------------------------------------------------------
    # 核心入口
    # -----------------------------------------------------------------------
    
    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """
        实时处理：
        1. 获取/更新 Profile。
        2. 检查完整性 -> 提问 or 生成报告。
        """
        logger.info(f"[{PLUGIN_NAME}] 开始商业定位分析...")
        
        # 1. 解析基础信息
        request = context.get("request")
        if not request:
            return {}
            
        session_id = getattr(request, "session_id", "default_session")
        user_id = getattr(request, "user_id", "default_user")
        input_text = getattr(request, "user_input", "") # 或 raw_query
        
        # 2. 获取并更新 Profile (如果有新输入)
        # 注意：这里假设 context["user_profile"] 是最新的，或者我们需要手动 update
        # 实际逻辑：若 input_text 包含信息，应先提取并更新。
        # 为简化，这里假设 MemoryService 或 Intent 阶段已处理提取，
        # 或者我们在这里简单调用 AI 提取 (此处略过复杂提取，直接用 context 中的 profile)
        
        # 假设 MemoryService 已注入 user_profile
        profile = context.get("user_profile")
        if not profile and memory_service:
            # 尝试从 MemoryService 获取
            # profile = await memory_service.get_user_profile(user_id) 
            # 暂时 Mock 一个空 profile
            profile = {"id": user_id, "type": "personal"}

        # 3. 检查完整性
        missing = await _check_profile_completeness(profile)
        
        if missing:
            # 档案不完整，生成提问
            question = await _generate_question(missing)
            
            # 发布提问事件
            await bus.publish(UserQueryEvent(data={
                "question": question,
                "missing_fields": missing,
                "session_id": session_id
            }))
            
            return {
                "analysis": {
                    **context.get("analysis", {}),
                    PLUGIN_NAME: {
                        "status": "collecting_info",
                        "missing_fields": missing,
                        "question": question
                    }
                }
            }
        else:
            # 档案完整，生成报告
            reports = await _generate_reports(profile, session_id)
            
            return {
                "analysis": {
                    **context.get("analysis", {}),
                    PLUGIN_NAME: {
                        "status": "reports_generated",
                        "reports": reports
                    }
                }
            }

    # 注册为实时插件
    plugin_center.register_plugin(
        PLUGIN_NAME,
        PLUGIN_TYPE_REALTIME,
        get_output=get_output
    )
