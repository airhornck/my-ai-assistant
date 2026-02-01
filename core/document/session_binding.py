"""
会话-文档关联：将文档绑定到会话，供理解对话时引用。
类似 OpenAI 的「会话中附加文件」能力。
"""
from __future__ import annotations

import os
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.document.parser import DocumentParser
from core.document.storage import DocumentStorage
from models.document import Document, DocumentResponse, SessionDocument, generate_doc_id

logger = __import__("logging").getLogger(__name__)


class SessionDocumentBinding:
    """
    会话文档绑定服务：上传时绑定到 session，查询时按 session 加载并解析为上下文。
    """

    def __init__(
        self,
        db: AsyncSession,
        storage: Optional[DocumentStorage] = None,
        parser: Optional[DocumentParser] = None,
    ) -> None:
        self._db = db
        self._storage = storage or DocumentStorage()
        self._parser = parser or DocumentParser()

    async def attach(
        self,
        file_content: bytes,
        filename: str,
        user_id: str,
        session_id: str,
    ) -> DocumentResponse:
        """
        上传文件并绑定到会话。返回文档信息。
        """
        doc_id = generate_doc_id()
        storage_path = self._storage.save(file_content, user_id, doc_id, filename)
        file_type = _guess_file_type(filename)
        doc = Document(
            doc_id=doc_id,
            user_id=user_id,
            filename=os.path.basename(storage_path),
            original_filename=filename,
            file_type=file_type,
            storage_path=storage_path,
            metadata_=None,
        )
        self._db.add(doc)
        await self._db.flush()
        sess_doc = SessionDocument(
            id=generate_doc_id(),
            session_id=session_id,
            doc_id=doc_id,
        )
        self._db.add(sess_doc)
        await self._db.flush()
        await self._db.refresh(doc)
        return DocumentResponse.from_orm_document(doc)

    async def list_by_session(self, session_id: str) -> List[DocumentResponse]:
        """列出会话下所有附加文档。"""
        q = (
            select(Document)
            .join(SessionDocument, SessionDocument.doc_id == Document.doc_id)
            .where(SessionDocument.session_id == session_id)
            .order_by(SessionDocument.attached_at.desc())
        )
        result = await self._db.execute(q)
        rows = result.scalars().all()
        return [DocumentResponse.from_orm_document(r) for r in rows]

    async def get_session_document_context(
        self,
        session_id: str,
        max_chars_per_doc: int = 8000,
        max_total_chars: int = 20000,
    ) -> str:
        """
        加载会话下所有文档，解析为可引用的上下文文本。
        用于在理解对话时作为补充信息注入到 prompt。
        """
        docs = await self.list_by_session(session_id)
        if not docs:
            return ""
        parts = []
        total = 0
        for d in docs:
            if total >= max_total_chars:
                break
            text = self._parser.parse(d.storage_path, d.file_type, d.original_filename)
            if not text.strip():
                continue
            if len(text) > max_chars_per_doc:
                text = text[:max_chars_per_doc] + "\n...[已截断]"
            parts.append(f"【文档：{d.original_filename}】\n{text}")
            total += len(text)
        if not parts:
            return ""
        return "\n\n---\n\n".join(parts)


def _guess_file_type(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return ext or "bin"
