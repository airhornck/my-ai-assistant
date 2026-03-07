"""
定时刷新任务调度器
"""
import asyncio
import logging
from datetime import datetime
from typing import List

from cache.smart_cache import SmartCache
from services.ai_service import SimpleAIService
from services.industry_news_refresh import refresh_industry_news_report
from services.bilibili_multi_rankings_refresh import refresh_bilibili_multi_rankings_report
from services.bilibili_hotspot_refresh_enhanced import refresh_bilibili_hotspot_report

logger = logging.getLogger(__name__)


class RefreshScheduler:
    def __init__(self):
        self.cache = SmartCache()
        self.ai_service = SimpleAIService()
        self.tasks = []

    async def refresh_all(self):
        """执行所有刷新任务"""
        tasks = [
            self._safe_refresh("行业新闻", refresh_industry_news_report),
            self._safe_refresh("B站多榜单", refresh_bilibili_multi_rankings_report),
            self._safe_refresh("B站热点", refresh_bilibili_hotspot_report),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if not isinstance(r, Exception))
        logger.info(f"定时刷新完成，成功{success_count}/{len(tasks)}个任务")

    async def _safe_refresh(self, name: str, refresh_func):
        """安全执行刷新任务"""
        try:
            start_time = datetime.now()
            logger.info(f"开始刷新{name}...")
            result = await refresh_func(
                cache=self.cache,
                ai_service=self.ai_service,
                web_searcher=None  # 使用默认配置
            )
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"{name}刷新完成，耗时{duration:.2f}秒")
            return result
        except Exception as e:
            logger.error(f"{name}刷新失败: {e}")
            return e


async def main():
    """主函数：执行一次刷新"""
    scheduler = RefreshScheduler()
    await scheduler.refresh_all()


if __name__ == "__main__":
    asyncio.run(main())