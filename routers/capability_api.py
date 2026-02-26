"""
Lumina 四模块能力接口：内容方向榜单、案例库、内容定位矩阵、每周决策快照。
统一前缀：/api/v1/capabilities
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from core.deps import get_ai_service_for_router
from database import AsyncSessionLocal
from modules.case_template.service import CaseTemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capabilities", tags=["能力接口（Lumina 四模块）"])


class _MinimalRequest:
    """供插件 get_output 使用的最小请求体（仅含 getattr 可读属性）。"""
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


# ----- 1. 已过滤的内容方向榜单 -----
@router.get(
    "/content-direction-ranking",
    summary="内容方向榜单",
    description="基于画像与热点，返回已过滤排序的内容方向（适配度、热度、风险、角度建议、标题模板）。对应 Lumina「已过滤的内容方向榜单」。",
)
async def get_content_direction_ranking(
    user_id: Optional[str] = Query(None, description="用户 ID，用于画像"),
    platform: Optional[str] = Query(None, description="平台：xiaohongshu/douyin/bilibili/acfun"),
    ai: Any = Depends(get_ai_service_for_router),
) -> JSONResponse:
    """优先调用 content_direction_ranking 插件；无结果时回退到 topic_selection。"""
    try:
        center = getattr(ai, "_analysis_plugin_center", None)
        if not center:
            return JSONResponse(
                content={"success": False, "error": "分析脑插件中心未就绪"},
                status_code=503,
            )
        request = _MinimalRequest(
            brand_name="",
            product_desc="",
            topic=platform or "通用",
            user_id=user_id or "",
        )
        context = {
            "request": request,
            "preference_context": f"user_id={user_id or 'anonymous'}" if user_id else "",
            "platform": platform or "xiaohongshu",
        }
        # 优先使用 content_direction_ranking 插件（含适配度/风险/角度/标题模板）
        out = await center.get_output("content_direction_ranking", context)
        inner = (out.get("analysis") or {}).get("content_direction_ranking") or {}
        items = inner.get("items") if isinstance(inner.get("items"), list) else []
        source = "content_direction_ranking"
        if not items:
            out = await center.get_output("topic_selection", context)
            raw = (out.get("analysis") or {}).get("topic_selection")
            suggestions = raw if isinstance(raw, list) else []
            items = []
            for i, s in enumerate((suggestions or [])[:15]):
                if isinstance(s, dict):
                    items.append({
                        "rank": i + 1,
                        "title_suggestion": s.get("title_suggestion") or s.get("title", ""),
                        "core_angle": s.get("core_angle") or s.get("angle", ""),
                        "content_outline": s.get("content_outline", ""),
                        "reason": s.get("reason", ""),
                        "adaptation_score": None,
                        "heat_trend": None,
                        "risk_level": None,
                        "angles": [],
                        "title_templates": [],
                    })
            source = "topic_selection"
        return JSONResponse(
            content={"success": True, "data": {"items": items, "platform": inner.get("platform")}, "source": source},
            status_code=200,
        )
    except Exception as e:
        logger.warning("content-direction-ranking 失败: %s", e, exc_info=True)
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500,
        )


# ----- 2. 定位决策案例库 -----
@router.get(
    "/case-library",
    summary="定位决策案例库",
    description="案例列表，支持行业/阶段筛选；对应 Lumina「定位决策案例库」。与 /api/v1/cases 数据源一致，可扩展前后对比、决策规则字段。",
)
async def get_case_library(
    industry: Optional[str] = Query(None),
    goal_type: Optional[str] = Query(None),
    scenario_tag: Optional[str] = Query(None),
    status: str = Query("published", description="draft | published"),
    order_by_score: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """委托 CaseTemplateService，返回案例列表。"""
    try:
        svc = CaseTemplateService(session_factory=AsyncSessionLocal)
        result = await svc.list_cases(
            industry=industry,
            goal_type=goal_type,
            scenario_tag=scenario_tag,
            status=status,
            order_by_score=order_by_score,
            page=page,
            page_size=page_size,
        )
        return JSONResponse(
            content={"success": True, "data": result},
            status_code=200,
        )
    except Exception as e:
        logger.warning("case-library 失败: %s", e, exc_info=True)
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500,
        )


# ----- 3. 内容定位矩阵 -----
@router.get(
    "/content-positioning-matrix",
    summary="内容定位矩阵",
    description="3x4 矩阵（优先级×阶段）及每格边界与建议；对应 Lumina「内容定位矩阵」。",
)
async def get_content_positioning_matrix(
    user_id: Optional[str] = Query(None),
    brand_name: Optional[str] = Query(None),
    product_desc: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    ai: Any = Depends(get_ai_service_for_router),
) -> JSONResponse:
    """调用 content_positioning 插件，将内容方向整理为矩阵结构。"""
    try:
        center = getattr(ai, "_analysis_plugin_center", None)
        if not center:
            return JSONResponse(
                content={"success": False, "error": "分析脑插件中心未就绪"},
                status_code=503,
            )
        profile = {
            "brand_name": brand_name or "",
            "product_desc": product_desc or "",
            "industry": industry or "通用",
            "type": "personal",
            "name": "用户",
        }
        request = _MinimalRequest(
            brand_name=brand_name or "",
            product_desc=product_desc or "",
            topic="",
            user_id=user_id or "",
        )
        context = {"request": request, "user_profile": profile}
        out = await center.get_output("content_positioning", context)
        # 插件返回 analysis.content_positioning: { persona, four_piece_set, content_directions, position_matrix, ... }
        inner = (out.get("analysis") or {}).get("content_positioning") or out
        persona = inner.get("persona") or {}
        directions = inner.get("content_directions") or []
        # 优先使用插件输出的 3x4 矩阵；若无则按原逻辑构建
        matrix = inner.get("position_matrix") if isinstance(inner.get("position_matrix"), list) else None
        if not matrix:
            priority_labels = ["高优先级", "中优先级", "低优先级"]
            stage_labels = ["起步", "成长", "变现"]
            matrix = []
            for pi, pr in enumerate(priority_labels):
                for si, st in enumerate(stage_labels):
                    idx = pi * 3 + si
                    rec = (directions[idx] if idx < len(directions) else {}) if isinstance(directions, list) else {}
                    if isinstance(rec, dict):
                        matrix.append({
                            "priority": pr,
                            "stage": st,
                            "boundary": rec.get("desc") or rec.get("name") or "",
                            "suggestion": rec.get("suggestion", ""),
                            "example": rec.get("example", ""),
                        })
                    else:
                        matrix.append({"priority": pr, "stage": st, "boundary": "", "suggestion": "", "example": ""})
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "matrix": matrix,
                    "persona": persona,
                    "raw_directions": directions,
                },
                "source": "content_positioning",
            },
            status_code=200,
        )
    except Exception as e:
        logger.warning("content-positioning-matrix 失败: %s", e, exc_info=True)
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500,
        )


# ----- 4. 每周决策快照 -----
@router.get(
    "/weekly-decision-snapshot",
    summary="每周决策快照",
    description="当前阶段、最大风险、优先级建议、禁区及历史快照；对应 Lumina「每周决策快照」。",
)
async def get_weekly_decision_snapshot(
    user_id: Optional[str] = Query(None),
    ai: Any = Depends(get_ai_service_for_router),
) -> JSONResponse:
    """先聚合 account_diagnosis、content_positioning，再调用 weekly_decision_snapshot 插件。"""
    try:
        center = getattr(ai, "_analysis_plugin_center", None)
        if not center:
            return JSONResponse(
                content={"success": False, "error": "分析脑插件中心未就绪"},
                status_code=503,
            )
        request = _MinimalRequest(brand_name="", product_desc="", topic="", user_id=user_id or "")
        ctx = {"request": request, "analysis": {}}
        # 先拉取诊断与内容定位，供 weekly_decision_snapshot 聚合
        try:
            acc_out = await center.get_output("account_diagnosis", ctx)
            if isinstance(acc_out, dict) and acc_out.get("analysis"):
                ctx["analysis"].update(acc_out["analysis"])
        except Exception as e:
            logger.debug("weekly-decision-snapshot 前置 account_diagnosis 失败: %s", e)
        try:
            pos_out = await center.get_output("content_positioning", ctx)
            if isinstance(pos_out, dict) and pos_out.get("analysis"):
                ctx["analysis"].update(pos_out["analysis"])
        except Exception as e:
            logger.debug("weekly-decision-snapshot 前置 content_positioning 失败: %s", e)
        out = await center.get_output("weekly_decision_snapshot", ctx)
        snapshot = (out.get("analysis") or {}).get("weekly_decision_snapshot") or {}
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "stage": snapshot.get("stage", "起步"),
                    "max_risk": snapshot.get("max_risk", ""),
                    "priorities": snapshot.get("priorities", []),
                    "forbidden": snapshot.get("forbidden", []),
                    "weekly_focus": snapshot.get("weekly_focus", ""),
                    "history": snapshot.get("history", []),
                    "snapshot_time": snapshot.get("snapshot_time", ""),
                },
                "source": "weekly_decision_snapshot",
            },
            status_code=200,
        )
    except Exception as e:
        logger.warning("weekly-decision-snapshot 失败: %s", e, exc_info=True)
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500,
        )
