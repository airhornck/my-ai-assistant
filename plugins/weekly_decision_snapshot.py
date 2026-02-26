"""
每周决策快照插件（分析脑级插件，对应 Lumina「每周决策快照」）：
输出当前阶段判断、最大风险点、优先级建议、禁区标注、本周重点调整及历史快照。
支持实时 get_output（聚合 context 中已有诊断/定位结果）与可选缓存历史。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

PLUGIN_NAME = "weekly_decision_snapshot"

# 历史快照缓存键前缀（按 user_id 存储最近 N 条）
CACHE_KEY_HISTORY_PREFIX = "weekly_snapshot:history:"
CACHE_KEY_LATEST_PREFIX = "weekly_snapshot:latest:"
MAX_HISTORY = 10


def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    """注册每周决策快照插件（实时）。"""
    cache = config.get("cache")
    ai_service = config.get("ai_service")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        """
        从 context.analysis 聚合 account_diagnosis、content_positioning 等，
        生成阶段、最大风险、优先级、禁区、本周重点；历史从 cache 读取。
        """
        analysis = context.get("analysis") or {}
        request = context.get("request")
        user_id = getattr(request, "user_id", "") if request else ""

        # 1. 阶段判断：来自 content_positioning 的 persona 或默认
        stage = "起步"
        persona = (analysis.get("content_positioning") or {}).get("persona") if isinstance(analysis.get("content_positioning"), dict) else {}
        if isinstance(persona, dict) and persona.get("persona_type"):
            # 简单映射：expert/educator 多为成长/变现，vlogger/general 起步多
            ptype = persona.get("persona_type", "general")
            if ptype in ("expert", "educator"):
                stage = "成长"
            elif ptype == "vlogger":
                stage = "起步"

        # 2. 最大风险与优先级：来自 account_diagnosis
        max_risk = ""
        priorities: List[str] = []
        diag = analysis.get("account_diagnosis") if isinstance(analysis.get("account_diagnosis"), dict) else {}
        if diag:
            summary = diag.get("summary", "")
            issues = diag.get("issues", [])
            suggestions = diag.get("suggestions", [])
            if issues:
                max_risk = issues[0].get("msg", issues[0].get("indicator", "")) if issues else summary or "暂无"
            else:
                max_risk = summary or "暂无明显风险，保持更新节奏即可。"
            for s in (suggestions or [])[:5]:
                if isinstance(s, dict) and s.get("suggestion"):
                    priorities.append(f"[{s.get('priority', '中')}] {s.get('suggestion', '')}")

        # 3. 禁区：固定建议 + 可扩展来自 rate_limit / platform_rules
        forbidden: List[str] = [
            "避免纯搬运、洗稿",
            "避免过度营销与诱导关注",
            "避免违禁词与敏感画面",
        ]

        # 4. 本周重点：用 AI 生成一句或使用模板
        weekly_focus = ""
        if ai_service and (max_risk or priorities):
            try:
                llm = ai_service.router.fast_model
                prompt = f"""根据以下诊断信息，用一句话给出「本周最应优先做的一件事」。
阶段：{stage}
最大风险点：{max_risk}
已有建议（前3条）：{chr(10).join(priorities[:3])}
请只输出一句话，不要序号、不要解释。"""
                from langchain_core.messages import HumanMessage
                res = await llm.ainvoke([HumanMessage(content=prompt)])
                weekly_focus = (res.content or "").strip()[:200]
            except Exception as e:
                logger.debug("weekly_decision_snapshot 本周重点生成失败: %s", e)
        if not weekly_focus:
            weekly_focus = "优先解决当前最大风险点，再按优先级推进内容与转化。"

        # 5. 历史快照：从缓存读取
        history: List[Dict[str, Any]] = []
        if cache and user_id:
            try:
                raw = await cache.get(f"{CACHE_KEY_HISTORY_PREFIX}{user_id}")
                if isinstance(raw, str):
                    history = json.loads(raw)
                elif isinstance(raw, list):
                    history = raw
                history = (history or [])[-MAX_HISTORY:]
            except Exception as e:
                logger.debug("weekly_snapshot 读取历史失败: %s", e)

        snapshot = {
            "stage": stage,
            "max_risk": max_risk,
            "priorities": priorities,
            "forbidden": forbidden,
            "weekly_focus": weekly_focus,
            "history": history,
            "snapshot_time": time.strftime("%Y-%m-%d %H:%M"),
        }

        # 6. 可选：写入本次快照到 cache 作为 latest，并追加到 history
        if cache and user_id:
            try:
                await cache.set(f"{CACHE_KEY_LATEST_PREFIX}{user_id}", json.dumps(snapshot), ttl=604800)  # 7d
                new_history = history + [{"snapshot_time": snapshot["snapshot_time"], "stage": stage, "weekly_focus": weekly_focus}]
                await cache.set(f"{CACHE_KEY_HISTORY_PREFIX}{user_id}", json.dumps(new_history[-MAX_HISTORY:]), ttl=2592000)  # 30d
            except Exception as e:
                logger.debug("weekly_snapshot 写入缓存失败: %s", e)

        return {
            "analysis": {
                **analysis,
                PLUGIN_NAME: snapshot,
            },
        }

    plugin_center.register_plugin(
        PLUGIN_NAME,
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )
