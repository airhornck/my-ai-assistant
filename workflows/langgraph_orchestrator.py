"""
LangGraph 工作流编排器

将「分析 → 拆解 → 预测 → 生成」串成 StateGraph。

设计理念：
- 策略脑负责"做什么"（动态规划步骤 plan）
- LangGraph 负责"怎么做"（编排执行步骤）
- 两者互补：策略脑输出 plan，LangGraph 按 plan 执行各节点

使用示例：
    from workflows.langgraph_orchestrator import create_orchestrator

    orchestrator = create_orchestrator(capabilities)

    # 执行编排
    result = await orchestrator.execute(
        plan=[
            {"step": "analyze", "params": {...}},
            {"step": "decompose", "params": {...}},
            {"step": "predict", "params": {...}},
            {"step": "generate", "params": {...}},
        ],
        state={"user_input": "..."}
    )
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


# =============================================================================
# State 定义
# =============================================================================


@dataclass
class OrchestratorState:
    """
    编排器状态：贯穿整个 StateGraph。

    策略脑输出的 plan 在此流转，每个步骤的输出存入 step_outputs。
    """

    # 输入
    user_input: str = ""
    raw_input: str = ""
    user_id: str = ""
    session_id: str = ""

    # 策略脑规划的步骤
    plan: list[dict[str, Any]] = field(default_factory=list)
    current_step: int = 0

    # 各步骤输出
    step_outputs: list[Any] = field(default_factory=list)

    # 分析结果（可选）
    analysis_result: dict[str, Any] = field(default_factory=dict)

    # 拆解结果（可选）
    decomposition_result: dict[str, Any] = field(default_factory=dict)

    # 预测结果（可选）
    prediction_result: dict[str, Any] = field(default_factory=dict)

    # 生成结果（可选）
    generation_result: dict[str, Any] = field(default_factory=dict)

    # 错误记录
    errors: list[str] = field(default_factory=list)

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 节点函数
# =============================================================================


class OrchestratorNodes:
    """编排器节点：执行具体步骤。"""

    def __init__(self, capabilities: Any) -> None:
        self.caps = capabilities

    async def analyze_node(self, state: OrchestratorState) -> dict:
        """分析节点：调用分析脑或插件。"""
        step = state.plan[state.current_step]
        logger.info(f"执行分析节点: {step}")

        try:
            # TODO: 调用分析脑
            # result = await self.caps.analysis.analyze(...)
            result = {"status": "analyzed", "data": "analysis_output"}

            return {
                "analysis_result": result,
                "step_outputs": state.step_outputs + [result],
            }
        except Exception as e:
            logger.error(f"分析节点失败: {e}")
            return {
                "errors": state.errors + [f"analyze failed: {e}"],
            }

    async def decompose_node(self, state: OrchestratorState) -> dict:
        """拆解节点：调用视频拆解服务。"""
        step = state.plan[state.current_step]
        logger.info(f"执行拆解节点: {step}")

        try:
            # 调用视频拆解 Port
            result = await self.caps.video_decomposition.decompose(
                video_url=step.get("params", {}).get("video_url", ""),
                raw_text=step.get("params", {}).get("raw_text", ""),
            )

            return {
                "decomposition_result": result.to_dict(),
                "step_outputs": state.step_outputs + [result.to_dict()],
            }
        except Exception as e:
            logger.error(f"拆解节点失败: {e}")
            return {
                "errors": state.errors + [f"decompose failed: {e}"],
            }

    async def predict_node(self, state: OrchestratorState) -> dict:
        """预测节点：调用预测模型。"""
        step = state.plan[state.current_step]
        logger.info(f"执行预测节点: {step}")

        try:
            # 基于拆解结果进行预测
            features = state.decomposition_result or {}

            # 爆款预测
            viral_result = await self.caps.prediction.predict_viral(
                features=features,
            )

            # CTR 预测
            ctr_result = await self.caps.prediction.predict_ctr(
                cover_features=features.get("cover_features", {}),
                title=step.get("params", {}).get("title", ""),
            )

            result = {
                "viral_score": viral_result.score,
                "viral_confidence": viral_result.confidence,
                "ctr": ctr_result.ctr,
                "ctr_confidence": ctr_result.confidence,
            }

            return {
                "prediction_result": result,
                "step_outputs": state.step_outputs + [result],
            }
        except Exception as e:
            logger.error(f"预测节点失败: {e}")
            return {
                "errors": state.errors + [f"predict failed: {e}"],
            }

    async def generate_node(self, state: OrchestratorState) -> dict:
        """生成节点：调用生成脑。"""
        step = state.plan[state.current_step]
        logger.info(f"执行生成节点: {step}")

        try:
            # TODO: 调用生成脑
            # result = await self.caps.generation.generate(...)
            result = {"status": "generated", "data": "generation_output"}

            return {
                "generation_result": result,
                "step_outputs": state.step_outputs + [result],
            }
        except Exception as e:
            logger.error(f"生成节点失败: {e}")
            return {
                "errors": state.errors + [f"generate failed: {e}"],
            }

    async def generic_node(self, state: OrchestratorState) -> dict:
        """通用节点：执行任意步骤。"""
        step = state.plan[state.current_step]
        step_name = step.get("step", "")
        logger.info(f"执行通用节点: {step_name}")

        # 根据步骤名分发
        if "analyze" in step_name:
            return await self.analyze_node(state)
        elif "decompose" in step_name:
            return await self.decompose_node(state)
        elif "predict" in step_name:
            return await self.predict_node(state)
        elif "generate" in step_name:
            return await self.generate_node(state)
        else:
            # 未知步骤，跳过
            logger.warning(f"未知步骤: {step_name}")
            return {"step_outputs": state.step_outputs + [{"skipped": step_name}]}


# =============================================================================
# 边函数
# =============================================================================


def should_continue(state: OrchestratorState) -> str:
    """
    判断是否继续执行下一步。

    策略脑规划的 plan 有多步，依次执行；
    如果还有下一步，返回节点名；否则结束。
    """
    if state.current_step < len(state.plan) - 1:
        return "continue"
    return "end"


# =============================================================================
# 编排器类
# =============================================================================


class LangGraphOrchestrator:
    """
    LangGraph 编排器。

    接收策略脑输出的 plan，按图执行各步骤。
    """

    def __init__(self, capabilities: Any) -> None:
        self.capabilities = capabilities
        self.nodes = OrchestratorNodes(capabilities)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """构建 StateGraph。"""
        graph = StateGraph(OrchestratorState)

        # 添加节点
        graph.add_node("analyze", self.nodes.analyze_node)
        graph.add_node("decompose", self.nodes.decompose_node)
        graph.add_node("predict", self.nodes.predict_node)
        graph.add_node("generate", self.nodes.generate_node)
        graph.add_node("generic", self.nodes.generic_node)

        # 设置入口
        graph.set_entry_point("dispatch")

        # 添加调度节点（根据步骤名分发）
        @graph.node
        async def dispatch_node(state: OrchestratorState) -> dict:
            """调度节点：根据当前步骤名决定下一个节点。"""
            if state.current_step >= len(state.plan):
                return {"current_step": -1}  # 结束

            step = state.plan[state.current_step]
            step_name = step.get("step", "").lower()

            if "analyze" in step_name:
                return {"next_node": "analyze"}
            elif "decompose" in step_name:
                return {"next_node": "decompose"}
            elif "predict" in step_name:
                return {"next_node": "predict"}
            elif "generate" in step_name:
                return {"next_node": "generate"}
            else:
                return {"next_node": "generic"}

        graph.add_node("dispatch", dispatch_node)

        # 条件边：dispatch → 具体节点
        def route_dispatch(state: OrchestratorState) -> str:
            next_node = state.metadata.get("next_node", "generic")
            return next_node

        graph.add_conditional_edges(
            "dispatch",
            route_dispatch,
            {
                "analyze": "analyze",
                "decompose": "decompose",
                "predict": "predict",
                "generate": "generate",
                "generic": "generic",
            },
        )

        # 边：各节点 → dispatch（继续下一步）
        for node in ["analyze", "decompose", "predict", "generate", "generic"]:
            graph.add_edge(node, "dispatch")

        # 编译图（带 checkpoint 支持断点续航）
        checkpointer = MemorySaver()
        return graph.compile(checkpointer=checkpointer)

    async def execute(
        self,
        plan: list[dict[str, Any]],
        state: dict[str, Any],
        *,
        thread_id: str = "default",
    ) -> OrchestratorState:
        """
        执行编排。

        :param plan: 策略脑输出的步骤列表
        :param state: 初始状态
        :param thread_id: 线程 ID（用于 checkpoint）
        :return: 最终状态
        """
        # 初始化状态
        initial_state = OrchestratorState(
            user_input=state.get("user_input", ""),
            raw_input=state.get("raw_input", ""),
            user_id=state.get("user_id", ""),
            session_id=state.get("session_id", ""),
            plan=plan,
            current_step=0,
        )

        # 执行图
        config = {"configurable": {"thread_id": thread_id}}

        final_state = None
        async for chunk in self.graph.astream(initial_state, config):
            final_state = chunk

        return final_state


# =============================================================================
# 工厂函数
# =============================================================================


_orchestrator_cache: Optional[LangGraphOrchestrator] = None


def create_orchestrator(
    capabilities: Any,
    *,
    use_cache: bool = True,
) -> LangGraphOrchestrator:
    """
    创建编排器。
    """
    global _orchestrator_cache

    if use_cache and _orchestrator_cache is not None:
        return _orchestrator_cache

    orchestrator = LangGraphOrchestrator(capabilities)

    if use_cache:
        _orchestrator_cache = orchestrator

    return orchestrator


def reset_orchestrator() -> None:
    """重置编排器缓存。"""
    global _orchestrator_cache
    _orchestrator_cache = None
