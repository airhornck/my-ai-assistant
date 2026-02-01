"""
文档物理存储：本地保存或云存储（OSS 等）。
生产环境可替换为 OSS 实现，接口保持一致。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import BinaryIO, Optional

logger = __import__("logging").getLogger(__name__)

UPLOAD_DIR_ENV = "UPLOAD_DIR"
DEFAULT_UPLOAD_DIR = "uploads"
SAFE_FILENAME_MAX_LEN = 200
SAFE_FILENAME_PATTERN = re.compile(r"[^\w\u4e00-\u9fff.\-]", re.UNICODE)


def _get_upload_root() -> str:
    return os.getenv(UPLOAD_DIR_ENV, DEFAULT_UPLOAD_DIR).rstrip("/")


def sanitize_filename(name: str) -> str:
    """防路径遍历与冲突：只保留安全字符并截断长度。"""
    base = os.path.basename(name).strip() or "unnamed"
    safe = SAFE_FILENAME_PATTERN.sub("_", base)
    if len(safe) > SAFE_FILENAME_MAX_LEN:
        ext = ""
        if "." in safe:
            safe, ext = safe.rsplit(".", 1)
            ext = "." + ext[:20]
        safe = safe[: SAFE_FILENAME_MAX_LEN - len(ext)] + ext
    return safe or "unnamed"


def build_storage_path(user_id: str, doc_id: str, safe_filename: str) -> str:
    """构建存储路径：uploads/{user_id}/{doc_id}_{filename}"""
    root = _get_upload_root()
    safe_user = re.sub(r"[^\w\-]", "_", user_id)[:64]
    safe_doc = re.sub(r"[^\w\-]", "_", doc_id)[:64]
    rel = f"{safe_user}/{safe_doc}_{safe_filename}"
    return os.path.join(root, rel)


class DocumentStorage:
    """
    文档物理存储。当前实现为本地文件系统；生产可替换为 OSS。
    """

    def __init__(self, upload_root: Optional[str] = None) -> None:
        self._root = upload_root or _get_upload_root()

    def save(self, content: bytes, user_id: str, doc_id: str, filename: str) -> str:
        """
        保存文件内容到存储。返回最终存储路径（绝对路径，便于解析时跨目录访问）。
        """
        safe_name = sanitize_filename(filename)
        storage_path = build_storage_path(user_id, doc_id, safe_name)
        # 转为绝对路径，避免工作目录变化导致解析时找不到文件
        storage_path = os.path.abspath(storage_path)
        dir_path = os.path.dirname(storage_path)
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        with open(storage_path, "wb") as f:
            f.write(content)
        return storage_path

    def read(self, storage_path: str) -> bytes:
        """读取文件内容。"""
        with open(storage_path, "rb") as f:
            return f.read()

    def exists(self, storage_path: str) -> bool:
        """检查文件是否存在。"""
        return os.path.isfile(storage_path)
