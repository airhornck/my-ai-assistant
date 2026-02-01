#!/usr/bin/env python3
"""
B站热点榜单手动刷新脚本。
可用于 cron 定时调用，或启动前预热缓存。
"""
import asyncio
import logging
import sys
from pathlib import Path

# 确保项目根目录在 path 中
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    from dotenv import load_dotenv
    for _f in (".env", ".env.dev", ".env.prod"):
        _p = _root / _f
        if _p.exists():
            load_dotenv(_p)
            break

    from cache.smart_cache import SmartCache
    from services.ai_service import SimpleAIService
    from services.bilibili_hotspot_refresh import refresh_bilibili_hotspot_report

    cache = SmartCache()
    ai_service = SimpleAIService(cache=cache)
    await refresh_bilibili_hotspot_report(cache=cache, ai_service=ai_service)
    logger.info("B站热点榜单刷新完成")


if __name__ == "__main__":
    asyncio.run(main())
