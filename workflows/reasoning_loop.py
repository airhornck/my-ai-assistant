"""
循环推理节点：实现 ReAct 风格的循环推理，支持意图纠正和上下文累积。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

REASONING_LOOP_SYSTEM = """你是推理循环控制器。你的任务是：
1. 判断当前执行结果是否满足用户意图
2. 如果需要，继续执行下一步或重新规划
3. 如果意图已满足，结束循环

判断规则：
- 如果生成了内容（generate步骤完成），检查内容是否满足用户意图
- 如果是闲聊意图，直接结束
- 如果需要更多信息，指示需要执行的步骤

输出JSON格式：
{
    "should_continue": true/false,
    "reason": "说明为什么继续或结束",
    "next_action": "继续执行/重新规划/结束",
    "updated_intent": "如果需要纠正意图，在此说明"
}
"""


async def reasoning_loop_node(state: dict) -> dict:
    """
    循环推理节点：
    - 检查当前执行结果
    - 判断是否需要继续循环
    - 支持意图纠正
    
    循环逻辑：
    1. 执行完一步后进入 reasoning_loop
    2. 判断是否需要继续：
       - 意图未完成且有下一步 → 继续
       - 意图未完成但当前步骤失败 → 重新规划
       - 意图已完成 → 结束
    3. 返回决策结果
    """
    base = state
    step_outputs = list(base.get("step_outputs", []))
    current_step = base.get("current_step", 0)
    plan = base.get("plan", [])
    intent = base.get("intent", "free_discussion")
    intent_confidence = base.get("intent_confidence", 0.5)
    
    # 获取上一步的输出
    last_output = step_outputs[-1] if step_outputs else {}
    last_step = last_output.get("step", "")
    
    # 判断是否完成
    is_content_generated = last_step == "generate" and last_output.get("result", {}).get("content_length", 0) > 0
    is_casual_reply = last_step == "casual_reply"
    is_analysis_done = last_step == "analyze"
    
    # 循环计数，防止无限循环
    loop_count = base.get("_loop_count", 0)
    max_loops = 5  # 最多5次循环
    
    should_continue = False
    reason = ""
    next_action = "end"
    
    if loop_count >= max_loops:
        reason = f"达到最大循环次数({max_loops})，强制结束"
        next_action = "end"
    elif intent in ("casual_chat", "free_discussion"):
        if is_casual_reply:
            reason = "闲聊意图已完成"
            next_action = "end"
        else:
            reason = "闲聊意图，执行casual_reply"
            next_action = "continue"
    elif intent in ("generate_content", "strategy_planning"):
        if is_content_generated:
            reason = "内容已生成，检查是否需要评估"
            # 有evaluate步骤就继续，否则结束
            remaining_steps = [s for s in plan[current_step+1:] if s.get("step", "").lower() == "evaluate"]
            if remaining_steps:
                next_action = "continue"
                should_continue = True
            else:
                next_action = "end"
        elif is_analysis_done:
            reason = "分析完成，继续生成"
            next_action = "continue"
            should_continue = True
        else:
            reason = "需要继续执行下一步"
            next_action = "continue"
            should_continue = True
    elif intent == "query_info":
        if is_analysis_done or is_casual_reply:
            reason = "信息已提供，结束"
            next_action = "end"
        else:
            reason = "需要继续检索/分析"
            next_action = "continue"
            should_continue = True
    elif intent == "account_diagnosis":
        if is_analysis_done:
            reason = "诊断完成，结束"
            next_action = "end"
        else:
            reason = "继续诊断"
            next_action = "continue"
            should_continue = True
    else:
        # 默认结束
        reason = f"未知意图({intent})，结束"
        next_action = "end"
    
    logger.info(f"reasoning_loop: loop={loop_count}, intent={intent}, last_step={last_step}, next_action={next_action}, reason={reason}")
    
    return {
        **base,
        "_should_continue": should_continue,
        "_loop_count": loop_count + 1,
        "_reasoning_reason": reason,
        "_next_action": next_action,
    }
