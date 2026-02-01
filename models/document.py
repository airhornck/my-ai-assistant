"""
文档数据模型：ORM 表与 API 响应结构。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.types import JSON

from database import Base


def generate_doc_id() -> str:
    """生成文档唯一 ID。"""
    return str(uuid.uuid4()).replace("-", "")[:32]


# ---------------------------------------------------------------------------
# ORM 模型（与 database.Base 一致）
# ---------------------------------------------------------------------------


class Document(Base):
    """
    文档表：存储用户上传文件的元信息。
    storage_path 可为本地路径或阿里云 OSS 等云存储路径。
    """

    __tablename__ = "documents"

    doc_id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    filename = Column(String(512), nullable=False, comment="存储用文件名，防冲突")
    original_filename = Column(String(512), nullable=False, comment="用户原始文件名")
    file_type = Column(String(64), nullable=False, comment="MIME 或扩展名")
    storage_path = Column(String(1024), nullable=False, comment="云存储或本地路径")
    upload_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    metadata_ = Column("metadata", JSON, nullable=True, default=None, comment="解析出的摘要、关键词等")


class SessionDocument(Base):
    """
    会话-文档关联表：将文档绑定到会话，支持「会话中附加文件」。
    类似 OpenAI 在对话中附加文件的能力。
    """

    __tablename__ = "session_documents"

    id = Column(String(64), primary_key=True)
    session_id = Column(String(128), nullable=False, index=True)
    doc_id = Column(String(64), ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False, index=True)
    attached_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Pydantic 响应模型（API 使用）
# ---------------------------------------------------------------------------


class DocumentResponse(BaseModel):
    """文档信息响应（GET /documents、GET /documents/{doc_id}）。"""

    doc_id: str = Field(..., description="文档唯一标识")
    user_id: str = Field(..., description="上传用户 ID")
    filename: str = Field(..., description="存储用文件名")
    original_filename: str = Field(..., description="用户原始文件名")
    file_type: str = Field(..., description="文件类型")
    storage_path: str = Field(..., description="存储路径")
    upload_time: datetime = Field(..., description="上传时间")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="摘要、关键词等")

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_document(cls, row: Document) -> "DocumentResponse":
        return cls(
            doc_id=row.doc_id,
            user_id=row.user_id,
            filename=row.filename,
            original_filename=row.original_filename,
            file_type=row.file_type,
            storage_path=row.storage_path,
            upload_time=row.upload_time,
            metadata=row.metadata_,
        )
