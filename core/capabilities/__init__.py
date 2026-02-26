"""
能力中心统一入口：一站式获取所有 Port 实现。

基于环境变量选择具体 Adapter，支持灵活替换。
各能力初始化参数可从 config/capabilities.yaml 读取。

使用示例：
    from core.capabilities import get_capabilities

    # 获取所有能力
    caps = get_capabilities()
    multimodal = caps.multimodal
    prediction = caps.prediction
    ...
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

# 多模态
from core.multimodal.port import IMultimodalPort
from core.multimodal.factory import get_multimodal_port

# 预测模型
from services.prediction.port import IPredictionPort
from services.prediction.factory import get_prediction_port

# 视频拆解
from services.video_decomposition.port import IVideoDecompositionPort
from services.video_decomposition.factory import get_video_decomposition_port

# 样本库
from modules.sample_library.port import SampleLibraryPort
from modules.sample_library.factory import get_sample_library

# 平台规则
from modules.platform_rules.port import PlatformRulesPort
from modules.platform_rules.factory import get_platform_rules

# 知识库
from modules.knowledge_base.port import KnowledgePort
from modules.knowledge_base.factory import get_knowledge_port

# 方法论（待补齐 Port）
from modules.methodology.service import MethodologyService

# 案例模板（待补齐 Port）
from modules.case_template.service import CaseTemplateService

# 数据闭环（待补齐 Port）
from modules.data_loop.service import DataLoopService

if TYPE_CHECKING:
    from cache.smart_cache import SmartCache


@dataclass
class Capabilities:
    """所有能力的统一封装。"""

    multimodal: IMultimodalPort
    prediction: IPredictionPort
    video_decomposition: IVideoDecompositionPort
    sample_library: SampleLibraryPort
    platform_rules: PlatformRulesPort
    knowledge: KnowledgePort

    # 服务类（暂未补 Port）
    methodology: Optional[MethodologyService] = None
    case_template: Optional[CaseTemplateService] = None
    data_loop: Optional[DataLoopService] = None

    def __repr__(self) -> str:
        names = [
            "multimodal",
            "prediction",
            "video_decomposition",
            "sample_library",
            "platform_rules",
            "knowledge",
        ]
        return f"Capabilities({', '.join(names)})"


def get_capabilities(
    *,
    cache: "SmartCache | None" = None,
    multimodal_provider: str | None = None,
    multimodal_api_key: str | None = None,
    prediction_provider: str | None = None,
    video_decomposition_provider: str | None = None,
    sample_library_provider: str | None = None,
    platform_rules_dir: str | None = None,
    use_aliyun_knowledge: bool | None = None,
    session_factory: Any = None,
) -> Capabilities:
    """
    获取所有能力的统一入口。

    参数可通过环境变量或显式传入；环境变量优先级低于显式参数。

    环境变量：
        MULTIMODAL_PROVIDER: mock|aliyun
        PREDICTION_PROVIDER: mock|local|api
        VIDEO_DECOMPOSITION_PROVIDER: mock|full
        SAMPLE_LIBRARY_PROVIDER: mock|redis|pg
        PLATFORM_RULES_DIR: 规则目录
        USE_ALIYUN_KNOWLEDGE: 1 使用阿里云知识库

    示例：
        caps = get_capabilities()
        result = await caps.multimodal.analyze_image(url)
    """
    # 多模态
    multimodal = get_multimodal_port(
        provider=multimodal_provider,
        api_key=multimodal_api_key,
    )

    # 预测模型
    prediction = get_prediction_port(provider=prediction_provider)

    # 视频拆解
    video_decomposition = get_video_decomposition_port(
        provider=video_decomposition_provider,
        multimodal_port=multimodal,
    )

    # 样本库
    sample_library = get_sample_library(cache=cache)

    # 平台规则
    platform_rules = get_platform_rules(rules_dir=platform_rules_dir)

    # 知识库
    knowledge = get_knowledge_port(cache=cache)

    # 方法论（服务类，暂未补 Port）
    methodology = None
    if os.getenv("ENABLE_METHODOLOGY", "1") == "1":
        methodology = MethodologyService()

    # 案例模板（需要 session_factory）
    case_template = None
    if session_factory is not None and os.getenv("ENABLE_CASE_TEMPLATE", "1") == "1":
        case_template = CaseTemplateService(session_factory)

    # 数据闭环（需要 session_factory）
    data_loop = None
    if session_factory is not None and os.getenv("ENABLE_DATA_LOOP", "1") == "1":
        data_loop = DataLoopService(session_factory)

    return Capabilities(
        multimodal=multimodal,
        prediction=prediction,
        video_decomposition=video_decomposition,
        sample_library=sample_library,
        platform_rules=platform_rules,
        knowledge=knowledge,
        methodology=methodology,
        case_template=case_template,
        data_loop=data_loop,
    )


# 单例缓存（延迟初始化）
_capabilities_cache: Optional[Capabilities] = None


def get_capabilities_singleton(
    *,
    cache: "SmartCache | None" = None,
    session_factory: Any = None,
) -> Capabilities:
    """
    获取能力单例（全局缓存）。
    首次调用后，后续调用返回同一实例。
    """
    global _capabilities_cache
    if _capabilities_cache is None:
        _capabilities_cache = get_capabilities(
            cache=cache,
            session_factory=session_factory,
        )
    return _capabilities_cache


def reset_capabilities() -> None:
    """重置能力单例（用于测试或重新配置）。"""
    global _capabilities_cache
    _capabilities_cache = None
