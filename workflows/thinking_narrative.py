"""
思考过程叙述化：将策略脑执行记录转换为 DeepSeek 风格的连贯叙述。
第一人称、解释推理链、说明如何综合信息及使用参考材料。
使用 thinking_narrative 接口（默认 qwen-turbo）以缩短耗时。
"""
from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.api_config import get_model_config

logger = logging.getLogger(__name__)

NARRATIVE_SYSTEM = """你是思考过程撰写专家。根据策略脑的执行记录，撰写一段连贯的、第一人称的思考过程叙述。

要求：
1. 用「我」作为主语，如「我打算…」「根据搜索结果…」「这些信息足够我…」
2. 解释推理链：为什么做这些步骤、如何综合信息、如何得出结论
3. 若有网络检索：说明阅读了多少网页、从哪些来源获得什么信息
4. 若有参考材料（文档/链接）：明确说明用作「补充」「借鉴表述」，主推广对象以用户对话为准，不可喧宾夺主
5. 若有用户偏好标签：在叙述中自然体现「根据您的偏好（如科技数码、简洁文案等）」，让用户感知到个性化
6. 若有后续步骤（如生成B站风格）：回顾上文、说明如何衔接、如何调整
7. 语言自然连贯，避免机械罗列步骤名
8. 输出 200–600 字，不要超长"""


async def generate_thinking_narrative(
    user_input_str: str,
    thinking_logs: list,
    step_outputs: list,
    search_context: str,
    analysis: dict | str,
    llm_client,  # 保留兼容，实际使用 config.thinking_narrative（默认 qwen-turbo）
    effective_tags: list | None = None,
) -> str:
    """
    根据执行记录生成 DeepSeek 风格的思考叙述。
    使用 thinking_narrative 接口（默认 qwen-turbo）以加快响应；若调用失败则返回步骤摘要。
    """
    try:
        data = {}
        if isinstance(user_input_str, str) and user_input_str.strip():
            try:
                data = json.loads(user_input_str)
            except (TypeError, json.JSONDecodeError):
                pass
        
        brand = (data.get("brand_name") or "").strip()
        product = (data.get("product_desc") or "").strip()
        topic = (data.get("topic") or "").strip()
        raw_query = (data.get("raw_query") or "").strip()
        conversation_context = (data.get("conversation_context") or "").strip()
        has_reference = bool((data.get("session_document_context") or "").strip())
        
        steps_desc = []
        for i, entry in enumerate(thinking_logs or []):
            step = entry.get("step", "")
            thought = entry.get("thought", "")
            out = (step_outputs or [])[i] if i < len(step_outputs or []) else {}
            steps_desc.append(f"- {step}: {thought}")
            if out.get("result"):
                steps_desc.append(f"  结果摘要: {str(out['result'])[:150]}")
        
        search_preview = (search_context or "")[:800] + ("..." if len(search_context or "") > 800 else "")
        analysis_preview = ""
        if isinstance(analysis, dict):
            analysis_preview = f"关联度{analysis.get('semantic_score','')}，切入点：{analysis.get('angle','')}"
        elif analysis:
            analysis_preview = str(analysis)[:300]
        
        ctx_hint = ""
        if conversation_context and (not brand or not product):
            ctx_hint = f"\n【近期对话（主推广对象从此提取）】\n{conversation_context[:600]}\n"
        tags_display = ", ".join(effective_tags or []) if (effective_tags or []) else "无"
        user_prompt = f"""【用户目标】
品牌：{brand or "未指定"}
产品：{product or "未指定"}
话题：{topic or raw_query or "推广"}{ctx_hint}
【执行记录】
{chr(10).join(steps_desc)}

【网络检索内容摘要】（若有）
{search_preview or "（无）"}

【分析结果摘要】
{analysis_preview or "（无）"}

【是否有参考材料（文档/链接）】
{"有，用作补充" if has_reference else "无"}

【用户偏好标签】（若有，需在叙述中体现「根据您的偏好（xxx）」）
{tags_display}

请撰写思考过程叙述。"""
        
        messages = [
            SystemMessage(content=NARRATIVE_SYSTEM),
            HumanMessage(content=user_prompt),
        ]
        cfg = get_model_config("thinking_narrative")
        client = ChatOpenAI(
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            temperature=cfg.get("temperature", 0.3),
            max_tokens=cfg.get("max_tokens", 2048),
        )
        response = await client.ainvoke(messages)
        text = (response.content or "").strip() if hasattr(response, "content") else str(response).strip()
        if text and len(text) > 50:
            return text
    except Exception as e:
        logger.warning("思考叙述生成失败: %s", e, exc_info=True)
    
    # 降级：简洁步骤列表
    fallback = []
    for entry in (thinking_logs or []):
        step = entry.get("step", "")
        thought = entry.get("thought", "")
        if step or thought:
            fallback.append(f"- **{step}**: {thought}")
    return "\n".join(fallback) if fallback else "（无详细记录）"
