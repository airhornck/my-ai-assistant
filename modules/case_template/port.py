"""
案例模板 Port：案例 CRUD 与打分接口抽象。
实现者可替换为不同存储后端。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CaseTemplate:
    """案例模板。"""

    id: str
    title: str
    platform: str = ""
    category: str = ""
    content: str = ""
    scores: dict[str, float] = field(default_factory=dict)  # 各来源打分
    total_score: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseScore:
    """单条打分记录。"""

    case_id: str
    source: str  # platform_reflow, user_review, system_auto
    score: float
    comment: str = ""
    scored_at: str = ""


class ICaseTemplatePort(ABC):
    """案例模板端口。"""

    @abstractmethod
    async def create(
        self,
        title: str,
        platform: str = "",
        category: str = "",
        content: str = "",
        **kwargs: Any,
    ) -> CaseTemplate:
        """
        创建案例模板。
        """
        ...

    @abstractmethod
    async def get_by_id(self, case_id: str) -> Optional[CaseTemplate]:
        """
        按 ID 查询案例。
        """
        ...

    @abstractmethod
    async def list(
        self,
        platform: str | None = None,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[CaseTemplate]:
        """
        列表查询案例。
        """
        ...

    @abstractmethod
    async def update(
        self,
        case_id: str,
        title: str | None = None,
        content: str | None = None,
        **kwargs: Any,
    ) -> Optional[CaseTemplate]:
        """
        更新案例内容。
        """
        ...

    @abstractmethod
    async def delete(self, case_id: str) -> bool:
        """
        删除案例。
        """
        ...

    @abstractmethod
    async def add_score(
        self,
        case_id: str,
        source: str,
        score: float,
        comment: str = "",
    ) -> bool:
        """
        添加打分记录。
        """
        ...

    @abstractmethod
    async def get_scores(self, case_id: str) -> list[CaseScore]:
        """
        获取案例的所有打分记录。
        """
        ...
