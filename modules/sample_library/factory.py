"""
样本库工厂：按配置选择实现。
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from modules.sample_library.port import SampleLibraryPort
from modules.sample_library.mock_adapter import MockSampleLibraryAdapter

if TYPE_CHECKING:
    from cache.smart_cache import SmartCache


def get_sample_library(cache: "object | None" = None) -> SampleLibraryPort:
    """
    获取样本库 Port。
    环境变量：SAMPLE_LIBRARY_PROVIDER=mock|redis|pg
    当前仅 mock 可用；redis/pg 可后续接入。
    """
    p = (os.getenv("SAMPLE_LIBRARY_PROVIDER", "mock")).strip().lower()
    if p in ("redis", "pg"):
        # TODO: 接入 Redis / PostgreSQL 存储
        pass
    return MockSampleLibraryAdapter()
