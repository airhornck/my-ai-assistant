"""
B站热点榜单插件：分析脑的定时插件。
通过 plugin.register(plugin_center, config) 向分析脑插件中心注册。
"""
from plugins.bilibili_hotspot.plugin import register

__all__ = ["register"]
