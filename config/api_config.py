"""
系统统一接口配置（api_config）：管理所有外部接口（LLM、搜索等）。
各模块引用时需注明：接口类型、服务商、以及类型相关参数。

引用规范：
- 类型 (type): llm | search | embedding
- 服务商 (provider): 对应 PROVIDERS 中的 key
- LLM 类: provider, model, temperature, max_tokens
- 搜索类: provider, top_k

获取方式：
- get_interface_config(id) -> 通用，含 type/provider
- get_model_config(role) -> LLM 便捷
- get_search_config() -> 搜索便捷
"""
from __future__ import annotations

import os
from typing import Any, Optional

# ===== 接口类型 =====
TYPE_LLM = "llm"
TYPE_SEARCH = "search"
TYPE_EMBEDDING = "embedding"

# ===== 服务商配置（API Key 与 Base URL 统一在此管理）=====
# 每个服务商：base_url、api_key_env（环境变量名）
#
# Key 获取地址（建议配置到 .env，勿将 Key 提交到仓库）：
# 所有 Key 仅从 .env 读取，详见 docs/ENV_KEYS_REFERENCE.md
# - 阿里云: DASHSCOPE_API_KEY
# - DeepSeek: DEEPSEEK_API_KEY，获取 https://platform.deepseek.com/
# - 百度搜索: BAIDU_SEARCH_API_KEY，获取 https://console.bce.baidu.com/qianfan/
# - 自建推理: CUSTOM_LLM_API_KEY、CUSTOM_LLM_BASE_URL

PROVIDERS: dict[str, dict[str, Any]] = {
    # ----- LLM 类 -----
    # 阿里云百炼/通义千问
    "dashscope": {
        "type": TYPE_LLM,
        "base_url": os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    # DeepSeek
    "deepseek": {
        "type": TYPE_LLM,
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    # 自建推理服务（OpenAI 兼容接口）
    "openai_compatible": {
        "type": TYPE_LLM,
        "base_url": os.getenv("CUSTOM_LLM_BASE_URL", ""),
        "api_key_env": "CUSTOM_LLM_API_KEY",
    },
    # ----- 搜索类 -----
    "baidu": {
        "type": TYPE_SEARCH,
        "base_url": os.getenv("BAIDU_SEARCH_BASE_URL", "https://qianfan.baidubce.com/v2/ai_search/web_search"),
        "api_key_env": "BAIDU_SEARCH_API_KEY",
    },
    "mock": {
        "type": TYPE_SEARCH,
        "base_url": "",
        "api_key_env": "",
    },
    "serpapi": {
        "type": TYPE_SEARCH,
        "base_url": "https://serpapi.com/search",
        "api_key_env": "SERPAPI_API_KEY",
    },
}


def get_provider_config(provider_id: str) -> dict[str, Any]:
    """
    获取服务商配置（base_url + api_key）。
    api_key 从环境变量 api_key_env 读取。
    """
    if provider_id not in PROVIDERS:
        raise ValueError(f"未知服务商: {provider_id}，可选: {list(PROVIDERS.keys())}")
    p = dict(PROVIDERS[provider_id])
    env_key = p.get("api_key_env", "")
    key = (os.getenv(env_key) or "").strip() if env_key else ""
    p["api_key"] = key
    return p


# ===== 接口定义（引用时注明类型、服务商、必要参数）=====
# 每个接口下标注【引用模块】，便于快速定位
#
# 模块 -> 接口映射总览：
# | 接口 ID        | 类型   | 引用模块 |
# |----------------|--------|----------|
# | intent         | llm    | core/intent/processor, services/ai_service(reply_casual) |
# | strategy       | llm    | core/ai/dashscope_client, workflows/meta_workflow, core/reference/supplement_extractor, workflows/thinking_narrative |
# | analysis       | llm    | domain/content/analyzer, services/ai_service |
# | evaluation     | llm    | domain/content/evaluator, services/ai_service |
# | generation_text| llm    | domain/content/generators/text_generator, domain/content/generator |
# | memory_optimizer| llm   | services/memory_optimizer |
# | embedding      | llm    | services/retrieval_service |
# | web_search     | search | workflows/meta_workflow, core/search/web_searcher |

# ----- LLM 类：type=llm, provider, model, temperature, max_tokens -----
LLM_INTERFACES: dict[str, dict[str, Any]] = {
    # 意图理解、闲聊回复
    # 引用: core/intent/processor, services/ai_service.reply_casual
    "intent": {
        "provider": os.getenv("MODEL_INTENT_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_INTENT", "qwen-turbo"),
        "temperature": float(os.getenv("MODEL_INTENT_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("MODEL_INTENT_MAX_TOKENS", "4096")),
    },
    # 策略脑：规划、编排、思维链、参考材料提取、活动策划
    # 引用: core/ai/dashscope_client, workflows/meta_workflow, core/reference/supplement_extractor, workflows/thinking_narrative
    "strategy": {
        "provider": os.getenv("MODEL_STRATEGY_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_STRATEGY", "qwen-max"),
        "temperature": float(os.getenv("MODEL_STRATEGY_TEMPERATURE", "0.5")),
        "max_tokens": int(os.getenv("MODEL_STRATEGY_MAX_TOKENS", "8192")),
    },
    # 分析脑：品牌热点关联度分析
    # 引用: domain/content/analyzer, services/ai_service
    "analysis": {
        "provider": os.getenv("MODEL_ANALYSIS_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_ANALYSIS", "qwen-max"),
        "temperature": float(os.getenv("MODEL_ANALYSIS_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("MODEL_ANALYSIS_MAX_TOKENS", "8192")),
    },
    # 评估脑：内容质量评估
    # 引用: domain/content/evaluator, services/ai_service
    "evaluation": {
        "provider": os.getenv("MODEL_EVALUATION_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_EVALUATION", "qwen-turbo"),
        "temperature": float(os.getenv("MODEL_EVALUATION_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("MODEL_EVALUATION_MAX_TOKENS", "4096")),
    },
    # 生成脑-文本：文案、脚本等
    # 引用: domain/content/generators/text_generator, domain/content/generator
    "generation_text": {
        "provider": os.getenv("MODEL_GENERATION_TEXT_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_GENERATION_TEXT", "qwen3-max"),
        "temperature": float(os.getenv("MODEL_GENERATION_TEXT_TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("MODEL_GENERATION_TEXT_MAX_TOKENS", "8192")),
    },
    # 记忆优化：后台用户画像更新
    # 引用: services/memory_optimizer
    "memory_optimizer": {
        "provider": os.getenv("MODEL_MEMORY_OPTIMIZER_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_MEMORY_OPTIMIZER", "qwen-max"),
        "temperature": float(os.getenv("MODEL_MEMORY_OPTIMIZER_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("MODEL_MEMORY_OPTIMIZER_MAX_TOKENS", "4096")),
    },
    # 嵌入模型：RAG 检索
    # 引用: services/retrieval_service
    "embedding": {
        "provider": os.getenv("MODEL_EMBEDDING_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_EMBEDDING", "text-embedding-v3"),
    },
    # 生成脑-图片（占位）
    # 引用: domain/content/generators/image_generator, domain/content/generator
    "generation_image": {
        "provider": os.getenv("MODEL_GENERATION_IMAGE_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_GENERATION_IMAGE", ""),
        "temperature": 0.7,
        "max_tokens": 1024,
    },
    # 生成脑-视频（占位）
    # 引用: domain/content/generators/video_generator, domain/content/generator
    "generation_video": {
        "provider": os.getenv("MODEL_GENERATION_VIDEO_PROVIDER", "dashscope"),
        "model": os.getenv("MODEL_GENERATION_VIDEO", ""),
        "temperature": 0.7,
        "max_tokens": 1024,
    },
}

# ----- 搜索类：type=search, provider, top_k -----
# 引用: workflows/meta_workflow, core/search/web_searcher
SEARCH_INTERFACES: dict[str, dict[str, Any]] = {
    "web_search": {
        "provider": os.getenv("SEARCH_PROVIDER", "mock").strip().lower() or "mock",
        "top_k": int(os.getenv("BAIDU_SEARCH_TOP_K", "20")),
    },
}

# 兼容：MODEL_ROLES 指向 LLM 接口
MODEL_ROLES = LLM_INTERFACES


def _resolve_search_provider() -> str:
    """未配置 Key 时强制 mock。"""
    p = SEARCH_INTERFACES.get("web_search", {}).get("provider", "mock")
    if p == "baidu":
        prov = get_provider_config("baidu")
        if not prov.get("api_key"):
            return "mock"
    return p if p in ("mock", "baidu", "serpapi") else "mock"


def get_interface_config(
    interface_id: str,
    interface_type: Optional[str] = None,
    override: Optional[dict] = None,
) -> dict[str, Any]:
    """
    获取指定接口的完整配置。

    Args:
        interface_id: 接口 ID（如 intent、web_search）
        interface_type: 可选，llm|search|embedding；不传则自动推断
        override: 可选覆盖项

    Returns:
        合并服务商配置后的完整参数字典
    """
    if override is None:
        override = {}

    if interface_id in LLM_INTERFACES:
        cfg = dict(LLM_INTERFACES[interface_id])
        if interface_type and interface_type != TYPE_LLM and interface_type != TYPE_EMBEDDING:
            raise ValueError(f"接口 {interface_id} 为 LLM 类，与指定 type={interface_type} 冲突")
        provider_id = cfg.pop("provider", "dashscope")
        prov = get_provider_config(provider_id)
        if interface_id == "embedding":
            if not prov.get("api_key"):
                raise ValueError(f"嵌入模型需配置 {prov.get('api_key_env', '')}")
            out = {
                "type": TYPE_EMBEDDING,
                "provider": provider_id,
                "model": cfg.get("model", ""),
                "base_url": prov.get("base_url", ""),
                "api_key": prov["api_key"],
            }
        else:
            if not prov.get("api_key"):
                raise ValueError(
                    f"服务商 {provider_id} 的 API Key 未配置。请设置环境变量 {prov.get('api_key_env', '')}。"
                )
            out = {
                "type": TYPE_LLM,
                "provider": provider_id,
                "model": cfg.get("model", ""),
                "base_url": prov.get("base_url", ""),
                "api_key": prov["api_key"],
            }
            if "temperature" in cfg:
                out["temperature"] = cfg["temperature"]
            if "max_tokens" in cfg:
                out["max_tokens"] = cfg["max_tokens"]
        out.update(override)
        return out

    if interface_id in SEARCH_INTERFACES:
        cfg = dict(SEARCH_INTERFACES[interface_id])
        provider_id = _resolve_search_provider()
        if provider_id == "mock":
            out = {
                "type": TYPE_SEARCH,
                "provider": "mock",
                "api_key": None,
                "base_url": "",
                "top_k": cfg.get("top_k", 20),
            }
        else:
            prov = get_provider_config(provider_id if provider_id in PROVIDERS else "baidu")
            out = {
                "type": TYPE_SEARCH,
                "provider": provider_id,
                "api_key": prov.get("api_key"),
                "base_url": prov.get("base_url", ""),
                "top_k": cfg.get("top_k", 20),
            }
        out.update(override)
        return out

    raise ValueError(f"未知接口: {interface_id}，可选 LLM: {list(LLM_INTERFACES.keys())}，搜索: {list(SEARCH_INTERFACES.keys())}")


# ===== LLM 便捷接口 =====

def get_model_config(role: str, override: Optional[dict] = None) -> dict[str, Any]:
    """
    获取 LLM 接口配置。返回 ChatOpenAI 所需字段：model, base_url, api_key, temperature?, max_tokens?
    """
    cfg = get_interface_config(role, TYPE_LLM, override)
    out = {
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "api_key": cfg["api_key"],
    }
    if "temperature" in cfg:
        out["temperature"] = cfg["temperature"]
    if "max_tokens" in cfg:
        out["max_tokens"] = cfg["max_tokens"]
    return out


def get_embedding_config(override: Optional[dict] = None) -> dict[str, Any]:
    """获取嵌入模型配置（RAG RetrievalService）。"""
    return get_model_config("embedding", override)


# ===== 搜索便捷接口 =====

def get_search_config(override: Optional[dict] = None) -> dict[str, Any]:
    """
    获取搜索接口配置。返回 WebSearcher 所需字段：provider, api_key, base_url, top_k。
    """
    cfg = get_interface_config("web_search", TYPE_SEARCH, override)
    return {
        "provider": cfg["provider"],
        "baidu_api_key": cfg.get("api_key"),
        "baidu_base_url": cfg.get("base_url", ""),
        "baidu_top_k": cfg.get("top_k", 20),
    }


# ===== 兼容旧接口 =====

def get_dashscope_api_key() -> str:
    """兼容旧代码：返回 DashScope API Key。"""
    prov = get_provider_config("dashscope")
    key = prov.get("api_key", "")
    if not key:
        raise ValueError(
            "DashScope API Key 未配置。请设置环境变量 DASHSCOPE_API_KEY。"
            "获取地址：https://dashscope.console.aliyun.com/"
        )
    return key


def get_llm_config(override: Optional[dict] = None) -> dict[str, Any]:
    """兼容旧接口：返回 fast/powerful 双模型配置。"""
    intent_cfg = get_model_config("intent")
    strategy_cfg = get_model_config("strategy")
    return {
        "base_url": intent_cfg["base_url"],
        "api_key": intent_cfg["api_key"],
        "fast_model": intent_cfg["model"],
        "powerful_model": strategy_cfg["model"],
        "fast_temperature": intent_cfg.get("temperature", 0.3),
        "powerful_temperature": strategy_cfg.get("temperature", 0.5),
        "max_tokens": max(
            intent_cfg.get("max_tokens", 4096),
            strategy_cfg.get("max_tokens", 8192),
        ),
        **(override or {}),
    }
