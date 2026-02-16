"""
内容定位插件（分析脑级插件）：
负责用户人设分析、账号四件套生成（昵称/简介/头像/布局）、内容方向推荐及差异化策略。

核心功能：
1. 人设分析 (Persona Analysis): 调用 AI 分析 UserProfile。
2. 四件套生成 (Four-Piece Set):
   - 昵称: 模版 + AI 创意。
   - 简介: 触发 WebSearchEvent 获取竞品信息 + AI 组合。
   - 头像: 企业触发 WebSearchEvent / 个人触发 ImageGenerationEvent。
   - 布局: 平台固定模版。
3. 内容方向推荐 (Content Direction): 基于人设匹配预定义方向。
4. 差异化策略 (Differentiation): AI 分析竞品差异。
"""
from __future__ import annotations

import logging
import json
import random
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME
from core.plugin_bus import get_plugin_bus, WebSearchEvent, ImageGenerationEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
PLUGIN_NAME = "content_positioning"

# 预定义内容方向库
CONTENT_DIRECTIONS = {
    "expert": [
        {"name": "痛点解决", "desc": "针对行业/用户痛点提供专业解决方案"},
        {"name": "认知差科普", "desc": "纠正大众常见误区，建立专业权威"},
        {"name": "SOP拆解", "desc": "将复杂流程标准化、步骤化拆解"},
    ],
    "educator": [
        {"name": "课本巩固", "desc": "紧贴教材知识点进行复习与拓展"},
        {"name": "错题分析", "desc": "精讲典型错题，分析易错原因"},
        {"name": "学习方法", "desc": "分享高效记忆、笔记等学习技巧"},
    ],
    "vlogger": [
        {"name": "沉浸式体验", "desc": "第一视角展示生活/工作场景"},
        {"name": "好物测评", "desc": "真实使用体验分享与优缺点分析"},
        {"name": "Vlog记录", "desc": "碎片化生活记录，展示个人魅力"},
    ],
    "general": [
        {"name": "热点跟进", "desc": "结合时事热点发表观点"},
        {"name": "工具推荐", "desc": "分享提升效率的工具/软件"},
    ]
}

# 平台布局模版
LAYOUT_TEMPLATES = {
    "xiaohongshu": "3:4 竖屏封面，标题醒目（不超过 20 字），正文 '总-分-总' 结构，末尾带标签",
    "douyin": "9:16 全屏竖屏，前 3 秒黄金完播点，背景音乐卡点",
    "bilibili": "16:9 横屏中长视频，封面包含关键信息，内容注重逻辑深度与弹幕互动",
    "channels": "9:16 竖屏，注重社交属性与转发价值，引导关注",
}

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """
    注册内容定位插件。
    """
    ai_service = config.get("ai_service")
    memory_service = config.get("memory_service")
    bus = get_plugin_bus()

    # -----------------------------------------------------------------------
    # 内部辅助函数
    # -----------------------------------------------------------------------
    
    async def _analyze_persona(profile: Dict[str, Any]) -> Dict[str, Any]:
        """调用 fast_model 分析人设。"""
        if not ai_service:
            return {}
        
        llm = ai_service.router.fast_model
        prompt = f"""
请根据以下用户信息，分析其人设定位：
{json.dumps(profile, ensure_ascii=False, indent=2)}

请输出 JSON 格式：
{{
    "tags": ["标签1", "标签2"],
    "tone": "调性描述（如：专业严谨、幽默风趣）",
    "keywords": ["关键词1", "关键词2"],
    "persona_type": "expert/educator/vlogger/general (选一个最匹配的)"
}}
"""
        try:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            return json.loads(text.strip())
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 人设分析失败: {e}")
            return {"persona_type": "general", "tags": [], "tone": "通用", "keywords": []}

    async def _generate_nicknames(profile: Dict[str, Any], persona: Dict[str, Any]) -> List[str]:
        """生成昵称候选。"""
        user_type = profile.get("type", "personal") # enterprise / personal
        industry = profile.get("industry", "通用")
        
        # 固定模版
        templates = []
        if user_type == "enterprise":
            brand = profile.get("brand_name", "")
            templates = [f"{brand}官方", f"{brand} {industry}", f"{brand}小助手"]
        else:
            name = profile.get("name", "小A")
            role = persona.get("tags", ["博主"])[0]
            templates = [f"{name}的{industry}笔记", f"{role}{name}", f"{name}Talk"]
            
        # AI 创意
        if ai_service:
            llm = ai_service.router.powerful_model
            prompt = f"""
为一位 {industry} 领域的 {user_type} 用户设计 3 个有创意的小红书/抖音昵称。
人设标签：{', '.join(persona.get('tags', []))}
调性：{persona.get('tone', '')}
现有信息：{json.dumps(profile, ensure_ascii=False)}

请直接输出 3 个昵称，用逗号分隔，不要其他废话。
"""
            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                ai_names = [n.strip() for n in response.content.split(",")]
                return templates[:1] + ai_names[:3] # 混合
            except Exception:
                pass
        
        return templates

    async def _generate_bio_and_trigger_search(profile: Dict[str, Any], persona: Dict[str, Any]) -> str:
        """生成简介，并触发竞品搜索。"""
        # 1. 触发搜索 (异步)
        brand = profile.get("brand_name") or profile.get("name") or "行业标杆"
        industry = profile.get("industry", "")
        query = f"{industry} {brand} 竞品 简介"
        
        await bus.publish(WebSearchEvent(data={
            "query": query,
            "intent": "competitor_bio_analysis",
            "context_id": profile.get("id", "unknown")
        }))
        
        # 2. 生成简介 (暂用 AI 模版，未等待搜索结果)
        # 模版：品牌口号 + 身份说明 + 价值展示 + 客户例证
        if ai_service:
            llm = ai_service.router.powerful_model
            prompt = f"""
请为以下用户生成一段社交媒体简介（Bio）。
要求包含：
1. 品牌口号/Slogan
2. 身份说明（我是谁）
3. 价值展示（能提供什么）
4. 客户例证/背书（如有）

用户信息：{json.dumps(profile, ensure_ascii=False)}
人设：{json.dumps(persona, ensure_ascii=False)}

请输出一段 100 字以内的简介。
"""
            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)])
                bio = response.content.strip()
                # 简单截断 (Mock trim_text)
                return bio[:100] + "..." if len(bio) > 100 else bio
            except Exception:
                pass
        return "专注分享行业干货，关注我，一起成长！"

    async def _handle_avatar(profile: Dict[str, Any]) -> str:
        """处理头像逻辑。"""
        user_type = profile.get("type", "personal")
        
        if user_type == "enterprise":
            # 触发搜索企业 Logo/形象
            await bus.publish(WebSearchEvent(data={
                "query": f"{profile.get('brand_name', '')} logo 高清",
                "intent": "enterprise_avatar_search"
            }))
            return "建议使用品牌 Logo（已触发搜索，请稍后查看素材库）"
        else:
            # 个人：触发文生图
            style = profile.get("preferred_style", "漫画") # 真实/漫画/古风
            desc = profile.get("avatar_desc", "专业职场人")
            
            prompt = f"A {style} style avatar of {desc}, high quality, social media profile picture"
            
            await bus.publish(ImageGenerationEvent(data={
                "prompt": prompt,
                "style": style,
                "context_id": profile.get("id", "unknown")
            }))
            return f"正在为您生成【{style}】风格的头像，请稍候..."

    # -----------------------------------------------------------------------
    # 核心入口
    # -----------------------------------------------------------------------
    
    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """实时生成内容定位方案。"""
        logger.info(f"[{PLUGIN_NAME}] 开始执行内容定位分析...")
        
        # 1. 获取 UserProfile
        # 假设 context 中包含 'user_profile' (由 MemoryService 注入) 或从 'request' 解析
        user_profile = context.get("user_profile")
        if not user_profile and context.get("request"):
            # 降级：从 request 临时构建
            req = context["request"]
            user_profile = {
                "name": getattr(req, "user_name", "User"),
                "brand_name": getattr(req, "brand_name", ""),
                "industry": getattr(req, "industry", "通用"),
                "type": getattr(req, "user_type", "personal"), # enterprise / personal
                "preferred_style": getattr(req, "style", "漫画")
            }
            
        if not user_profile:
            return {}

        # 2. 人设分析
        persona = await _analyze_persona(user_profile)
        
        # 3. 四件套生成
        nicknames = await _generate_nicknames(user_profile, persona)
        bio = await _generate_bio_and_trigger_search(user_profile, persona)
        avatar_status = await _handle_avatar(user_profile)
        
        # 布局推荐
        platform = context.get("platform", "xiaohongshu")
        layout = LAYOUT_TEMPLATES.get(platform, LAYOUT_TEMPLATES["xiaohongshu"])
        
        # 4. 内容方向推荐
        p_type = persona.get("persona_type", "general")
        directions = CONTENT_DIRECTIONS.get(p_type, CONTENT_DIRECTIONS["general"])
        # 随机选 3 个或全部
        selected_directions = random.sample(directions, min(len(directions), 3))
        
        # 5. 差异化策略 (简单版，因缺乏实时竞品数据，使用通用建议)
        differentiation = "建议采用差异化视觉风格，拍摄视角尝试第一人称沉浸式，叙事风格保持真诚与专业并重。"
        if ai_service:
             # 如果有竞品数据 (context.get('competitors'))，可在此增强
             pass

        # 6. 更新 UserProfile (模拟)
        if memory_service:
            # TODO: 调用 memory_service.update_profile(...)
            pass

        result = {
            "persona": persona,
            "four_piece_set": {
                "nicknames": nicknames,
                "bio": bio,
                "avatar_status": avatar_status,
                "layout_suggestion": layout
            },
            "content_directions": selected_directions,
            "differentiation_strategy": differentiation
        }
        
        return {
            "analysis": {
                **context.get("analysis", {}),
                PLUGIN_NAME: result
            }
        }

    # 注册为实时插件
    plugin_center.register_plugin(
        PLUGIN_NAME,
        PLUGIN_TYPE_REALTIME,
        get_output=get_output
    )
