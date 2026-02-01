"""
链接解析模块：从对话中提取 URL 并抓取网页内容。
"""
from core.link.parser import extract_urls, fetch_link_context

__all__ = ["extract_urls", "fetch_link_context"]
