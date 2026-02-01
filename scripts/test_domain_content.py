"""
domain/content 模块单元测试：使用 mock ILLMClient 验证分析、生成、评估可独立测试。
"""
import pytest
from domain.content.analyzer import ContentAnalyzer
from domain.content.generator import ContentGenerator
from domain.content.evaluator import ContentEvaluator
from models.request import ContentRequest


class MockLLMClient:
    """Mock LLM 客户端，用于单测不依赖真实 API"""

    async def invoke(self, messages, *, task_type="chat", complexity="medium"):
        content = str(messages)
        if "分析" in content or "semantic_score" in content:
            return '```json\n{"semantic_score": 85, "angle": "年轻群体科技感", "reason": "测试理由"}\n```'
        if "推广" in content or "文案" in content:
            return "这是一段测试生成的推广文案内容。"
        if "打分" in content or "consistency" in content:
            return '{"scores": {"consistency": 8, "creativity": 8, "safety": 9, "platform_fit": 8}, "overall": 8.2, "suggestions": "可再强化卖点"}'
        return "mock response"


@pytest.mark.asyncio
async def test_analyzer_with_mock():
    """分析脑：mock LLM 返回有效 JSON"""
    mock = MockLLMClient()
    analyzer = ContentAnalyzer(mock)
    request = ContentRequest(user_id="u1", brand_name="B", product_desc="P", topic="T")
    result = await analyzer.analyze(request, preference_context=None)
    assert "semantic_score" in result
    assert result["semantic_score"] == 85
    assert "angle" in result


@pytest.mark.asyncio
async def test_generator_with_mock():
    """生成脑：mock LLM 返回文案"""
    mock = MockLLMClient()
    gen = ContentGenerator(mock)
    out = await gen.generate({"semantic_score": 80, "angle": "A", "reason": "R"}, topic="测试")
    assert "推广" in out or "文案" in out or len(out) > 0


@pytest.mark.asyncio
async def test_evaluator_with_mock():
    """评估脑：mock LLM 返回有效评估 JSON"""
    mock = MockLLMClient()
    ev = ContentEvaluator(mock)
    result = await ev.evaluate("测试文案", {"brand_name": "B", "topic": "T", "analysis": ""})
    assert "scores" in result
    assert "overall" in result
    assert result.get("overall_score", 0) >= 0
