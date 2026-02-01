"""
搜索接口配置：兼容层，统一从 config.api_config 读取。
引用 web_search 接口，供 workflows/meta_workflow、core/search/web_searcher 使用。
"""
from __future__ import annotations

# 统一接口配置入口：config/api_config
from config.api_config import (
    get_search_config,
    get_interface_config,
    TYPE_SEARCH,
    SEARCH_INTERFACES,
    PROVIDERS,
)

__all__ = [
    "get_search_config",
    "get_interface_config",
    "get_baidu_search_api_key",
    "get_baidu_search_base_url",
    "get_search_provider",
    "TYPE_SEARCH",
    "SEARCH_INTERFACES",
]


def get_baidu_search_api_key() -> str | None:
    """从统一配置获取百度搜索 API Key。"""
    cfg = get_search_config()
    return cfg.get("baidu_api_key")


def get_baidu_search_base_url() -> str:
    """百度搜索 API 地址。"""
    cfg = get_search_config()
    return cfg.get("baidu_base_url", "https://qianfan.baidubce.com/v2/ai_search/web_search")


def get_search_provider() -> str:
    """获取当前搜索供应商（mock|baidu）。"""
    cfg = get_search_config()
    return cfg.get("provider", "mock")
