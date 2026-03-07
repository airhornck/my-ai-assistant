"""
测试行业新闻与B站榜单插件
"""
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cache.smart_cache import SmartCache
from services.industry_news_refresh import refresh_industry_news_report
from services.bilibili_multi_rankings_refresh import refresh_bilibili_multi_rankings_report
from plugins.industry_news_bilibili_rankings.plugin import register
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_SCHEDULED

async def test_refresh_functions():
    """测试刷新功能"""
    print("测试行业新闻刷新...")
    try:
        industry_report = await refresh_industry_news_report()
        print(f"行业新闻报告长度: {len(industry_report)} 字符")
        print(f"前200字符: {industry_report[:200]}...")
    except Exception as e:
        print(f"行业新闻刷新失败: {e}")

    print("\n测试B站多榜单刷新...")
    try:
        bilibili_report = await refresh_bilibili_multi_rankings_report()
        print(f"B站榜单报告长度: {len(bilibili_report)} 字符")
        print(f"前200字符: {bilibili_report[:200]}...")
    except Exception as e:
        print(f"B站多榜单刷新失败: {e}")

async def test_plugin_registration():
    """测试插件注册"""
    print("\n测试插件注册...")
    try:
        plugin_center = BrainPluginCenter("analysis")
        cache = SmartCache()

        # 模拟配置
        config = {
            "cache": cache,
            "ai_service": None  # 实际使用时需要传入
        }

        # 注册插件
        register(plugin_center, config)

        # 检查插件是否注册成功
        if plugin_center.has_plugin("industry_news_bilibili_rankings"):
            print("✓ 插件注册成功")

            # 测试插件输出
            context = {"analysis": {}}
            output = await plugin_center.get_output("industry_news_bilibili_rankings", context)
            print(f"✓ 插件输出获取成功，包含键: {list(output.get('analysis', {}).keys())}")
        else:
            print("✗ 插件注册失败")

    except Exception as e:
        print(f"插件测试失败: {e}")

async def test_cache_storage():
    """测试缓存存储"""
    print("\n测试缓存存储...")
    try:
        cache = SmartCache()

        # 测试行业新闻缓存
        test_data = {
            "report": "测试行业新闻报告",
            "raw_data": [{"title": "测试新闻", "industry": "科技"}],
            "timestamp": "2024-01-01T00:00:00",
            "industries": ["科技", "金融"]
        }

        await cache.set("test_industry_news", test_data, ttl=60)
        retrieved = await cache.get("test_industry_news")

        if retrieved and retrieved.get("report") == "测试行业新闻报告":
            print("✓ 缓存存储测试通过")
        else:
            print("✗ 缓存存储测试失败")

    except Exception as e:
        print(f"缓存测试失败: {e}")

async def test_xmltodict():
    """测试xmltodict是否能正常解析RSS"""
    print("\n测试xmltodict解析RSS...")
    try:
        import xmltodict
        import httpx

        # 测试解析一个简单的RSS
        test_xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>Test RSS</title>
                <item>
                    <title>Test Article 1</title>
                    <description>This is a test article</description>
                    <link>https://example.com/1</link>
                    <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
                </item>
            </channel>
        </rss>'''

        data = xmltodict.parse(test_xml)
        if 'rss' in data and 'channel' in data['rss']:
            print("✓ xmltodict解析RSS成功")
        else:
            print("✗ xmltodict解析RSS失败")

    except Exception as e:
        print(f"xmltodict测试失败: {e}")

async def main():
    """运行所有测试"""
    print("开始测试行业新闻与B站榜单插件...")
    print("=" * 50)

    await test_xmltodict()
    await test_refresh_functions()
    await test_plugin_registration()
    await test_cache_storage()

    print("\n" + "=" * 50)
    print("测试完成")

if __name__ == "__main__":
    asyncio.run(main())