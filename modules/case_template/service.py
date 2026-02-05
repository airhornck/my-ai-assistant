"""
营销策略案例模板服务：CRUD、多来源打分（回流/用户/系统自动）、按综合分排序与筛选。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import MarketingCaseTemplate, CaseScore

logger = logging.getLogger(__name__)

SOURCE_PLATFORM_REFLOW = "platform_reflow"
SOURCE_USER_REVIEW = "user_review"
SOURCE_SYSTEM_AUTO = "system_auto"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class CaseTemplateService:
    """案例模板的增删改查与打分。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        title: str,
        content: str,
        summary: str | None = None,
        scenario_tags: List[str] | None = None,
        industry: str | None = None,
        goal_type: str | None = None,
        source_session_id: str | None = None,
        status: str = "published",
    ) -> Optional[int]:
        """创建案例模板，返回 id。"""
        async with self._session_factory() as session:
            try:
                row = MarketingCaseTemplate(
                    title=title,
                    summary=summary or "",
                    content=content,
                    scenario_tags=scenario_tags or [],
                    industry=industry,
                    goal_type=goal_type,
                    source_session_id=source_session_id,
                    status=status,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row.id
            except Exception as e:
                logger.warning("CaseTemplateService.create 失败: %s", e)
                await session.rollback()
                return None

    async def get(self, case_id: int) -> Optional[dict]:
        """单条详情，含最近打分。"""
        async with self._session_factory() as session:
            r = await session.execute(
                select(MarketingCaseTemplate).where(MarketingCaseTemplate.id == case_id)
            )
            row = r.scalar_one_or_none()
            if not row:
                return None
            # 最近几条打分
            r2 = await session.execute(
                select(CaseScore)
                .where(CaseScore.case_id == case_id)
                .order_by(CaseScore.created_at.desc())
                .limit(10)
            )
            scores = r2.scalars().all()
            return {
                "id": row.id,
                "title": row.title,
                "summary": row.summary,
                "content": row.content,
                "scenario_tags": row.scenario_tags,
                "industry": row.industry,
                "goal_type": row.goal_type,
                "source_session_id": row.source_session_id,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "scores": [
                    {"source": s.source, "score_value": s.score_value, "created_at": s.created_at.isoformat() if s.created_at else None}
                    for s in scores
                ],
            }

    async def list_cases(
        self,
        industry: str | None = None,
        goal_type: str | None = None,
        scenario_tag: str | None = None,
        status: str = "published",
        order_by_score: bool = True,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        include_content: bool = False,
    ) -> dict:
        """
        列表：支持按行业/目标/标签筛选，按综合分或时间排序，分页。
        综合分：取该案例最近一条打分的 score_value，无打分时排后。
        """
        size = min(max(1, page_size), MAX_PAGE_SIZE)
        offset = (max(1, page) - 1) * size
        async with self._session_factory() as session:
            q = select(MarketingCaseTemplate).where(MarketingCaseTemplate.status == status)
            if industry:
                q = q.where(MarketingCaseTemplate.industry == industry)
            if goal_type:
                q = q.where(MarketingCaseTemplate.goal_type == goal_type)
            if scenario_tag:
                q = q.where(MarketingCaseTemplate.scenario_tags.contains([scenario_tag]))
            q = q.order_by(MarketingCaseTemplate.updated_at.desc())
            count_q = select(func.count()).select_from(MarketingCaseTemplate).where(MarketingCaseTemplate.status == status)
            if industry:
                count_q = count_q.where(MarketingCaseTemplate.industry == industry)
            if goal_type:
                count_q = count_q.where(MarketingCaseTemplate.goal_type == goal_type)
            if scenario_tag:
                count_q = count_q.where(MarketingCaseTemplate.scenario_tags.contains([scenario_tag]))
            total_r = await session.execute(count_q)
            total = total_r.scalar() or 0
            r = await session.execute(q.offset(offset).limit(size))
            rows = r.scalars().all()
            ids = [x.id for x in rows]
            scores_map: dict[int, int] = {}
            if ids:
                for cid in ids:
                    r3 = await session.execute(
                        select(CaseScore.score_value)
                        .where(CaseScore.case_id == cid)
                        .order_by(CaseScore.created_at.desc())
                        .limit(1)
                    )
                    s = r3.scalar_one_or_none()
                    if s is not None:
                        scores_map[cid] = s
            if order_by_score and rows:
                rows = sorted(rows, key=lambda x: (scores_map.get(x.id) or 0), reverse=True)
            items = []
            for row in rows:
                item = {
                    "id": row.id,
                    "title": row.title,
                    "summary": (row.summary or "")[:200] if row.summary else "",
                    "industry": row.industry,
                    "goal_type": row.goal_type,
                    "scenario_tags": row.scenario_tags,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "latest_score": scores_map.get(row.id),
                }
                if include_content:
                    item["content"] = row.content
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": size}

    async def add_score(
        self,
        case_id: int,
        source: str,
        score_value: int,
        payload: dict | None = None,
    ) -> bool:
        """写入一条打分。source 为 platform_reflow | user_review | system_auto。"""
        async with self._session_factory() as session:
            try:
                s = CaseScore(case_id=case_id, source=source, score_value=score_value, payload=payload)
                session.add(s)
                await session.commit()
                return True
            except Exception as e:
                logger.warning("CaseTemplateService.add_score 失败: %s", e)
                await session.rollback()
                return False

    async def update(self, case_id: int, **kwargs: Any) -> bool:
        """更新案例部分字段。"""
        allowed = {"title", "summary", "content", "scenario_tags", "industry", "goal_type", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return True
        async with self._session_factory() as session:
            try:
                r = await session.execute(select(MarketingCaseTemplate).where(MarketingCaseTemplate.id == case_id))
                row = r.scalar_one_or_none()
                if not row:
                    return False
                for k, v in updates.items():
                    setattr(row, k, v)
                await session.commit()
                return True
            except Exception as e:
                await session.rollback()
                return False

    async def delete(self, case_id: int) -> bool:
        """删除案例（硬删，关联 case_scores 会级联删）。"""
        async with self._session_factory() as session:
            try:
                r = await session.execute(select(MarketingCaseTemplate).where(MarketingCaseTemplate.id == case_id))
                row = r.scalar_one_or_none()
                if not row:
                    return False
                await session.delete(row)
                await session.commit()
                return True
            except Exception as e:
                await session.rollback()
                return False
