"""
文档服务：上传、存储与查询。
本地存储路径为 uploads/{user_id}/{doc_id}_{safe_filename}；
生产环境建议使用阿里云 OSS，此处预留扩展点。
"""
from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.document import Document, DocumentResponse, generate_doc_id

logger = logging.getLogger(__name__)

# 环境变量：本地存储根目录；生产环境可改为 OSS 等
UPLOAD_DIR_ENV = "UPLOAD_DIR"
DEFAULT_UPLOAD_DIR = "uploads"

# 文件名安全：仅保留字母数字、中文、点、下划线、横线，最大长度
SAFE_FILENAME_MAX_LEN = 200
SAFE_FILENAME_PATTERN = re.compile(r"[^\w\u4e00-\u9fff.\-]", re.UNICODE)


def _get_upload_root() -> str:
    return os.getenv(UPLOAD_DIR_ENV, DEFAULT_UPLOAD_DIR).rstrip("/")


def _sanitize_filename(name: str) -> str:
    """
    防路径遍历与冲突：只保留安全字符并截断长度。
    使用 os.path.basename 去除路径成分。
    """
    base = os.path.basename(name).strip() or "unnamed"
    safe = SAFE_FILENAME_PATTERN.sub("_", base)
    if len(safe) > SAFE_FILENAME_MAX_LEN:
        ext = ""
        if "." in safe:
            safe, ext = safe.rsplit(".", 1)
            ext = "." + ext[:20]
        safe = safe[: SAFE_FILENAME_MAX_LEN - len(ext)] + ext
    return safe or "unnamed"


def _build_local_path(user_id: str, doc_id: str, safe_filename: str) -> str:
    """本地路径：uploads/{user_id}/{doc_id}_{safe_filename}，防路径遍历。"""
    root = _get_upload_root()
    safe_user = re.sub(r"[^\w\-]", "_", user_id)[:64]
    safe_doc = re.sub(r"[^\w\-]", "_", doc_id)[:64]
    rel = f"{safe_user}/{safe_doc}_{safe_filename}"
    return os.path.join(root, rel)


class DocumentService:
    """
    文档服务：上传保存到本地（或后续扩展 OSS），元信息入库。
    本地存储需注意磁盘空间与权限；生产建议使用阿里云 OSS。
    """

    def __init__(self, db: AsyncSession, upload_root: Optional[str] = None) -> None:
        self._db = db
        self._upload_root = upload_root or _get_upload_root()

    async def upload(self, file, user_id: str) -> DocumentResponse:
        """
        处理上传：保存文件到 uploads/{user_id}/{doc_id}_{filename}，并将元信息写入数据库。
        file 需具备 filename 与 read()（如 FastAPI UploadFile）。
        """
        original_filename = getattr(file, "filename", None) or "unnamed"
        safe_filename = _sanitize_filename(original_filename)
        doc_id = generate_doc_id()
        storage_path = _build_local_path(user_id, doc_id, safe_filename)
        dir_path = os.path.dirname(storage_path)
        Path(dir_path).mkdir(parents=True, exist_ok=True)

        reader = getattr(file, "read", None)
        if reader is None:
            raise ValueError("file 对象需提供 read 方法")
        result = reader()
        if hasattr(result, "__await__"):
            content = await result
        else:
            content = result
        with open(storage_path, "wb") as f:
            f.write(content)

        file_type = _guess_file_type(original_filename)
        doc = Document(
            doc_id=doc_id,
            user_id=user_id,
            filename=safe_filename,
            original_filename=original_filename,
            file_type=file_type,
            storage_path=storage_path,
            metadata_=None,
        )
        self._db.add(doc)
        await self._db.flush()
        await self._db.refresh(doc)
        logger.info("document upload: doc_id=%s user_id=%s path=%s", doc_id, user_id, storage_path)
        return DocumentResponse.from_orm_document(doc)

    async def get(self, doc_id: str, user_id: str) -> Optional[DocumentResponse]:
        """获取文档信息；仅返回属于该 user_id 的文档。"""
        result = await self._db.execute(
            select(Document).where(Document.doc_id == doc_id, Document.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return DocumentResponse.from_orm_document(row)

    async def list_by_user(self, user_id: str) -> List[DocumentResponse]:
        """列出该用户所有文档（按上传时间倒序）。"""
        result = await self._db.execute(
            select(Document).where(Document.user_id == user_id).order_by(Document.upload_time.desc())
        )
        rows = result.scalars().all()
        return [DocumentResponse.from_orm_document(r) for r in rows]


def _guess_file_type(filename: str) -> str:
    """根据扩展名猜测 file_type（MIME 或扩展名）。"""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return ext or "bin"
