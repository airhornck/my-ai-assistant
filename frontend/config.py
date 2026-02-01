"""
前端配置：后端地址、超时、文件类型等，便于统一管理与环境切换。
"""
from __future__ import annotations

import os
from pathlib import Path

# 加载 .env（与项目根目录 .env 对齐，.env 不存在时尝试 .env.dev）
try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent.parent
    for _name in (".env", ".env.dev"):
        _p = _root / _name
        if _p.exists():
            load_dotenv(_p)
            break
except ImportError:
    pass

# 后端 API（去除末尾斜杠，避免 URL 拼接问题）
_raw = os.getenv("BACKEND_URL", "http://localhost:8000").strip()
BACKEND_URL = _raw.rstrip("/") if _raw else "http://localhost:8000"

# 超时（秒）
TIMEOUT_CHAT = 30.0
TIMEOUT_DEEP = 150.0
TIMEOUT_INIT = 10.0
TIMEOUT_UPLOAD = 60.0

# 文件上传（与后端 core/document/parser.SUPPORTED_DOC_EXTENSIONS 对齐）
ALLOWED_FILE_TYPES = [
    ".pdf", ".txt", ".md", ".docx", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif",
]
ALLOWED_FILE_EXTENSIONS = [
    "pdf", "txt", "md", "docx", "pptx",
    "jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif",
]

# 对话历史
MAX_HISTORY_ITEMS = 10
MAX_CONTENT_LENGTH_PER_MSG = 500

# 输入限制（可选，防止超长请求）
MAX_INPUT_LENGTH = 2000
