"""
营销方法论服务：基于 knowledge/ 目录的 Markdown 文件管理，可扩展 DB。
列表、读取、创建、更新、删除；更新后需删除向量目录以触发知识库重建。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "./knowledge")
METHODOLOGY_SUBDIR = "methodology"


class MethodologyService:
    """营销方法论：管理 knowledge/methodology/*.md（或 knowledge/*.md）。"""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base = Path(base_dir or DEFAULT_KNOWLEDGE_DIR)
        self._methodology_dir = self._base / METHODOLOGY_SUBDIR

    def _ensure_dir(self) -> None:
        self._methodology_dir.mkdir(parents=True, exist_ok=True)

    def list_docs(self, category: str | None = None) -> List[dict]:
        """列出方法论文档：文件名、相对路径、可选分类。category 暂未用，预留按子目录筛选。"""
        self._ensure_dir()
        out = []
        for f in self._methodology_dir.glob("**/*.md"):
            try:
                rel = f.relative_to(self._base)
                out.append({
                    "path": str(rel),
                    "name": f.stem,
                    "size": f.stat().st_size,
                })
            except Exception as e:
                logger.warning("list_docs 跳过 %s: %s", f, e)
        # 同时列出根目录下非 README 的 .md（与现有 marketing_knowledge 等一致）
        for f in self._base.glob("*.md"):
            if f.name.upper() == "README.MD":
                continue
            out.append({"path": f.name, "name": f.stem, "size": f.stat().st_size})
        return out

    def get_content(self, path: str) -> Optional[str]:
        """读取文档内容。path 为相对 knowledge 的路径，如 methodology/xxx.md 或 marketing_knowledge.md。"""
        full = self._base / path
        if not full.exists() or not full.is_file():
            return None
        try:
            return full.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("get_content %s 失败: %s", path, e)
            return None

    def create_or_update(self, path: str, content: str) -> bool:
        """创建或更新文档。path 建议为 methodology/xxx.md。"""
        self._ensure_dir()
        full = self._base / path
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            logger.warning("create_or_update %s 失败: %s", path, e)
            return False

    def delete(self, path: str) -> bool:
        """删除文档。"""
        full = self._base / path
        if not full.exists() or not full.is_file():
            return False
        try:
            full.unlink()
            return True
        except Exception as e:
            logger.warning("delete %s 失败: %s", path, e)
            return False

    def get_vector_dir(self) -> str:
        """返回向量持久化目录，便于调用方在更新方法论后删除以触发重建。"""
        return os.getenv("KNOWLEDGE_VECTOR_DIR", "./data/knowledge_vectors")
