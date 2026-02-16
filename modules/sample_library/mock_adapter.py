"""
样本库 Mock 适配器：内存存储，开发/测试用。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from modules.sample_library.port import SampleLibraryPort, SampleRecord

logger = logging.getLogger(__name__)


class MockSampleLibraryAdapter(SampleLibraryPort):
    """内存实现：简单 dict 存储，进程重启后清空。"""

    def __init__(self) -> None:
        self._store: dict[str, SampleRecord] = {}  # key: f"{platform}:{video_id}"

    def _key(self, video_id: str, platform: str) -> str:
        return f"{platform or 'default'}:{video_id}"

    async def ingest(
        self,
        samples: list[SampleRecord | dict],
        *,
        batch_size: int = 100,
    ) -> int:
        count = 0
        for s in samples[: batch_size * 10]:  # 简单限制
            if isinstance(s, dict):
                rec = SampleRecord(
                    video_id=s.get("video_id", ""),
                    platform=s.get("platform", "default"),
                    title=s.get("title", ""),
                    features=s.get("features", {}),
                    metrics=s.get("metrics", {}),
                    published_at=s.get("published_at", ""),
                    category=s.get("category", ""),
                    extra=s.get("extra", {}),
                )
            else:
                rec = s
            if rec.video_id:
                self._store[self._key(rec.video_id, rec.platform)] = rec
                count += 1
        logger.debug("Mock 样本库 ingest: %d 条", count)
        return count

    async def search(
        self,
        *,
        platform: str = "",
        category: str = "",
        top_k: int = 20,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[SampleRecord]:
        results = []
        for rec in self._store.values():
            if platform and rec.platform != platform:
                continue
            if category and rec.category != category:
                continue
            results.append(rec)
        return results[:top_k]

    async def get_by_id(
        self,
        video_id: str,
        platform: str = "",
    ) -> Optional[SampleRecord]:
        return self._store.get(self._key(video_id, platform))
