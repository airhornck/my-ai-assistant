"""
内容生成域：分析脑、生成脑、评估脑。
各模块可单独开发与测试，依赖 ILLMClient 注入。
"""
from domain.content.analyzer import ContentAnalyzer
from domain.content.generator import ContentGenerator
from domain.content.evaluator import ContentEvaluator

__all__ = ["ContentAnalyzer", "ContentGenerator", "ContentEvaluator"]
