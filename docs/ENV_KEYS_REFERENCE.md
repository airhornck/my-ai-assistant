# 环境变量 Key 参考（按供应商与用途）

所有 API Key **仅**通过 `.env` / `.env.dev` / `.env.prod` 配置，代码中无默认 Key。

## 一、LLM 类接口

| 环境变量 | 供应商 | 用途 | 必填 | 获取地址 |
|----------|--------|------|------|----------|
| DASHSCOPE_API_KEY | 阿里云通义千问 | intent、strategy、analysis、evaluation、generation_text、thinking_narrative、memory_optimizer、embedding | ✅ | https://dashscope.console.aliyun.com/ |
| DASHSCOPE_BASE_URL | 阿里云 | 覆盖默认 Base URL | 否 | - |
| DEEPSEEK_API_KEY | DeepSeek | 同上（当 MODEL_xxx_PROVIDER=deepseek） | 按需 | https://platform.deepseek.com/ |
| DEEPSEEK_BASE_URL | DeepSeek | 覆盖默认 Base URL | 否 | - |
| CUSTOM_LLM_API_KEY | 自建推理 | 同上（当 MODEL_xxx_PROVIDER=openai_compatible） | 按需 | - |
| CUSTOM_LLM_BASE_URL | 自建推理 | 自建服务地址 | 按需 | - |

## 二、搜索类接口

| 环境变量 | 供应商 | 用途 | 必填 | 获取地址 |
|----------|--------|------|------|----------|
| SEARCH_PROVIDER | - | mock \| baidu \| serpapi | 否 | 默认 mock |
| BAIDU_SEARCH_API_KEY | 百度千帆 | web_search（当 SEARCH_PROVIDER=baidu） | 按需 | https://console.bce.baidu.com/qianfan/ |
| BAIDU_SEARCH_BASE_URL | 百度 | 覆盖默认 API 地址 | 否 | - |
| BAIDU_SEARCH_TOP_K | 百度 | 每页条数 | 否 | 默认 20 |
| SERPAPI_API_KEY | SerpAPI | web_search（当 SEARCH_PROVIDER=serpapi） | 按需 | https://serpapi.com/ |

## 三、知识库（生产对接阿里云百炼）

| 环境变量 | 用途 | 必填 |
|----------|------|------|
| USE_ALIYUN_KNOWLEDGE | 设为 1 时使用阿里云百炼知识库检索 | 否，默认本地向量 |
| ALIYUN_BAILIAN_WORKSPACE_ID | 百炼业务空间 ID | 使用阿里云知识库时必填 |
| ALIYUN_BAILIAN_INDEX_ID | 百炼知识库索引 ID | 使用阿里云知识库时必填 |

未配置上述三项时，知识库模块使用本地 `RetrievalService`（KNOWLEDGE_DIR / KNOWLEDGE_VECTOR_DIR）。

## 四、基础设施

| 环境变量 | 用途 |
|----------|------|
| DATABASE_URL | PostgreSQL 连接串（需 postgresql+asyncpg://） |
| REDIS_URL | Redis 连接串 |

## 五、可观测（LangSmith / LangChain Tracing）

| 环境变量 | 用途 |
|----------|------|
| LANGCHAIN_TRACING_V2 | 设为 `true` 时启用 LangSmith 追踪（LangGraph 元工作流、各脑子图、LLM 调用等） |
| LANGCHAIN_API_KEY | LangSmith API Key（启用追踪时必填） |
| LANGCHAIN_PROJECT | LangSmith 项目名（可选，用于区分环境） |

详见 [LANGGRAPH_LANGSMITH_IMPLEMENTATION.md](./LANGGRAPH_LANGSMITH_IMPLEMENTATION.md)。

## 六、LLM 模型覆盖（可选）

| 环境变量 | 用途 | 默认 |
|----------|------|------|
| MODEL_STRATEGY | 策略脑（规划）所用模型 | `qwen-turbo` |
| MODEL_STRATEGY_PROVIDER | 策略脑接口的 provider | `dashscope` |
| MODEL_INTENT | 意图理解/闲聊所用模型 | `qwen-turbo` |
| MODEL_ANALYSIS | 分析脑所用模型 | `qwen-max` |
| MODEL_EVALUATION | 评估脑所用模型 | `qwen-turbo` |
| MODEL_GENERATION_TEXT | 生成脑文本所用模型 | `qwen3-max` |

## 七、性能与体验（可选）

| 环境变量 | 用途 |
|----------|------|
| USE_SIMPLE_THINKING_NARRATIVE | 设为 `1` 或 `true` 时，汇总阶段不再调用 LLM 生成「思考过程叙述」，改为步骤列表拼接，可节省约 10–25 秒；**默认不设或为 0** 则使用 LLM 叙述（thinking_narrative 接口，默认 qwen-turbo） |
| MODEL_THINKING_NARRATIVE | 思维链叙述所用模型，默认 `qwen-turbo`；可改为 `qwen-max` 等（同 provider 下） |
| MODEL_THINKING_NARRATIVE_PROVIDER | 思维链叙述接口的 provider，默认 `dashscope` |

## 八、配置优先级

- **Key 读取**：仅从环境变量读取，无代码内默认值
- **加载顺序**：main 优先加载 `.env`，不存在时加载 `.env.dev`
- **生产**：Docker 使用 `--env-file .env.prod`
