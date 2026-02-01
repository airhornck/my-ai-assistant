"""
网络搜索模块：检索竞品、热点、行业数据等。
可接入 SerpAPI、百度千帆 web_search API 等，当前支持 mock 与 baidu。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class WebSearcher:
    """
    网络检索模块。
    生产环境可接入百度千帆 web_search API（配置 SEARCH_PROVIDER=baidu 与 BAIDU_SEARCH_API_KEY）。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "mock",
        base_url: Optional[str] = None,
        top_k: int = 20,
    ) -> None:
        """
        Args:
            api_key: 搜索 API Key（百度用 BAIDU_SEARCH_API_KEY）
            provider: 搜索供应商（mock|serpapi|baidu）
            base_url: 百度搜索 API 地址（可选）
            top_k: 百度搜索每页条数
        """
        self._api_key = api_key
        self._provider = provider
        self._base_url = base_url or "https://qianfan.baidubce.com/v2/ai_search/web_search"
        self._top_k = min(max(top_k, 1), 50)

    async def search(
        self,
        query: str,
        num_results: int = 5,
        search_type: str = "general",
    ) -> list[dict[str, Any]]:
        """
        网络检索。
        
        Args:
            query: 搜索关键词
            num_results: 返回结果数
            search_type: general（通用）| news（新闻）| product（商品）
        
        Returns:
            [{"title": "...", "snippet": "...", "url": "...", "source": "..."}]
        """
        if self._provider == "mock":
            return self._mock_search(query, num_results)
        elif self._provider == "baidu":
            return await self._baidu_search(query, num_results)
        elif self._provider == "serpapi":
            return await self._serpapi_search(query, num_results)
        else:
            logger.warning("不支持的搜索供应商: %s", self._provider)
            return []

    def _mock_search(self, query: str, num_results: int) -> list[dict]:
        """Mock 实现，用于开发测试。"""
        logger.info("Mock 搜索: query=%s", query)
        return [
            {
                "title": f"搜索结果 {i+1}：{query}",
                "snippet": f"这是关于「{query}」的相关信息摘要...",
                "url": f"https://example.com/result{i+1}",
                "source": "mock",
            }
            for i in range(min(num_results, 3))
        ]

    async def _baidu_search(self, query: str, num_results: int) -> list[dict]:
        """
        百度千帆 web_search API 实现。
        文档：https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
        鉴权：支持 Authorization 与 X-Appbuilder-Authorization（官方 curl 示例使用后者）
        """
        if not self._api_key:
            logger.info("百度搜索 API Key 未配置，使用 mock 搜索")
            return self._mock_search(query, num_results)
        try:
            import httpx
            top_k = min(num_results, self._top_k)
            payload = {
                "messages": [{"content": query.strip(), "role": "user"}],
                "search_source": "baidu_search_v2",
                "resource_type_filter": [{"type": "web", "top_k": top_k}],
            }
            # 官方示例使用 X-Appbuilder-Authorization，部分环境需 Authorization，两者都带上
            bearer = f"Bearer {self._api_key.strip()}"
            headers = {
                "Content-Type": "application/json",
                "Authorization": bearer,
                "X-Appbuilder-Authorization": bearer,
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self._base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            refs = data.get("references") or []
            results = []
            for r in refs[:num_results]:
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("content") or r.get("snippet", ""),
                    "url": r.get("url", ""),
                    "source": "baidu",
                })
            return results
        except Exception as e:
            # 401 等鉴权失败时简洁提示，避免刷屏；已自动降级 mock
            err_msg = str(e).strip()
            if "401" in err_msg or "Unauthorized" in err_msg:
                logger.info(
                    "百度搜索鉴权失败(401)，已使用 mock。请检查 BAIDU_SEARCH_API_KEY 是否为千帆控制台的 API Key"
                )
            else:
                logger.warning("百度搜索调用失败: %s", e, exc_info=True)
            return self._mock_search(query, num_results)

    async def _serpapi_search(self, query: str, num_results: int) -> list[dict]:
        """
        SerpAPI 实现（需安装 google-search-results 或直接 HTTP 调用）。
        文档：https://serpapi.com/search-api
        """
        if not self._api_key:
            logger.warning("SerpAPI Key 未配置，降级为 mock")
            return self._mock_search(query, num_results)
        
        try:
            # TODO: 接入 SerpAPI
            logger.warning("SerpAPI 集成待实现，当前使用 mock")
            return self._mock_search(query, num_results)
        except Exception as e:
            logger.warning("SerpAPI 调用失败: %s", e, exc_info=True)
            return self._mock_search(query, num_results)

    def format_results_as_context(self, results: list[dict]) -> str:
        """将搜索结果格式化为可注入 prompt 的文本。"""
        if not results:
            return "（未检索到相关信息）"
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            url = r.get("url", "")
            lines.append(f"{i}. **{title}**\n   {snippet}\n   来源：{url}")
        return "\n\n".join(lines)
