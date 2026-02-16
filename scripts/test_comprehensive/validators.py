# 结果验证器
import re
import json
from typing import Any, Optional

class Validators:
    """验证测试结果"""
    
    @staticmethod
    def check_api_success(response: dict) -> bool:
        """检查API是否成功返回"""
        return response.get("success") is True
    
    @staticmethod
    def check_intent_match(response: dict, expected_intent: str) -> bool:
        """检查意图是否匹配"""
        actual = response.get("intent", "")
        return actual == expected_intent
    
    @staticmethod
    def check_memory_recall(content: str, keywords: list) -> bool:
        """检查记忆是否被正确回忆"""
        if not content:
            return False
        content = str(content).lower()
        return any(kw.lower() in content for kw in keywords)
    
    @staticmethod
    def check_long_term_memory(content: str, brand_name: str = "", industry: str = "") -> bool:
        """检查长期记忆（我是谁）"""
        if not content:
            return False
        content = str(content)
        if brand_name and brand_name in content:
            return True
        if industry and industry in content:
            return True
        return False
    
    @staticmethod
    def check_context_window(content: str, keywords: list) -> bool:
        """检查上下文窗口（多轮后是否记住关键词）"""
        if not content:
            return False
        content = str(content).lower()
        matched = sum(1 for kw in keywords if kw.lower() in content)
        return matched >= len(keywords) * 0.5  # 至少匹配50%
    
    @staticmethod
    def check_clarification(response: dict) -> bool:
        """检查是否触发了澄清流程"""
        # 澄清时 intent 为 "clarification" 或 data 包含澄清问题
        intent = response.get("intent", "")
        if intent == "clarification":
            return True
        data = response.get("data", "")
        if data and isinstance(data, str):
            clarification_keywords = ["补充", "请告诉我", "品牌", "产品", "主题"]
            return any(kw in data for kw in clarification_keywords)
        return False
    
    @staticmethod
    def check_plugin_response(response: dict, plugin_type: str) -> bool:
        """检查插件是否有响应"""
        # 检查 thinking_process 或 data 中是否有插件相关输出
        thinking = response.get("thinking_process", [])
        data = response.get("data", {})
        
        if isinstance(thinking, list) and len(thinking) > 0:
            return True
        if isinstance(data, dict) and len(data) > 0:
            return True
        return False
    
    @staticmethod
    def check_generation_response(response: dict) -> bool:
        """检查生成内容是否存在"""
        data = response.get("data", {})
        if isinstance(data, dict):
            content = data.get("content", "")
        else:
            content = str(data) if data else ""
        
        # 检查是否有实际内容（不只是空字符串）
        return bool(content and len(str(content).strip()) > 10)
    
    @staticmethod
    def extract_session_id(response: dict) -> Optional[str]:
        """从响应中提取 session_id"""
        return response.get("session_id") or None
    
    @staticmethod
    def count_tokens_estimate(text: str) -> int:
        """估算 token 数量（中英文混合约 1 token = 1.5 字符）"""
        if not text:
            return 0
        text = str(text)
        # 简单估算：中文约 2 字符/token，英文约 4 字符/token
        chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
        english = len(re.findall(r'[a-zA-Z]', text))
        other = len(text) - chinese - english
        return (chinese // 2) + (english // 4) + (other // 3)


class TestResult:
    """测试结果记录"""
    
    def __init__(self, name: str):
        self.name = name
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.token_estimate = 0
        self.errors = []
        self.details = []
    
    def add_success(self, tokens: int = 0, detail: str = ""):
        self.requests += 1
        self.successes += 1
        self.token_estimate += tokens
        if detail:
            self.details.append({"status": "PASS", "detail": detail})
    
    def add_failure(self, error: str, detail: str = ""):
        self.requests += 1
        self.failures += 1
        self.errors.append(error)
        if detail:
            self.details.append({"status": "FAIL", "detail": detail})
    
    @property
    def success_rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return (self.successes / self.requests) * 100
    
    def summary(self) -> dict:
        return {
            "name": self.name,
            "requests": self.requests,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": f"{self.success_rate:.1f}%",
            "token_estimate": self.token_estimate,
            "errors": self.errors[:5],  # 最多显示5个
        }
