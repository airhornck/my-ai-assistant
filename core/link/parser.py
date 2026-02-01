"""
链接解析：从文本提取 URL，抓取网页主文内容，供 AI 理解对话时引用。
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 简单 URL 正则（http/https）
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)

# 单链接最大抓取字符
MAX_CHARS_PER_LINK = 5000
# 最多处理链接数
MAX_LINKS_PER_MESSAGE = 5
# 请求超时（秒）
FETCH_TIMEOUT = 10


def extract_urls(text: str) -> List[str]:
    """
    从文本中提取所有 http/https URL。
    返回去重后的列表，最多 MAX_LINKS_PER_MESSAGE 个。
    """
    if not text or not isinstance(text, str):
        return []
    urls = _URL_PATTERN.findall(text)
    seen = set()
    result = []
    for u in urls:
        u = u.rstrip(".,;:!?)")
        if u not in seen and _is_valid_url(u):
            seen.add(u)
            result.append(u)
            if len(result) >= MAX_LINKS_PER_MESSAGE:
                break
    return result


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


async def fetch_link_context(
    urls: List[str],
    max_chars_per_link: int = MAX_CHARS_PER_LINK,
) -> str:
    """
    异步抓取多个 URL 的主文内容，拼接为可注入 prompt 的文本。
    失败时跳过该链接，不阻断流程。
    """
    if not urls:
        return ""
    import asyncio

    async def _fetch_one(url: str) -> str:
        try:
            html = await _fetch_html(url)
            if not html:
                return ""
            return _extract_main_text(html, url, max_chars_per_link)
        except Exception as e:
            logger.warning("抓取链接失败 %s: %s", url, e)
            return ""

    tasks = [_fetch_one(u) for u in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    parts = []
    for url, r in zip(urls, results):
        if isinstance(r, str) and r.strip():
            parts.append(f"【链接：{url}】\n{r.strip()}")
        elif isinstance(r, Exception):
            logger.warning("抓取 %s 异常: %s", url, r)
    if not parts:
        return ""
    return "\n\n---\n\n".join(parts)


async def _fetch_html(url: str) -> str:
    """异步抓取 HTML。"""
    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AIAssistant/1.0)"},
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
    except ImportError:
        import asyncio
        import urllib.request

        def _sync_get():
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AIAssistant/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")

        return await asyncio.to_thread(_sync_get)
    except Exception as e:
        logger.warning("请求 %s 失败: %s", url, e)
        return ""


def _extract_main_text(html: str, url: str, max_chars: int) -> str:
    """
    从 HTML 提取主文。
    优先 trafilatura，后备 readability。
    """
    text = ""
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, include_tables=False)
    except ImportError:
        pass
    except Exception as e:
        logger.warning("trafilatura 解析失败: %s", e)

    if not text:
        try:
            from readability import Document

            doc = Document(html)
            text = doc.summary()
            if text:
                text = re.sub(r"<[^>]+>", " ", text)
                text = " ".join(text.split())
        except ImportError:
            pass
        except Exception as e:
            logger.warning("readability 解析失败: %s", e)

    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[已截断]"
    return text.strip()
