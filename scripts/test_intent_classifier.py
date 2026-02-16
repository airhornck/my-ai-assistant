"""
意图分类器测试
测试各种用户输入的意图分类准确性
"""
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class IntentTestCase:
    """意图测试用例"""
    input_text: str
    expected_category: str  # 期望的分类
    expected_intent: Optional[str] = None  # 期望的意图
    description: str = ""


class IntentClassifierTester:
    """意图分类器测试"""

    # 测试用例库
    TEST_CASES = [
        # 闲聊类
        IntentTestCase("你好", "casual", description="简单问候"),
        IntentTestCase("hello", "casual", description="英文问候"),
        IntentTestCase("在吗", "casual", description="询问在否"),
        IntentTestCase("今天天气不错", "casual", description="闲聊"),

        # 诊断类
        IntentTestCase("帮我诊断账号", "diagnosis", description="诊断账号"),
        IntentTestCase("分析一下我的B站", "diagnosis", description="分析账号"),
        IntentTestCase("我的账号有什么问题", "diagnosis", description="账号问题"),
        IntentTestCase("为什么播放量低", "diagnosis", description="原因分析"),

        # 创作类
        IntentTestCase("帮我写文案", "creation", description="写文案"),
        IntentTestCase("生成一篇笔记", "creation", description="生成内容"),
        IntentTestCase("创作脚本", "creation", description="创作脚本"),
        IntentTestCase("写一个短视频脚本", "creation", description="视频脚本"),

        # 热点类
        IntentTestCase("最近有什么热点", "hotspot", description="查询热点"),
        IntentTestCase("B站热门视频", "hotspot", description="热门内容"),
        IntentTestCase("小红书趋势", "hotspot", description="平台趋势"),

        # 建议类
        IntentTestCase("给我一些建议", "suggestion", description="请求建议"),
        IntentTestCase("怎么做更好", "suggestion", description="优化建议"),
        IntentTestCase("应该注意什么", "suggestion", description="注意事项"),

        # 报告类
        IntentTestCase("生成报告", "report", description="生成报告"),
        IntentTestCase("导出数据分析", "report", description="导出数据"),
        IntentTestCase("给我一份报告", "report", description="获取报告"),

        # 工具类
        IntentTestCase("计算CVR", "tool", description="计算工具"),
        IntentTestCase("帮我算一下", "tool", description="计算请求"),
    ]

    def __init__(self):
        self.results = []

    def load_classifier(self):
        """加载意图分类器"""
        try:
            from core.intent.processor import IntentProcessor
            self.processor = IntentProcessor()
            return True
        except ImportError as e:
            print(f"无法导入 IntentProcessor: {e}")
            return False

    async def test_single(self, test_case: IntentTestCase) -> dict:
        """测试单个用例"""
        try:
            t0 = time.time()
            result = await self.processor.classify(test_case.input_text)
            duration = time.time() - t0

            # 检查分类结果
            actual_category = result.get("category", "unknown")
            actual_intent = result.get("intent", "")

            # 判断是否通过
            category_match = actual_category == test_case.expected_category

            # 如果期望具体意图，也检查
            intent_match = True
            if test_case.expected_intent:
                intent_match = actual_intent == test_case.expected_intent

            success = category_match and intent_match

            return {
                "input": test_case.input_text,
                "expected_category": test_case.expected_category,
                "expected_intent": test_case.expected_intent,
                "actual_category": actual_category,
                "actual_intent": actual_intent,
                "success": success,
                "duration": duration,
                "confidence": result.get("confidence", 0),
                "all_intents": result.get("all_intents", [])
            }

        except Exception as e:
            return {
                "input": test_case.input_text,
                "expected_category": test_case.expected_category,
                "success": False,
                "error": str(e)
            }

    async def run_all(self) -> list[dict]:
        """运行所有测试"""
        print(f"开始测试 {len(self.TEST_CASES)} 个用例...")

        results = []
        for i, tc in enumerate(self.TEST_CASES):
            print(f"  [{i+1}/{len(self.TEST_CASES)}] {tc.input_text[:30]}...", end=" ")

            result = await self.test_single(tc)
            results.append(result)

            status = "✓" if result.get("success", False) else "✗"
            expected = tc.expected_category
            actual = result.get("actual_category", "ERROR")
            print(f"{status} 期望:{expected} -> 实际:{actual}")

        # 统计
        passed = sum(1 for r in results if r.get("success", False))
        total = len(results)

        print(f"\n{'='*50}")
        print(f"测试完成: {passed}/{total} 通过 ({passed/total*100:.1f}%)")
        print(f"{'='*50}")

        # 分类统计
        category_stats = {}
        for r in results:
            cat = r.get("expected_category", "unknown")
            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "passed": 0}
            category_stats[cat]["total"] += 1
            if r.get("success", False):
                category_stats[cat]["passed"] += 1

        print("\n按分类统计:")
        for cat, stats in sorted(category_stats.items()):
            rate = stats["passed"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"  {cat}: {stats['passed']}/{stats['total']} ({rate:.1f}%)")

        # 失败用例分析
        failures = [r for r in results if not r.get("success", False)]
        if failures:
            print(f"\n失败用例分析:")
            for r in failures:
                print(f"  - 输入: {r['input']}")
                print(f"    期望: {r['expected_category']}")
                print(f"    实际: {r.get('actual_category', 'ERROR')}")
                if r.get("error"):
                    print(f"    错误: {r['error']}")

        self.results = results
        return results


async def main():
    """主函数"""
    tester = IntentClassifierTester()

    if not tester.load_classifier():
        print("加载分类器失败，尝试直接导入模块...")

        # 尝试不同的导入方式
        try:
            import sys
            sys.path.insert(0, ".")
            from core.intent.processor import IntentProcessor
            processor = IntentProcessor()

            # 测试一个简单用例
            test_input = "帮我诊断账号"
            print(f"测试输入: {test_input}")
            result = await processor.classify(test_input)
            print(f"结果: {result}")

        except Exception as e:
            print(f"导入失败: {e}")
            return

    else:
        results = await tester.run_all()

        # 保存结果
        with open("test_intent_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("\n结果已保存到 test_intent_results.json")


if __name__ == "__main__":
    asyncio.run(main())
