"""
Lumina 四模块能力接口：内容方向榜单、案例库、内容定位矩阵、每周决策快照。
统一前缀：/api/v1/capabilities

实现原则：以 chat 模式与用户交互——根据插件能力所需，先询问用户补充信息；
信息齐全后再调用插件，生成「用户账号的定制内容」，而非通用内容。
响应中 need_clarification=true 时表示需用户补充，前端可展示 message 引导用户回复并再次请求。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from core.deps import get_ai_service_for_router, get_memory_service_for_router
from database import AsyncSessionLocal, get_or_create_user_profile
from domain.memory import MemoryService
from modules.case_template.service import CaseTemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capabilities", tags=["能力接口（Lumina 四模块）"])

# 各能力插件生成「账号定制内容」所需的最小信息；缺失时返回澄清话术，由 chat 收集后再请求
CLARIFICATION_CONFIG = {
    "content_direction_ranking": {
        "required_hint": "平台 + 品牌/行业（或已绑定 user_id 画像）",
        "message": "为生成您的专属内容方向榜单，请补充：① 要投放的平台（如小红书、抖音、B站）；② 品牌名称或所在行业（如美妆、教育）。您也可以先绑定账号，我会根据您的画像来推荐。",
        "missing_fields": ["platform", "brand_or_industry"],
    },
    "case_library": {
        "required_hint": "行业或目标类型（或已绑定 user_id 画像）",
        "message": "为推荐与您最相关的定位决策案例，请补充：您的行业（如教育、美妆）或目标类型（如涨粉、转化）。",
        "missing_fields": ["industry_or_goal"],
    },
    "content_positioning_matrix": {
        "required_hint": "品牌或行业（或已绑定 user_id 画像）",
        "message": "为生成您的专属内容定位矩阵与人设分析，请补充：品牌名称或所在行业（如美妆、教育）。",
        "missing_fields": ["brand_or_industry"],
    },
    "weekly_decision_snapshot": {
        "required_hint": "user_id（已绑定账号）或 品牌+行业",
        "message": "每周决策快照需要关联您的账号或品牌信息。请先绑定账号，或补充品牌名称与行业，以便生成针对您账号的阶段性建议与风险提示。",
        "missing_fields": ["user_or_brand_industry"],
    },
}


class _MinimalRequest:
    """供插件 get_output 使用的最小请求体（仅含 getattr 可读属性）。"""
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


async def _load_user_context(
    user_id: Optional[str],
    memory_svc: Optional[Any],
    *,
    brand_name: str = "",
    product_desc: str = "",
    industry: str = "",
    topic: str = "",
    platform: str = "",
) -> Tuple[Dict[str, Any], str, _MinimalRequest]:
    """
    先了解用户基本情况与需求：从 DB 拉取画像，从 MemoryService 拉取偏好/记忆，与请求参数合并。
    返回 (user_profile 字典, preference_context 字符串, MinimalRequest)。
    """
    profile_dict: Dict[str, Any] = {
        "brand_name": brand_name or "",
        "product_desc": product_desc or "",
        "industry": industry or "通用",
        "type": "personal",
        "name": "用户",
    }
    preference_context = ""

    if user_id and (user_id or "").strip():
        try:
            async with AsyncSessionLocal() as db:
                profile = await get_or_create_user_profile(db, user_id)
                await db.commit()
            # 从数据库画像补全
            profile_dict["brand_name"] = profile_dict["brand_name"] or (profile.brand_name or "")
            profile_dict["product_desc"] = profile_dict["product_desc"] or (getattr(profile, "product_desc", None) or "")
            profile_dict["industry"] = profile_dict["industry"] or (profile.industry or "通用")
            profile_dict["name"] = getattr(profile, "name", None) or "用户"
            if getattr(profile, "preferred_style", None):
                profile_dict["preferred_style"] = profile.preferred_style
            if getattr(profile, "tags", None) and isinstance(profile.tags, list):
                profile_dict["tags"] = profile.tags
        except Exception as e:
            logger.debug("能力接口加载用户画像失败: %s", e)

        if memory_svc:
            try:
                mem = await memory_svc.get_memory_for_analyze(
                    user_id=user_id,
                    brand_name=profile_dict["brand_name"],
                    product_desc=profile_dict["product_desc"],
                    topic=topic or profile_dict.get("industry", ""),
                )
                preference_context = (mem.get("preference_context") or "").strip()
            except Exception as e:
                logger.debug("能力接口获取记忆上下文失败: %s", e)
            if not preference_context:
                try:
                    preference_context = (await memory_svc.get_user_summary(user_id)) or ""
                except Exception:
                    pass

    if not preference_context and (profile_dict.get("brand_name") or profile_dict.get("industry")):
        parts = []
        if profile_dict.get("brand_name"):
            parts.append(f"品牌：{profile_dict['brand_name']}")
        if profile_dict.get("industry"):
            parts.append(f"行业：{profile_dict['industry']}")
        if profile_dict.get("product_desc"):
            parts.append(f"产品/描述：{profile_dict['product_desc']}")
        preference_context = "；".join(parts)

    req = _MinimalRequest(
        brand_name=profile_dict["brand_name"],
        product_desc=profile_dict["product_desc"],
        topic=topic or platform or profile_dict.get("industry", "通用"),
        user_id=user_id or "",
    )
    return profile_dict, preference_context or "未提供用户画像，按通用场景输出。", req


def _need_clarification(
    capability: str,
    profile_dict: Dict[str, Any],
    *,
    platform: str = "",
    industry: str = "",
    brand_name: str = "",
    product_desc: str = "",
    goal_type: str = "",
    user_id: str = "",
) -> Tuple[bool, str, List[str]]:
    """
    判断当前是否具备生成「账号定制内容」所需信息；若不足则返回需向用户澄清的文案与缺失项。
    返回 (是否可继续执行, 澄清话术, 缺失字段列表)。
    """
    has_profile = bool(
        (profile_dict.get("brand_name") or "").strip()
        or (profile_dict.get("industry") or "").strip()
        or (profile_dict.get("product_desc") or "").strip()
    )
    has_user = bool((user_id or "").strip())

    if capability == "content_direction_ranking":
        has_platform = bool((platform or "").strip())
        if has_platform and (has_profile or has_user):
            return False, "", []
        if not has_platform or not (has_profile or has_user):
            cfg = CLARIFICATION_CONFIG["content_direction_ranking"]
            return True, cfg["message"], cfg["missing_fields"]

    if capability == "case_library":
        has_industry_or_goal = bool((industry or "").strip()) or bool((goal_type or "").strip()) or has_profile
        if has_industry_or_goal or has_user:
            return False, "", []
        cfg = CLARIFICATION_CONFIG["case_library"]
        return True, cfg["message"], cfg["missing_fields"]

    if capability == "content_positioning_matrix":
        has_brand_or_industry = (
            bool((brand_name or "").strip())
            or bool((industry or "").strip())
            or bool((product_desc or "").strip())
            or has_profile
        )
        if has_brand_or_industry or has_user:
            return False, "", []
        cfg = CLARIFICATION_CONFIG["content_positioning_matrix"]
        return True, cfg["message"], cfg["missing_fields"]

    if capability == "weekly_decision_snapshot":
        has_brand_industry = (
            bool((brand_name or "").strip())
            or (profile_dict.get("industry") or "").strip()
            or (profile_dict.get("brand_name") or "").strip()
        )
        if has_user or has_brand_industry:
            return False, "", []
        cfg = CLARIFICATION_CONFIG["weekly_decision_snapshot"]
        return True, cfg["message"], cfg["missing_fields"]

    return False, "", []


def _clarification_response(message: str, missing_fields: List[str], capability: str) -> JSONResponse:
    """统一返回「需用户补充信息」的响应，供 chat 展示并引导用户回复后再次请求。"""
    return JSONResponse(
        content={
            "success": True,
            "need_clarification": True,
            "capability": capability,
            "message": message,
            "missing_fields": missing_fields,
            "data": None,
            "hint": "请在对话中补充上述信息后再次请求本能力，将为您生成账号定制内容。",
        },
        status_code=200,
    )


async def _run_capability_fixed_plan(
    template_id: str,
    *,
    profile_dict: Dict[str, Any],
    preference_context: str,
    request: _MinimalRequest,
    center: Any,
    case_service: Any = None,
    platform: str = "",
    industry: str = "",
    goal_type: Optional[str] = None,
    scenario_tag: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    status: str = "published",
    order_by_score: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    执行能力接口固定 Plan（与 plans 中 CAPABILITY_TEMPLATE_* 对应）。
    返回 (step_outputs, final_context)，供各接口从最后一步或 context.analysis 组装响应。
    """
    from plans import get_plan

    plan = get_plan(template_id)
    if not plan:
        return [], {}
    context: Dict[str, Any] = {
        "request": request,
        "user_profile": profile_dict,
        "preference_context": preference_context,
        "analysis": {},
    }
    # 可选：由调用方注入 platform 等（如 content_direction_ranking 需要）
    context["platform"] = (platform or "xiaohongshu").strip() or "xiaohongshu"
    step_outputs: List[Dict[str, Any]] = []
    for step_config in plan:
        step_name = (step_config.get("step") or "").lower()
        if step_name == "memory_query":
            step_outputs.append({
                "step": "memory_query",
                "reason": step_config.get("reason", ""),
                "result": {"has_memory": bool(preference_context), "memory_context": preference_context},
            })
            continue
        if step_name == "analyze":
            plugins = step_config.get("plugins") or []
            if isinstance(plugins, str):
                plugins = [plugins] if plugins.strip() else []
            get_output = getattr(center, "get_output", None) if center else None
            if not callable(get_output):
                step_outputs.append({"step": "analyze", "reason": step_config.get("reason", ""), "result": {}})
                continue
            for plugin_name in plugins:
                try:
                    out = await get_output(plugin_name, context)
                    if isinstance(out, dict) and out.get("analysis"):
                        context["analysis"] = {**context.get("analysis", {}), **out["analysis"]}
                except Exception as e:
                    logger.debug("capability plan analyze %s 失败: %s", plugin_name, e)
            step_outputs.append({
                "step": "analyze",
                "reason": step_config.get("reason", ""),
                "result": dict(context.get("analysis", {})),
            })
            continue
        if step_name == "case_library":
            if case_service is None:
                step_outputs.append({
                    "step": "case_library",
                    "reason": step_config.get("reason", ""),
                    "result": {"items": [], "total": 0, "error": "case_service not available"},
                })
                continue
            industry_resolved = (industry or "").strip() or (profile_dict.get("industry") or "通用").strip()
            try:
                result = await case_service.list_cases(
                    industry=industry_resolved or "通用",
                    goal_type=goal_type,
                    scenario_tag=scenario_tag,
                    status=status,
                    order_by_score=order_by_score,
                    page=page,
                    page_size=page_size,
                )
            except Exception as e:
                logger.warning("case_library list_cases 失败: %s", e)
                result = {"items": [], "total": 0}
            step_outputs.append({
                "step": "case_library",
                "reason": step_config.get("reason", ""),
                "result": result if isinstance(result, dict) else {"items": [], "total": 0},
            })
            continue
        step_outputs.append({"step": step_name, "reason": step_config.get("reason", ""), "result": {}})
    return step_outputs, context


# ----- 1. 已过滤的内容方向榜单（固定 Plan 执行）-----
@router.get(
    "/content-direction-ranking",
    summary="内容方向榜单",
    description="Chat 模式：缺平台/品牌或行业时先返回 need_clarification；信息齐全后按固定 Plan（memory_query → analyze content_direction_ranking）执行。",
)
async def get_content_direction_ranking(
    user_id: Optional[str] = Query(None, description="用户 ID，用于加载画像与记忆"),
    platform: Optional[str] = Query(None, description="平台：xiaohongshu/douyin/bilibili/acfun"),
    ai: Any = Depends(get_ai_service_for_router),
    memory_svc: Optional[Any] = Depends(get_memory_service_for_router),
) -> JSONResponse:
    """按固定 Plan 执行：memory_query → analyze(content_direction_ranking)；无结果时回退 topic_selection。"""
    from plans import CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING

    try:
        center = getattr(ai, "_analysis_plugin_center", None)
        if not center:
            return JSONResponse(
                content={"success": False, "error": "分析脑插件中心未就绪"},
                status_code=503,
            )
        if memory_svc is None and getattr(ai, "_cache", None):
            memory_svc = MemoryService(cache=ai._cache)
        profile_dict, preference_context, request = await _load_user_context(
            user_id, memory_svc, platform=platform or "",
        )
        need, msg, missing = _need_clarification(
            "content_direction_ranking",
            profile_dict,
            platform=platform or "",
            user_id=user_id or "",
        )
        if need:
            return _clarification_response(msg, missing, "content_direction_ranking")
        step_outputs, ctx = await _run_capability_fixed_plan(
            CAPABILITY_TEMPLATE_CONTENT_DIRECTION_RANKING,
            profile_dict=profile_dict,
            preference_context=preference_context,
            request=request,
            center=center,
            platform=platform or "xiaohongshu",
        )
        inner = (ctx.get("analysis") or {}).get("content_direction_ranking") or {}
        items = inner.get("items") if isinstance(inner.get("items"), list) else []
        source = "content_direction_ranking"
        if not items:
            fallback_ctx = {**ctx, "platform": (platform or "xiaohongshu").strip() or "xiaohongshu"}
            out = await center.get_output("topic_selection", fallback_ctx)
            raw = (out.get("analysis") or {}).get("topic_selection")
            suggestions = raw if isinstance(raw, list) else []
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
            content={
                "success": True,
                "need_clarification": False,
                "data": {"items": items, "platform": inner.get("platform")},
                "source": source,
            },
            status_code=200,
        )
    except Exception as e:
        logger.warning("content-direction-ranking 失败: %s", e, exc_info=True)
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500,
        )


# ----- 2. 定位决策案例库（固定 Plan 执行）-----
@router.get(
    "/case-library",
    summary="定位决策案例库",
    description="Chat 模式：缺行业或目标时先返回 need_clarification；信息齐全后按固定 Plan（memory_query → case_library）执行。",
)
async def get_case_library(
    user_id: Optional[str] = Query(None, description="用户 ID，用于补全行业等筛选默认值"),
    industry: Optional[str] = Query(None),
    goal_type: Optional[str] = Query(None),
    scenario_tag: Optional[str] = Query(None),
    status: str = Query("published", description="draft | published"),
    order_by_score: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    memory_svc: Optional[Any] = Depends(get_memory_service_for_router),
) -> JSONResponse:
    """按固定 Plan 执行：memory_query → case_library（CaseTemplateService.list_cases）。"""
    from plans import CAPABILITY_TEMPLATE_CASE_LIBRARY

    try:
        profile_dict, preference_context, request = await _load_user_context(
            user_id, memory_svc, industry=industry or "",
        )
        need, msg, missing = _need_clarification(
            "case_library",
            profile_dict,
            industry=industry or "",
            goal_type=goal_type or "",
            user_id=user_id or "",
        )
        if need:
            return _clarification_response(msg, missing, "case_library")
        case_svc = CaseTemplateService(session_factory=AsyncSessionLocal)
        # case_library 固定 Plan 仅含 memory_query + case_library，无需 analysis center
        step_outputs, _ = await _run_capability_fixed_plan(
            CAPABILITY_TEMPLATE_CASE_LIBRARY,
            profile_dict=profile_dict,
            preference_context=preference_context,
            request=request,
            center=None,
            case_service=case_svc,
            industry=industry or "",
            goal_type=goal_type,
            scenario_tag=scenario_tag,
            status=status,
            order_by_score=order_by_score,
            page=page,
            page_size=page_size,
        )
        result = step_outputs[-1].get("result", {}) if step_outputs else {}
        if not isinstance(result, dict):
            result = {"items": [], "total": 0}
        return JSONResponse(
            content={
                "success": True,
                "need_clarification": False,
                "data": result,
            },
            status_code=200,
        )
    except Exception as e:
        logger.warning("case-library 失败: %s", e, exc_info=True)
        return JSONResponse(
            content={"success": False, "error": str(e)},
            status_code=500,
        )


# ----- 3. 内容定位矩阵（固定 Plan 执行）-----
@router.get(
    "/content-positioning-matrix",
    summary="内容定位矩阵",
    description="Chat 模式：缺品牌或行业时先返回 need_clarification；信息齐全后按固定 Plan（memory_query → analyze content_positioning）执行。",
)
async def get_content_positioning_matrix(
    user_id: Optional[str] = Query(None, description="用户 ID，用于加载画像"),
    brand_name: Optional[str] = Query(None),
    product_desc: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    ai: Any = Depends(get_ai_service_for_router),
    memory_svc: Optional[Any] = Depends(get_memory_service_for_router),
) -> JSONResponse:
    """按固定 Plan 执行：memory_query → analyze(content_positioning)。"""
    from plans import CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX

    try:
        center = getattr(ai, "_analysis_plugin_center", None)
        if not center:
            return JSONResponse(
                content={"success": False, "error": "分析脑插件中心未就绪"},
                status_code=503,
            )
        if memory_svc is None and getattr(ai, "_cache", None):
            memory_svc = MemoryService(cache=ai._cache)
        profile_dict, preference_context, request = await _load_user_context(
            user_id, memory_svc,
            brand_name=brand_name or "",
            product_desc=product_desc or "",
            industry=industry or "",
        )
        need, msg, missing = _need_clarification(
            "content_positioning_matrix",
            profile_dict,
            brand_name=brand_name or "",
            industry=industry or "",
            product_desc=product_desc or "",
            user_id=user_id or "",
        )
        if need:
            return _clarification_response(msg, missing, "content_positioning_matrix")
        _, ctx = await _run_capability_fixed_plan(
            CAPABILITY_TEMPLATE_CONTENT_POSITIONING_MATRIX,
            profile_dict=profile_dict,
            preference_context=preference_context,
            request=request,
            center=center,
        )
        inner = (ctx.get("analysis") or {}).get("content_positioning") or {}
        persona = inner.get("persona") or {}
        directions = inner.get("content_directions") or []
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
                "need_clarification": False,
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


# ----- 4. 每周决策快照（固定 Plan 执行）-----
@router.get(
    "/weekly-decision-snapshot",
    summary="每周决策快照",
    description="Chat 模式：缺 user_id 或品牌/行业时先返回 need_clarification；信息齐全后按固定 Plan（memory_query → account_diagnosis → content_positioning → weekly_decision_snapshot）执行。",
)
async def get_weekly_decision_snapshot(
    user_id: Optional[str] = Query(None, description="用户 ID，用于加载画像与记忆"),
    ai: Any = Depends(get_ai_service_for_router),
    memory_svc: Optional[Any] = Depends(get_memory_service_for_router),
) -> JSONResponse:
    """按固定 Plan 执行：memory_query → analyze(account_diagnosis) → analyze(content_positioning) → analyze(weekly_decision_snapshot)。"""
    from plans import CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT

    try:
        center = getattr(ai, "_analysis_plugin_center", None)
        if not center:
            return JSONResponse(
                content={"success": False, "error": "分析脑插件中心未就绪"},
                status_code=503,
            )
        if memory_svc is None and getattr(ai, "_cache", None):
            memory_svc = MemoryService(cache=ai._cache)
        profile_dict, preference_context, request = await _load_user_context(user_id, memory_svc)
        need, msg, missing = _need_clarification(
            "weekly_decision_snapshot",
            profile_dict,
            user_id=user_id or "",
            brand_name=profile_dict.get("brand_name") or "",
        )
        if need:
            return _clarification_response(msg, missing, "weekly_decision_snapshot")
        _, ctx = await _run_capability_fixed_plan(
            CAPABILITY_TEMPLATE_WEEKLY_DECISION_SNAPSHOT,
            profile_dict=profile_dict,
            preference_context=preference_context,
            request=request,
            center=center,
        )
        snapshot = (ctx.get("analysis") or {}).get("weekly_decision_snapshot") or {}
        return JSONResponse(
            content={
                "success": True,
                "need_clarification": False,
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
