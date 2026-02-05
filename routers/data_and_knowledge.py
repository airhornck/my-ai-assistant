"""
数据闭环、案例模板、营销方法论 API：数据接收、案例 CRUD、方法论管理。
"""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from database import AsyncSessionLocal, InteractionHistory
from modules.data_loop.service import DataLoopService
from modules.case_template.service import CaseTemplateService
from modules.methodology.service import MethodologyService


# ---------- 请求体 ----------

class DataFeedbackBody(BaseModel):
    """数据闭环：用户反馈"""
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None
    payload: Optional[dict] = None


class PlatformMetricsBody(BaseModel):
    """数据闭环：平台回流批量"""
    items: List[dict] = Field(..., description="每项含 metric_type，可选 session_id, user_id, value, dimensions")


class CaseCreateBody(BaseModel):
    """案例模板创建"""
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    summary: Optional[str] = None
    scenario_tags: Optional[List[str]] = None
    industry: Optional[str] = None
    goal_type: Optional[str] = None
    source_session_id: Optional[str] = None
    status: str = Field(default="published", pattern="^(draft|published)$")


class CaseScoreBody(BaseModel):
    """案例打分"""
    source: str = Field(..., pattern="^(platform_reflow|user_review|system_auto)$")
    score_value: int = Field(..., ge=1, le=100)
    payload: Optional[dict] = None


class CaseFromSessionBody(BaseModel):
    """将某次会话生成结果标记为案例并写入案例库（积累机制）"""
    session_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    industry: Optional[str] = None
    goal_type: Optional[str] = None
    scenario_tags: Optional[List[str]] = None


class MethodologyWriteBody(BaseModel):
    """方法论文档写入"""
    path: str = Field(..., min_length=1, description="相对 knowledge 的路径，如 methodology/xxx.md")
    content: str = Field(...)


# ---------- 路由 ----------

router = APIRouter()


def _data_loop_service() -> DataLoopService:
    return DataLoopService(session_factory=AsyncSessionLocal)


def _case_service() -> CaseTemplateService:
    return CaseTemplateService(session_factory=AsyncSessionLocal)


def _methodology_service() -> MethodologyService:
    return MethodologyService()


# ----- 数据闭环 -----

@router.post("/data/feedback", status_code=201)
async def api_data_feedback(body: DataFeedbackBody):
    """接收用户反馈事件，写入 feedback_events。"""
    svc = _data_loop_service()
    ev_id = await svc.record_feedback(
        session_id=body.session_id,
        user_id=body.user_id,
        rating=body.rating,
        comment=body.comment,
        payload=body.payload,
    )
    return {"ok": True, "id": ev_id}


@router.post("/data/platform-metrics", status_code=202)
async def api_platform_metrics(body: PlatformMetricsBody):
    """批量接收平台回流指标。"""
    svc = _data_loop_service()
    n = await svc.record_platform_metrics(body.items)
    return {"ok": True, "count": n}


# ----- 案例模板 -----

@router.get("/cases")
async def api_list_cases(
    industry: Optional[str] = None,
    goal_type: Optional[str] = None,
    scenario_tag: Optional[str] = None,
    status: str = "published",
    order_by_score: bool = True,
    page: int = 1,
    page_size: int = 20,
):
    """案例模板列表：按行业/目标/标签筛选，按分排序，分页。"""
    svc = _case_service()
    return await svc.list_cases(
        industry=industry,
        goal_type=goal_type,
        scenario_tag=scenario_tag,
        status=status,
        order_by_score=order_by_score,
        page=page,
        page_size=min(page_size, 100),
    )


@router.get("/cases/{case_id}")
async def api_get_case(case_id: int):
    """案例详情。"""
    svc = _case_service()
    out = await svc.get(case_id)
    if out is None:
        return {"error": "not_found"}, 404
    return out


@router.post("/cases/from-session", status_code=201)
async def api_create_case_from_session(body: CaseFromSessionBody):
    """
    将某次会话的生成结果标记为案例并写入案例库（积累机制）。
    按 session_id 取该会话最近一条交互的 ai_output 作为案例内容，并写入行业/目标/标签等元数据。
    """
    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(InteractionHistory)
            .where(InteractionHistory.session_id == body.session_id)
            .order_by(InteractionHistory.created_at.desc())
            .limit(1)
        )
        row = r.scalar_one_or_none()
    if row is None or not (row.ai_output and row.ai_output.strip()):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": "该会话无可用生成内容"},
        )
    svc = _case_service()
    pk = await svc.create(
        title=body.title,
        content=(row.ai_output or "").strip(),
        summary=(row.ai_output or "")[:500] if row.ai_output else None,
        scenario_tags=body.scenario_tags,
        industry=body.industry,
        goal_type=body.goal_type,
        source_session_id=body.session_id,
        status="published",
    )
    if pk is None:
        return JSONResponse(status_code=500, content={"error": "create_failed"})
    return {"ok": True, "id": pk, "message": "已将会话生成结果沉淀为案例"}


@router.post("/cases", status_code=201)
async def api_create_case(body: CaseCreateBody):
    """创建案例模板。"""
    svc = _case_service()
    pk = await svc.create(
        title=body.title,
        content=body.content,
        summary=body.summary,
        scenario_tags=body.scenario_tags,
        industry=body.industry,
        goal_type=body.goal_type,
        source_session_id=body.source_session_id,
        status=body.status,
    )
    if pk is None:
        return {"error": "create_failed"}, 500
    return {"ok": True, "id": pk}


@router.post("/cases/{case_id}/scores", status_code=201)
async def api_add_case_score(case_id: int, body: CaseScoreBody):
    """为案例添加一条打分（回流/用户/系统自动）。"""
    svc = _case_service()
    ok = await svc.add_score(
        case_id=case_id,
        source=body.source,
        score_value=body.score_value,
        payload=body.payload,
    )
    if not ok:
        return {"error": "add_score_failed"}, 500
    return {"ok": True}


@router.put("/cases/{case_id}")
async def api_update_case(case_id: int, body: dict):
    """更新案例部分字段。"""
    svc = _case_service()
    ok = await svc.update(case_id, **body)
    if not ok:
        return {"error": "not_found_or_failed"}, 404
    return {"ok": True}


@router.delete("/cases/{case_id}")
async def api_delete_case(case_id: int):
    """删除案例。"""
    svc = _case_service()
    ok = await svc.delete(case_id)
    if not ok:
        return {"error": "not_found"}, 404
    return {"ok": True}


# ----- 营销方法论 -----

@router.get("/methodology")
async def api_list_methodology():
    """方法论文档列表。"""
    svc = _methodology_service()
    return {"items": svc.list_docs()}


@router.get("/methodology/doc")
async def api_get_methodology(path: str):
    """读取方法论文档内容。path 为相对 knowledge 的路径，如 methodology/xxx.md。"""
    svc = _methodology_service()
    content = svc.get_content(path)
    if content is None:
        return {"error": "not_found"}, 404
    return {"path": path, "content": content}


@router.put("/methodology/doc")
async def api_put_methodology(body: MethodologyWriteBody):
    """创建或更新方法论文档。"""
    svc = _methodology_service()
    ok = svc.create_or_update(body.path, body.content)
    if not ok:
        return {"error": "write_failed"}, 500
    return {"ok": True, "path": body.path}


@router.delete("/methodology/doc")
async def api_delete_methodology(path: str):
    """删除方法论文档。path 为相对 knowledge 的路径。"""
    svc = _methodology_service()
    ok = svc.delete(path)
    if not ok:
        return {"error": "not_found"}, 404
    return {"ok": True}
