# 系统统一接口配置指南

`config/api_config.py` 管理**所有**外部接口（LLM、搜索等）。引用时需注明：**类型**、**服务商**、及类型相关参数。

## 一、接口类型与引用规范

| 类型 | 说明 | 必要参数 |
|------|------|----------|
| llm | 大语言模型（Chat） | provider, model, temperature, max_tokens |
| embedding | 嵌入模型（RAG） | provider, model |
| search | 网络搜索 | provider, top_k |

## 二、服务商配置（PROVIDERS）

API Key 与 Base URL 在此统一管理，环境变量名见 `api_key_env`。

### LLM 类

| 服务商 | api_key_env | 默认 base_url |
|--------|-------------|---------------|
| dashscope | DASHSCOPE_API_KEY | 阿里云百炼 |
| deepseek | DEEPSEEK_API_KEY | https://api.deepseek.com/v1 |
| openai_compatible | CUSTOM_LLM_API_KEY | CUSTOM_LLM_BASE_URL |

### 搜索类

| 服务商 | api_key_env | 默认 base_url |
|--------|-------------|---------------|
| baidu | BAIDU_SEARCH_API_KEY | 百度千帆 web_search |
| mock | 无需 | - |
| serpapi | SERPAPI_API_KEY | SerpAPI（待实现） |

## 三、接口定义与模块映射

### LLM 接口（LLM_INTERFACES）

| 接口 ID | 类型 | provider | model | temperature | max_tokens | 引用模块 |
|---------|------|----------|-------|-------------|------------|----------|
| intent | llm | dashscope | qwen-turbo | 0.3 | 4096 | core/intent/processor, services/ai_service.reply_casual |
| strategy | llm | dashscope | qwen-max | 0.5 | 8192 | core/ai/dashscope_client, workflows/meta_workflow, core/reference/supplement_extractor, workflows/thinking_narrative |
| analysis | llm | dashscope | qwen-max | 0.3 | 8192 | domain/content/analyzer, services/ai_service |
| evaluation | llm | dashscope | qwen-turbo | 0.3 | 4096 | domain/content/evaluator, services/ai_service |
| generation_text | llm | dashscope | qwen3-max | 0.7 | 8192 | domain/content/generators/text_generator, domain/content/generator |
| memory_optimizer | llm | dashscope | qwen-max | 0.3 | 4096 | services/memory_optimizer |
| embedding | llm | dashscope | text-embedding-v3 | - | - | services/retrieval_service |
| generation_image | llm | dashscope | (待配置) | 0.7 | 1024 | domain/content/generators/image_generator |
| generation_video | llm | dashscope | (待配置) | 0.7 | 1024 | domain/content/generators/video_generator |

### 搜索接口（SEARCH_INTERFACES）

| 接口 ID | 类型 | provider | top_k | 引用模块 |
|---------|------|----------|-------|----------|
| web_search | search | baidu/mock | 20 | workflows/meta_workflow, core/search/web_searcher |

## 四、获取配置

```python
from config.api_config import get_interface_config, get_model_config, get_search_config

# 通用（返回含 type、provider 的完整配置）
cfg = get_interface_config("web_search")   # type=search
cfg = get_interface_config("intent")       # type=llm

# LLM 便捷（供 ChatOpenAI）
cfg = get_model_config("generation_text")

# 搜索便捷（供 WebSearcher）
cfg = get_search_config()
```

## 五、环境变量

完整说明见 [ENV_KEYS_REFERENCE.md](./ENV_KEYS_REFERENCE.md)。所有 Key 仅从 .env 配置，按供应商与用途划分。

```bash
# LLM 类
DASHSCOPE_API_KEY=sk-xxx
# DEEPSEEK_API_KEY=sk-xxx
# CUSTOM_LLM_BASE_URL=、CUSTOM_LLM_API_KEY=

# 搜索
SEARCH_PROVIDER=baidu
BAIDU_SEARCH_API_KEY=bce-v3/xxx
# BAIDU_SEARCH_TOP_K=20

# 切换模型
MODEL_GENERATION_TEXT_PROVIDER=deepseek
MODEL_GENERATION_TEXT=deepseek-chat
```

## 六、新增接口

1. 在 `PROVIDERS` 中添加服务商（含 `type`、`base_url`、`api_key_env`）
2. 在 `LLM_INTERFACES` 或 `SEARCH_INTERFACES` 中添加接口定义（含 `provider` 及类型参数）
3. 在 `.env` 中配置对应 Key
