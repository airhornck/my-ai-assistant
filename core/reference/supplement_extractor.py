"""
参考材料补充提取：从文档/链接中提取可辅助主推广对象的信息。
将原始参考内容解析为「对会话主题的补充」，避免参考材料中的其他产品喧宾夺主。
"""
from __future__ import annotations

import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

SUPPLEMENT_SYSTEM = """你是参考材料分析专家。用户提供了「主推广对象」和「参考材料」。

你的任务：从参考材料中提取**仅对主推广对象有用的补充信息**，包括：
- 可借鉴的表述风格、写作手法
- 行业通用卖点、消费者关注点（与主对象品类相关的）
- 可引用的数据、趋势（若材料涉及其他品牌，仅提取行业层面信息）

**严格规则**：
1. 主推广对象是唯一主体，参考材料中的其他品牌/产品名称、型号不得出现在输出中
2. 若参考材料主要讲的是与主对象不同的产品（如材料写vivo、主对象是华为），只提取：行业趋势、品类共性卖点、可借鉴的表述风格，绝不输出材料中的产品名
3. 输出应为简洁的补充要点，供文案生成时丰富主推广对象的表述
4. 若无有效补充可提取，输出「（无可补充内容）」"""


async def extract_reference_supplement(
    main_topic: str,
    reference_raw: str,
    llm_client,
) -> str:
    """
    从参考材料中提取对主推广对象的补充信息。
    
    Args:
        main_topic: 主推广对象描述，如「华为新款手机，目标用户18-35岁」
        reference_raw: 文档/链接的原始解析内容
        llm_client: ILLMClient 实例，需有 invoke(messages, task_type=..., complexity=...)
    
    Returns:
        提取出的补充信息，供生成时使用；若失败或无可补充则返回空字符串
    """
    if not reference_raw or not reference_raw.strip():
        return ""
    if not main_topic or not main_topic.strip():
        return ""
    
    main_topic = main_topic.strip()
    reference_raw = reference_raw.strip()
    
    # 限制长度，避免 token 过多
    max_ref = 12000
    if len(reference_raw) > max_ref:
        reference_raw = reference_raw[:max_ref] + "\n...[已截断]"
    
    user_prompt = f"""【主推广对象（必须围绕此）】
{main_topic}

【参考材料（用户提供的文档/链接内容）】
{reference_raw}

请提取对主推广对象有用的补充信息，遵守严格规则。只输出补充要点，不要其他解释。"""
    
    try:
        messages = [SystemMessage(content=SUPPLEMENT_SYSTEM), HumanMessage(content=user_prompt)]
        response = await llm_client.invoke(messages, task_type="planning", complexity="medium")
        text = (response.strip() if isinstance(response, str) else str(response)).strip()
        if not text or "（无可补充内容）" in text or "无可补充" in text:
            return ""
        return text
    except Exception as e:
        logger.warning("参考材料补充提取失败: %s", e, exc_info=True)
        return ""
