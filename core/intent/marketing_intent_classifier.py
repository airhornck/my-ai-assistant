"""
营销意图识别器
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.intent.types import INTENT_CASUAL_CHAT, INTENT_FREE_DISCUSSION


@dataclass
class ClassificationResult:
    """分类结果数据类"""

    is_marketing: bool
    confidence: float
    reason: str
    matched_categories: Optional[List[str]] = None
    should_continue_flow: bool = False


@dataclass
class RuleMatchResult:
    """规则匹配结果（含无匹配情况）"""

    is_marketing: Optional[bool]
    confidence: float
    reason: str
    matched_categories: Optional[List[str]] = None


class MarketingIntentClassifier:
    """
    营销意图分类器 - 主类
    用于判断用户输入是否为营销创作意图
    """

    def __init__(self, use_fallback_llm: bool = False):
        self._init_keyword_library()
        self.rule_engine = RuleEngine()
        self.scorer = IntentScorer()
        self.use_fallback_llm = use_fallback_llm
        self.state_manager = ConversationStateManager()

    def _init_keyword_library(self) -> None:
        """初始化关键词库"""
        self.keyword_categories = {
            "action": [
                "推广", "营销", "宣传", "广告", "传播", "曝光",
                "获客", "拉新", "引流", "导流", "引粉",
                "转化", "变现", "成交", "销售", "卖货",
                "运营", "维护", "管理", "操作", "执行",
            ],
            "content": [
                "文案", "脚本", "稿件", "软文", "文章",
                "内容", "素材", "选题", "话题", "标题",
                "视频", "短视频", "长视频", "直播", "图文",
                "笔记", "帖子", "动态", "说说", "微博",
            ],
            "platform": [
                "小红书", "抖音", "快手", "视频号", "B站", "bilibili",
                "知乎", "微博", "公众号", "头条", "百家号",
                "账号", "号", "主页", "页面", "店铺",
            ],
            "growth": [
                "涨粉", "增粉", "吸粉", "圈粉", "粉丝",
                "流量", "热度", "曝光", "推荐", "算法",
                "数据", "指标", "KPI", "ROI", "效果",
            ],
            "ip": [
                "IP", "人设", "形象", "定位",
                "品牌", "口碑", "影响力", "知名度", "权威",
                "标签", "特色", "特点", "风格", "调性",
            ],
            "strategy": [
                "策略", "方案", "计划", "规划", "打法",
                "方法论", "框架", "体系", "结构", "流程",
                "技巧", "方法", "窍门", "秘籍", "攻略",
            ],
            "question": [
                "怎么", "如何", "怎样", "为何", "为什么",
                "哪些", "什么", "哪里", "谁", "哪个",
                "怎么办", "怎么做", "如何做", "怎样做",
            ],
            "operation": [
                "做", "写", "搞", "弄", "整",
                "设计", "策划", "制作", "创建", "建立",
                "优化", "改进", "提升", "调整", "修改",
            ],
        }
        self.keyword_weights = {
            "action": 3.0,
            "strategy": 2.5,
            "ip": 2.0,
            "growth": 2.0,
            "content": 1.5,
            "platform": 1.0,
            "question": 0.5,
            "operation": 0.5,
        }

    def classify(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
    ) -> ClassificationResult:
        """
        主分类函数

        参数:
            user_input: 用户输入的文本
            session_id: 会话ID（可选）
            conversation_history: 对话历史（可选，格式 [{"user": str, "assistant": str, "is_marketing": bool}]）

        返回:
            ClassificationResult对象
        """
        text = (user_input or "").strip()

        if not text:
            return ClassificationResult(
                is_marketing=False,
                confidence=0.5,
                reason="empty_input",
            )

        if self._is_special_command(text):
            return self._handle_special_command(text)

        if session_id and conversation_history:
            self.state_manager.update_session(session_id, conversation_history)

        if session_id:
            flow_state = self.state_manager.get_flow_state(session_id)
            if flow_state.in_creation_flow and not self._is_clear_break(text):
                return ClassificationResult(
                    is_marketing=True,
                    confidence=0.85,
                    reason="context_continuation",
                    should_continue_flow=True,
                )

        rule_result = self.rule_engine.check(text)
        if rule_result.confidence > 0.85 and rule_result.is_marketing is not None:
            return ClassificationResult(
                is_marketing=rule_result.is_marketing,
                confidence=rule_result.confidence,
                reason=f"rule:{rule_result.reason}",
                matched_categories=rule_result.matched_categories,
            )

        score_result = self.scorer.score_intent(
            text, self.keyword_categories, self.keyword_weights
        )

        if score_result["confidence"] > 0.75:
            return ClassificationResult(
                is_marketing=score_result["is_marketing"],
                confidence=score_result["confidence"],
                reason="scoring_algorithm",
                matched_categories=score_result.get("matched_categories"),
            )

        if session_id and self.state_manager.get_flow_state(session_id).in_creation_flow:
            default_marketing = True
            confidence = 0.65
            reason = "context_fallback"
        else:
            default_marketing = False
            confidence = 0.5
            reason = "default_chat"

        if self.use_fallback_llm and confidence < 0.7:
            llm_result = self._llm_fallback(text, conversation_history)
            if llm_result is not None:
                return llm_result

        return ClassificationResult(
            is_marketing=default_marketing,
            confidence=confidence,
            reason=reason,
        )

    def _is_special_command(self, text: str) -> bool:
        """检查是否为特殊命令"""
        special_commands = [
            r"^/创作$",
            r"^/marketing$",
            r"^/营销$",
            r"^/闲聊$",
            r"^/chat$",
            r"^/聊天$",
            r"^/重置$",
            r"^/reset$",
            r"^/clear$",
            r"^/继续$",
            r"^/continue$",
        ]
        return any(re.match(p, text) for p in special_commands)

    def _handle_special_command(self, text: str) -> ClassificationResult:
        """处理特殊命令"""
        if re.match(r"^/(创作|marketing|营销)", text):
            return ClassificationResult(
                is_marketing=True,
                confidence=1.0,
                reason="explicit_command",
                should_continue_flow=False,
            )
        if re.match(r"^/(闲聊|chat|聊天)", text):
            return ClassificationResult(
                is_marketing=False,
                confidence=1.0,
                reason="explicit_command",
            )
        if re.match(r"^/(重置|reset|clear)", text):
            return ClassificationResult(
                is_marketing=False,
                confidence=1.0,
                reason="reset_command",
            )
        if re.match(r"^/(继续|continue)", text):
            return ClassificationResult(
                is_marketing=True,
                confidence=0.9,
                reason="continue_command",
                should_continue_flow=True,
            )
        return ClassificationResult(
            is_marketing=False,
            confidence=0.5,
            reason="unknown_command",
        )

    def _is_clear_break(self, text: str) -> bool:
        """检查是否为明确的流程打断"""
        break_patterns = [
            r"^(不|不要)(用|需要|想).*(了|啦)",
            r"^先(这样|到这|到这里)",
            r"^(好|好的|OK|ok|Ok)(的)?$",
            r"^(先?谢谢|感谢|辛苦)(了|你)?$",
            r"^退出(创作|流程)?$",
        ]
        for pattern in break_patterns:
            if re.match(pattern, text):
                return True
        chat_words = [
            "你好", "在吗", "哈喽", "早上好", "晚上好",
            "天气", "吃饭", "睡觉",
        ]
        return any(w in text for w in chat_words) and len(text) < 10

    def _llm_fallback(
        self,
        text: str,
        history: Optional[List[Dict]] = None,
    ) -> Optional[ClassificationResult]:
        """LLM兜底分类（占位，实际需要调用 LLM API）"""
        return None

    def update_conversation(
        self,
        session_id: str,
        user_input: str,
        ai_response: str,
        is_marketing: bool,
    ) -> None:
        """更新对话状态"""
        self.state_manager.update_turn(
            session_id, user_input, ai_response, is_marketing
        )

    def to_intent(self, result: ClassificationResult) -> str:
        """将分类结果映射到项目意图常量"""
        if result.is_marketing:
            return INTENT_FREE_DISCUSSION
        return INTENT_CASUAL_CHAT


class RuleEngine:
    """规则引擎 - 使用正则和规则进行快速判断"""

    def __init__(self) -> None:
        self.strong_patterns = self._init_strong_patterns()

    def _init_strong_patterns(self) -> List[tuple]:
        """初始化强规则模式: (pattern, is_marketing, confidence, reason)"""
        return [
            (
                r"帮(我|我们|公司)?(做|写|设计|策划|规划|制定|优化).*(方案|策略|计划|内容|文案|脚本)",
                True,
                0.95,
                "direct_instruction",
            ),
            (
                r"请(问)?(如何|怎么|怎样).*(做|写|设计|策划|规划|制定|优化).*",
                True,
                0.93,
                "how_to_instruction",
            ),
            (
                r".*(推广|营销|宣传|广告|获客|引流|变现).*(方案|策略|计划|方法|技巧|怎么做)",
                True,
                0.94,
                "promotion_related",
            ),
            (r".*怎么(推广|营销|宣传|广告|获客|引流).*", True, 0.92, "how_to_promote"),
            (r".*如何(推广|营销|宣传|广告|获客|引流).*", True, 0.92, "how_to_promote"),
            (
                r".*(小红书|抖音|视频号|B站|快手|知乎|微博).*(运营|账号|IP|人设|打造)",
                True,
                0.93,
                "platform_operation",
            ),
            (
                r".*做(小红书|抖音|视频号|B站|快手|知乎|微博).*(账号|IP|内容)",
                True,
                0.93,
                "platform_content",
            ),
            (
                r".*(写|创作|制作|设计).*(文案|脚本|内容|帖子|笔记|视频|封面|标题)",
                True,
                0.91,
                "content_creation",
            ),
            (
                r".*(文案|脚本|内容|标题|封面).*怎么(写|做|设计)",
                True,
                0.92,
                "how_to_create",
            ),
            (
                r".*(涨粉|增粉|引流|变现|转化|成交).*(方法|技巧|策略|怎么|如何)",
                True,
                0.93,
                "growth_method",
            ),
            (r".*怎么(涨粉|增粉|引流|变现|转化|成交).*", True, 0.91, "how_to_grow"),
            (
                r".*(个人IP|人设|个人品牌|账号定位).*(打造|建立|设定|怎么|如何)",
                True,
                0.94,
                "ip_building",
            ),
            (r".*打造(个人IP|人设|个人品牌|账号定位).*", True, 0.94, "build_ip"),
            (
                r".*(如何|怎么).*打造.*(IP|人设|变现|品牌).*",
                True,
                0.92,
                "how_to_build_ip",
            ),
            (
                r".*(我)?(想|要|打算).*(推广|营销|宣传|引流|变现).*",
                True,
                0.90,
                "want_to_promote",
            ),
            (
                r".*(营销|推广|文案|品牌).*(什么|怎么|如何|是).*",
                True,
                0.88,
                "marketing_question",
            ),
            (
                r".*(直播|短视频|图文|社群|私域).*(怎么做|如何做|策略|方案)",
                True,
                0.92,
                "specific_action",
            ),
            (
                r".*做(直播|短视频|图文|社群|私域).*(内容|活动|策划)",
                True,
                0.91,
                "do_specific_action",
            ),
            (r"^(你好|在吗|哈喽|哈啰|嗨).*$", False, 0.90, "greeting"),
            (r"^.*(早上好|中午好|晚上好|早安|午安|晚安).*$", False, 0.85, "time_greeting"),
            (r"^.*(谢谢|感谢|辛苦).*$", False, 0.80, "thanks"),
            (r"^.*(再见|拜拜|下次聊|下次见).*$", False, 0.90, "goodbye"),
            (r"^.*(天气|吃饭|睡觉|休息|聊天).*$", False, 0.75, "small_talk"),
        ]

    def check(self, text: str) -> RuleMatchResult:
        """规则检查"""
        text_lower = text.lower()
        for pattern, is_marketing, confidence, reason in self.strong_patterns:
            if re.search(pattern, text_lower):
                matched = self._extract_categories_from_pattern(pattern, text_lower)
                return RuleMatchResult(
                    is_marketing=is_marketing,
                    confidence=confidence,
                    reason=f"rule_{reason}",
                    matched_categories=matched,
                )
        return RuleMatchResult(
            is_marketing=None,
            confidence=0.0,
            reason="no_rule_match",
        )

    def _extract_categories_from_pattern(self, pattern: str, text: str) -> List[str]:
        """从规则模式中提取类别"""
        categories: List[str] = []
        if "推广" in pattern or "营销" in pattern:
            categories.append("action")
        if "小红书" in pattern or "抖音" in pattern:
            categories.append("platform")
        if "文案" in pattern or "内容" in pattern:
            categories.append("content")
        if "涨粉" in pattern or "引流" in pattern:
            categories.append("growth")
        if "IP" in pattern or "人设" in pattern:
            categories.append("ip")
        return list(set(categories))


class IntentScorer:
    """意图评分器 - 基于关键词组合和权重评分"""

    def score_intent(
        self,
        text: str,
        keyword_categories: Dict[str, List[str]],
        keyword_weights: Dict[str, float],
    ) -> Dict[str, Any]:
        """计算意图评分"""
        text_lower = text.lower()
        matched_categories: set = set()
        category_counts: Dict[str, int] = {}

        for category, keywords in keyword_categories.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    matched_categories.add(category)
                    category_counts[category] = category_counts.get(category, 0) + 1

        base_score = 0.0
        for category in matched_categories:
            weight = keyword_weights.get(category, 1.0)
            count = category_counts.get(category, 1)
            base_score += weight * count

        pattern_bonus = 0.0
        if len(matched_categories) >= 2:
            pattern_bonus += 0.5
        if len(matched_categories) >= 3:
            pattern_bonus += 1.0
        if {"action", "question"}.issubset(matched_categories):
            pattern_bonus += 1.0
        if {"action", "platform"}.issubset(matched_categories):
            pattern_bonus += 1.0
        if {"ip", "strategy"}.issubset(matched_categories):
            pattern_bonus += 1.0

        if self._is_small_talk(text_lower):
            pattern_bonus -= 2.0

        final_score = base_score * 0.1 + pattern_bonus
        normalized_score = min(1.0, max(0.0, final_score / 5.0))
        is_marketing = normalized_score >= 0.6

        return {
            "score": normalized_score,
            "is_marketing": is_marketing,
            "confidence": normalized_score,
            "matched_categories": list(matched_categories),
            "base_score": base_score,
            "pattern_bonus": pattern_bonus,
        }

    def _is_small_talk(self, text: str) -> bool:
        """判断是否为闲聊"""
        patterns = [
            r"^你好.*",
            r"^在吗.*",
            r"^哈喽.*",
            r"^嗨.*",
            r".*(早上|中午|晚上)好.*",
            r".*(早安|午安|晚安).*",
            r".*(谢谢|感谢|辛苦).*$",
            r".*(再见|拜拜|下次聊).*",
            r"^([你您]好|hi|hello)[!！。，,. ]*$",
            r"^.*(今天|明天|昨天).*(天气|温度).*$",
            r"^.*(吃|喝).*(饭|水|茶|咖啡).*$",
        ]
        return any(re.match(p, text) for p in patterns)


class ConversationStateManager:
    """对话状态管理器"""

    def __init__(self) -> None:
        self.sessions: Dict[str, SessionState] = {}

    def update_session(self, session_id: str, history: List[Dict]) -> None:
        """更新会话状态"""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id)
        self.sessions[session_id].update_from_history(history)

    def update_turn(
        self,
        session_id: str,
        user_input: str,
        ai_response: str,
        is_marketing: bool,
    ) -> None:
        """更新对话轮次"""
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id)
        self.sessions[session_id].add_turn(user_input, ai_response, is_marketing)

    def get_flow_state(self, session_id: str) -> "FlowState":
        """获取流程状态"""
        if session_id in self.sessions:
            return self.sessions[session_id].get_flow_state()
        return FlowState()


class SessionState:
    """会话状态"""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.turns: List[Dict] = []
        self.mode = "chat"
        self.creation_start_time: Optional[float] = None
        self.consecutive_chat_turns = 0

    def update_from_history(self, history: List[Dict]) -> None:
        """从历史记录更新状态"""
        if not history:
            return
        marketing_turns = sum(
            1 for t in history[-5:] if t.get("is_marketing", False)
        )
        chat_turns = len(history[-5:]) - marketing_turns
        self.mode = "creation" if marketing_turns > chat_turns else "chat"
        if self.mode == "creation":
            self.consecutive_chat_turns = 0

    def add_turn(
        self,
        user_input: str,
        ai_response: str,
        is_marketing: bool,
    ) -> None:
        """添加对话轮次"""
        self.turns.append({
            "user_input": user_input,
            "ai_response": ai_response,
            "is_marketing": is_marketing,
            "timestamp": time.time(),
        })
        if is_marketing:
            self.mode = "creation"
            self.consecutive_chat_turns = 0
            if self.creation_start_time is None:
                self.creation_start_time = time.time()
        else:
            if self.mode == "creation":
                self.consecutive_chat_turns += 1
                if self.consecutive_chat_turns >= 3:
                    self.mode = "chat"
                    self.creation_start_time = None

    def get_flow_state(self) -> "FlowState":
        """获取流程状态"""
        return FlowState(
            in_creation_flow=self.mode == "creation",
            consecutive_chat_turns=self.consecutive_chat_turns,
            creation_duration=(
                time.time() - self.creation_start_time
                if self.creation_start_time
                else 0
            ),
            total_turns=len(self.turns),
        )


@dataclass
class FlowState:
    """流程状态数据类"""

    in_creation_flow: bool = False
    consecutive_chat_turns: int = 0
    creation_duration: float = 0.0
    total_turns: int = 0
