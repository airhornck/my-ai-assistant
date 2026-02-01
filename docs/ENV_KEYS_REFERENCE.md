# 环境变量 Key 参考（按供应商与用途）

所有 API Key **仅**通过 `.env` / `.env.dev` / `.env.prod` 配置，代码中无默认 Key。

## 一、LLM 类接口

| 环境变量 | 供应商 | 用途 | 必填 | 获取地址 |
|----------|--------|------|------|----------|
| DASHSCOPE_API_KEY | 阿里云通义千问 | intent、strategy、analysis、evaluation、generation_text、memory_optimizer、embedding | ✅ | https://dashscope.console.aliyun.com/ |
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

## 三、基础设施

| 环境变量 | 用途 |
|----------|------|
| DATABASE_URL | PostgreSQL 连接串（需 postgresql+asyncpg://） |
| REDIS_URL | Redis 连接串 |

## 四、配置优先级

- **Key 读取**：仅从环境变量读取，无代码内默认值
- **加载顺序**：main 优先加载 `.env`，不存在时加载 `.env.dev`
- **生产**：Docker 使用 `--env-file .env.prod`
