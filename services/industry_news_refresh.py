"""
行业新闻定时任务：从多个行业网站获取新闻，通过API或爬虫方式
使用 xmltodict 替代 feedparser 以避免依赖问题
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import httpx
import xmltodict  # 替代 feedparser
from bs4 import BeautifulSoup
from bs4 import UnicodeDammit
from langchain_core.messages import HumanMessage, SystemMessage

from cache.smart_cache import (
    INDUSTRY_NEWS_CACHE_KEY,
    TTL_INDUSTRY_NEWS,
    SmartCache,
)
from config.search_config import get_search_config
from core.search import WebSearcher
from services.ai_service import SimpleAIService

logger = logging.getLogger(__name__)

# 限频：避免某些源长期反爬/返回脏 XML 导致日志刷屏
_RSS_WARN_THROTTLE_SECONDS = 30 * 60
_rss_warn_last_ts: dict[str, float] = {}


def _warn_throttled(key: str, msg: str) -> None:
    now = time.time()
    last = _rss_warn_last_ts.get(key, 0.0)
    if now - last >= _RSS_WARN_THROTTLE_SECONDS:
        _rss_warn_last_ts[key] = now
        logger.warning(msg)


_INVALID_XML_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def _looks_like_rss_or_xml(text: str) -> bool:
    # 反爬 HTML、跳转页、或 JSON 错误页经常导致 xmltodict 直接炸
    t = (text or "").lstrip().lower()
    if not t:
        return False
    if t.startswith("<!doctype html") or t.startswith("<html"):
        return False
    return ("<rss" in t) or ("<feed" in t) or t.startswith("<?xml")


def _decode_and_sanitize_xml(raw: bytes) -> str:
    # 尽量宽容地解码，随后剔除 XML 1.0 不允许的控制字符
    ud = UnicodeDammit(raw, is_html=False)
    text = ud.unicode_markup or raw.decode("utf-8", errors="replace")
    return _INVALID_XML_CHARS_RE.sub("", text)


def _safe_xmltodict_parse(xml_text: str) -> dict[str, Any] | None:
    """
    xmltodict 基于 expat，遇到脏字符/未转义 & 很容易报 not well-formed。
    这里做最小兜底：先直接 parse；失败再用 lxml recover 生成“尽量可读”的 XML。
    """
    try:
        return xmltodict.parse(xml_text)
    except Exception:
        try:
            # lxml 在本项目依赖中，且对坏 XML 更宽容
            from lxml import etree

            parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)
            root = etree.fromstring(xml_text.encode("utf-8", errors="ignore"), parser=parser)
            fixed = etree.tostring(root, encoding="utf-8", xml_declaration=True)
            return xmltodict.parse(fixed)
        except Exception:
            return None


# 行业分类配置
INDUSTRY_CONFIGS = {
    "科技": {
        "sources": [
            {"name": "36氪", "url": "https://36kr.com/feed", "type": "rss"},
            {"name": "虎嗅", "url": "https://www.huxiu.com/rss/0.xml", "type": "rss"},
            {"name": "钛媒体", "url": "https://www.tmtpost.com/rss.xml", "type": "rss"},
            {"name": "IT之家", "url": "https://www.ithome.com/rss/", "type": "rss"},
        ],
        "keywords": ["科技", "互联网", "AI", "人工智能", "云计算", "大数据", "区块链", "元宇宙"]
    },
    "金融": {
        "sources": [
            {"name": "华尔街见闻", "url": "https://wallstreetcn.com/rss", "type": "rss"},
            {"name": "财联社", "url": "https://www.cls.cn/rss", "type": "rss"},
            {"name": "雪球", "url": "https://xueqiu.com/", "type": "scrape", "selectors": [".article__bd__title"]},
        ],
        "keywords": ["金融", "股市", "投资", "银行", "保险", "证券", "经济"]
    },
    "娱乐": {
        "sources": [
            {"name": "豆瓣电影", "url": "https://www.douban.com/feed/review/movie", "type": "rss"},
            {"name": "微博热搜", "url": "https://s.weibo.com/top/summary", "type": "scrape", "selectors": ["#pl_top_realtimehot td a"]},
        ],
        "keywords": ["娱乐", "电影", "明星", "综艺", "电视剧", "音乐"]
    },
    "游戏": {
        "sources": [
            {"name": "游民星空", "url": "https://www.gamersky.com/news/rss", "type": "rss"},
            {"name": "3DM", "url": "https://www.3dmgame.com/news/", "type": "scrape", "selectors": [".bt_img li a"]},
        ],
        "keywords": ["游戏", "电竞", "手游", "主机", "Steam", "任天堂", "索尼"]
    },
    "汽车": {
        "sources": [
            {"name": "汽车之家", "url": "https://www.autohome.com.cn/news/", "type": "scrape", "selectors": [".article li h3 a"]},
            {"name": "懂车帝", "url": "https://www.dongchedi.com/", "type": "scrape", "selectors": [".feed-card-title"]},
        ],
        "keywords": ["汽车", "新能源", "电动车", "自动驾驶", "特斯拉", "比亚迪"]
    },
    "教育": {
        "sources": [
            {"name": "多知网", "url": "https://www.duozhi.com/feed", "type": "rss"},
            {"name": "芥末堆", "url": "https://www.jiemodui.com/rss.xml", "type": "rss"},
        ],
        "keywords": ["教育", "培训", "K12", "职业教育", "在线教育", "双减"]
    }
}

# 通用新闻源（跨行业）
GENERAL_NEWS_SOURCES = [
    {"name": "新浪新闻", "url": "https://news.sina.com.cn/rss/", "type": "rss"},
    {"name": "腾讯新闻", "url": "https://r.inews.qq.com/", "type": "rss"},
    {"name": "网易新闻", "url": "http://news.163.com/special/00011K6L/rss_newsattitude.xml", "type": "rss"},
]

INDUSTRY_NEWS_SYSTEM = """你是行业新闻分析专家。根据给定的各行业新闻数据，提炼出：
1. **行业热点趋势**：每个行业当前最受关注的话题、事件
2. **关键事件分析**：重要新闻的背景、影响和关联性
3. **跨行业关联**：不同行业新闻之间的相互影响
4. **营销机会点**：从新闻中发现的品牌营销、内容创作机会

输出要求：按行业分类，每个行业包含3-5个核心新闻点，每个点包含标题、概要、关键词和营销启示。
控制在800字以内，结构清晰，便于后续营销策划参考。"""


async def fetch_rss_feed(url: str, timeout: int = 10) -> List[Dict]:
    """获取RSS订阅源内容 - 使用 xmltodict 替代 feedparser"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
            }
            resp = await client.get(url, headers=headers)
            if resp.status_code == 403:
                _warn_throttled(f"rss_403:{url}", f"RSS获取被拒绝(403) {url}，已跳过（将限频告警）")
                return []
            if resp.status_code != 200:
                _warn_throttled(
                    f"rss_status:{url}",
                    f"RSS获取失败 {url}: HTTP {resp.status_code}，已跳过（将限频告警）",
                )
                return []

            # 某些站点会 200 但返回 HTML/反爬页；先做轻量判定，避免无意义解析报错刷屏
            content_type = (resp.headers.get("content-type") or "").lower()
            raw_text = ""
            try:
                raw_text = resp.text or ""
            except Exception:
                raw_text = ""
            if ("html" in content_type) or (raw_text and not _looks_like_rss_or_xml(raw_text)):
                _warn_throttled(
                    f"rss_not_xml:{url}",
                    f"RSS响应疑似非XML（content-type={content_type or 'unknown'}） {url}，已跳过（将限频告警）",
                )
                return []

            # 使用容错解码 + 宽松解析
            xml_text = _decode_and_sanitize_xml(resp.content)
            feed_data = _safe_xmltodict_parse(xml_text)
            if feed_data is None:
                _warn_throttled(
                    f"rss_xml_parse:{url}",
                    f"XML解析失败 {url}: not well-formed 或内容异常，已跳过（将限频告警）",
                )
                return []

            articles = []

            # 解析 RSS 2.0 格式
            if 'rss' in feed_data and 'channel' in feed_data['rss']:
                channel = feed_data['rss']['channel']
                items = channel.get('item', [])
                if not isinstance(items, list):
                    items = [items] if items else []

                for i, item in enumerate(items[:10]):  # 取最新10条
                    title = item.get('title', '')
                    description = item.get('description', '')
                    link = item.get('link', '')
                    pub_date = item.get('pubDate', '')

                    articles.append({
                        "title": title,
                        "summary": description[:200] if description else "",
                        "link": link,
                        "published": pub_date,
                        "source": urlparse(url).netloc
                    })

            # 解析 Atom 格式
            elif 'feed' in feed_data:
                feed = feed_data['feed']
                entries = feed.get('entry', [])
                if not isinstance(entries, list):
                    entries = [entries] if entries else []

                for i, entry in enumerate(entries[:10]):
                    title = entry.get('title', '')
                    if isinstance(title, dict):
                        title = title.get('#text', '')

                    summary = entry.get('summary', '')
                    if isinstance(summary, dict):
                        summary = summary.get('#text', '')

                    link = entry.get('link', '')
                    if isinstance(link, dict):
                        link = link.get('@href', '')
                    elif isinstance(link, list) and len(link) > 0:
                        link = link[0].get('@href', '')

                    published = entry.get('published', entry.get('updated', ''))

                    articles.append({
                        "title": title,
                        "summary": summary[:200] if summary else "",
                        "link": link,
                        "published": published,
                        "source": urlparse(url).netloc
                    })

            return articles
    except Exception as e:
        logger.warning(f"RSS获取失败 {url}: {e}")
        return []

# 其他函数保持不变...
async def scrape_website(url: str, selectors: List[str], timeout: int = 10) -> List[Dict]:
    """爬取网站新闻（简单版，注意反爬虫）"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.google.com/",
                "DNT": "1"
            }
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = []

            for selector in selectors:
                elements = soup.select(selector)
                for elem in elements[:15]:  # 限制数量
                    title = elem.get_text(strip=True)
                    link = elem.get('href', '')
                    if link and not link.startswith(('http://', 'https://')):
                        link = httpx.URL(url).join(link)

                    if title and len(title) > 5:
                        articles.append({
                            "title": title,
                            "summary": "",
                            "link": link,
                            "published": datetime.now().strftime("%Y-%m-%d"),
                            "source": urlparse(url).netloc
                        })

            # 去重
            seen = set()
            unique_articles = []
            for article in articles:
                key = article["title"]
                if key not in seen:
                    seen.add(key)
                    unique_articles.append(article)

            return unique_articles[:10]
    except Exception as e:
        logger.warning(f"网站爬取失败 {url}: {e}")
        return []

def extract_keywords(text: str, industry_keywords: List[str]) -> List[str]:
    """提取关键词"""
    keywords = []
    text_lower = text.lower()

    # 行业关键词匹配
    for kw in industry_keywords:
        if kw.lower() in text_lower:
            keywords.append(kw)

    # 提取高频词（简单实现）
    words = re.findall(r'[\u4e00-\u9fa5]{2,6}', text)
    from collections import Counter
    word_counts = Counter(words)
    top_words = [word for word, _ in word_counts.most_common(5) if len(word) > 1]

    keywords.extend(top_words[:3])
    return list(set(keywords))[:5]

async def fetch_industry_news(industry: str, config: Dict) -> List[Dict]:
    """获取指定行业的新闻"""
    all_articles = []

    # 获取行业特定新闻源
    for source in config["sources"]:
        try:
            if source["type"] == "rss":
                articles = await fetch_rss_feed(source["url"])
            elif source["type"] == "scrape":
                articles = await scrape_website(
                    source["url"],
                    source.get("selectors", ["h1", "h2", "h3", "a"])
                )
            else:
                continue

            for article in articles:
                article["industry"] = industry
                article["keywords"] = extract_keywords(
                    f"{article['title']} {article['summary']}",
                    config["keywords"]
                )
                all_articles.append(article)

            await asyncio.sleep(1)  # 礼貌延迟
        except Exception as e:
            logger.warning(f"获取{industry}新闻源{source['name']}失败: {e}")

    return all_articles

async def refresh_industry_news_report(
    cache: SmartCache | None = None,
    ai_service: SimpleAIService | None = None,
    web_searcher: WebSearcher | None = None,
) -> str:
    """
    执行行业新闻刷新：
    1. 并行获取各行业新闻
    2. 获取通用新闻
    3. LLM分析处理 → 写入缓存
    """
    cache = cache or SmartCache()
    ai_svc = ai_service or SimpleAIService()

    # 并行获取各行业新闻
    tasks = []
    for industry, config in INDUSTRY_CONFIGS.items():
        tasks.append(fetch_industry_news(industry, config))

    # 获取通用新闻
    general_tasks = []
    for source in GENERAL_NEWS_SOURCES:
        if source["type"] == "rss":
            general_tasks.append(fetch_rss_feed(source["url"]))

    # 等待所有任务完成
    industry_results = await asyncio.gather(*tasks, return_exceptions=True)
    general_results = await asyncio.gather(*general_tasks, return_exceptions=True)

    # 整理结果
    all_articles = []
    for i, (industry, result) in enumerate(zip(INDUSTRY_CONFIGS.keys(), industry_results)):
        if isinstance(result, Exception):
            logger.warning(f"获取{industry}新闻失败: {result}")
            continue
        all_articles.extend(result)

    for result in general_results:
        if isinstance(result, Exception):
            continue
        for article in result:
            article["industry"] = "综合"
            article["keywords"] = extract_keywords(
                f"{article['title']} {article['summary']}",
                []
            )
            all_articles.append(article)

    # 按行业分组
    industry_groups = {}
    for article in all_articles:
        industry = article.get("industry", "其他")
        if industry not in industry_groups:
            industry_groups[industry] = []
        industry_groups[industry].append(article)

    # 构建LLM输入
    context_parts = []
    for industry, articles in industry_groups.items():
        context_parts.append(f"【{industry}行业新闻】")
        for i, article in enumerate(articles[:5], 1):  # 每个行业最多5条
            context_parts.append(
                f"{i}. {article['title']}\n"
                f"   概要：{article['summary'][:100] if article['summary'] else '无'}\n"
                f"   关键词：{', '.join(article['keywords'])}\n"
                f"   来源：{article['source']} | 时间：{article['published']}"
            )
        context_parts.append("")

    context_text = "\n".join(context_parts)

    if not context_text.strip():
        # 如果所有源都失败，使用搜索作为后备
        if web_searcher is None:
            cfg = get_search_config()
            web_searcher = WebSearcher(
                api_key=cfg.get("baidu_api_key"),
                provider=cfg.get("provider", "mock"),
                base_url=cfg.get("baidu_base_url"),
                top_k=cfg.get("baidu_top_k", 20),
            )

        try:
            search_query = "最新行业新闻 科技 金融 娱乐 游戏 汽车 教育 热点"
            results = await web_searcher.search(search_query, num_results=10)
            context_text = web_searcher.format_results_as_context(results)
        except Exception as e:
            logger.warning("行业新闻搜索失败: %s，使用兜底", e)
            context_text = "（新闻获取暂不可用，请基于你对各行业热点的了解作答）"

    user_prompt = f"""【各行业新闻汇总（来源：RSS/网站爬取）】
{context_text[:4000]}

请分析各行业的热点趋势，提炼对营销策划有价值的信息。"""

    messages = [
        SystemMessage(content=INDUSTRY_NEWS_SYSTEM),
        HumanMessage(content=user_prompt),
    ]

    try:
        llm = ai_svc._llm
        raw = await llm.invoke(messages, task_type="analysis", complexity="high")
        news_report = (raw or "").strip()
    except Exception as e:
        logger.warning("行业新闻分析LLM失败: %s", e)
        news_report = (
            "【行业新闻分析报告】\n"
            "科技：AI大模型持续火热，关注AI应用落地\n"
            "金融：政策利好频出，关注数字经济相关板块\n"
            "娱乐：影视作品热度分化，关注口碑传播效应\n"
            "游戏：新游发布频繁，关注用户留存策略\n"
            "汽车：新能源车竞争加剧，关注智能化升级\n"
            "教育：职业教育受关注，关注技能培训需求\n"
            "营销启示：结合行业热点进行内容创作，把握趋势红利"
        )

    # 存储原始数据和分析报告
    payload = {
        "report": news_report,
        "raw_data": all_articles[:50],  # 存储前50条
        "timestamp": datetime.now().isoformat(),
        "industries": list(industry_groups.keys())
    }

    await cache.set(INDUSTRY_NEWS_CACHE_KEY, payload, ttl=TTL_INDUSTRY_NEWS)
    logger.info(f"行业新闻报告已刷新，共{len(all_articles)}条新闻，涵盖{len(industry_groups)}个行业")
    return news_report