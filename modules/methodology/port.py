"""
方法论 Port：方法论文档管理接口抽象。
实现者可替换为数据库存储、文件系统等。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MethodologyDoc:
    """单篇方法论文档。"""

    filename: str
    relative_path: str
    category: str = ""
    content: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class IMethodologyPort(ABC):
    """方法论文档管理端口。"""

    @abstractmethod
    def list_docs(self, category: str | None = None) -> list[MethodologyDoc]:
        """
        列出方法论文档。
        :param category: 可选分类筛选
        :return: 文档列表
        """
        ...

    @abstractmethod
    def get_doc(self, relative_path: str) -> Optional[MethodologyDoc]:
        """
        获取单篇文档内容。
        :param relative_path: 相对于知识库根目录的路径
        :return: 文档内容，不存在返回 None
        """
        ...

    @abstractmethod
    def create_doc(
        self,
        filename: str,
        content: str,
        category: str = "",
    ) -> MethodologyDoc:
        """
        创建新文档。
        :param filename: 文件名
        :param content: 文档内容
        :param category: 分类
        :return: 创建的文档
        """
        ...

    @abstractmethod
    def update_doc(
        self,
        relative_path: str,
        content: str,
    ) -> Optional[MethodologyDoc]:
        """
        更新文档内容。
        :param relative_path: 文档路径
        :param content: 新内容
        :return: 更新后的文档，不存在返回 None
        """
        ...

    @abstractmethod
    def delete_doc(self, relative_path: str) -> bool:
        """
        删除文档。
        :param relative_path: 文档路径
        :return: 是否删除成功
        """
        ...
