# 项目整体检查报告

> 检查时间：2026-01  
> 范围：接口调用、运行可用性、架构、模块通信、语法、Key 配置

---

## 一、检查结果总览

| 项目 | 状态 | 说明 |
|------|------|------|
| Python 语法 | ✅ 通过 | 所有 .py 语法检查通过 |
| main 导入 | ✅ 通过 | 无循环依赖 |
| 路由 | ✅ 通过 | 无重复（约 13 个） |
| 代码内 Key | ✅ 无硬编码 | 无 sk-、bce-v3/ 等密钥字面量 |
| 接口配置 | ✅ 正常 | api_config 从环境变量读取 |
| 环境加载 | ✅ 正常 | main / frontend 支持 .env、.env.dev 回退 |
| 模块引用 | ✅ 正常 | 统一从 config.api_config 获取 |
| 前后端文件格式 | ✅ 对齐 | ALLOWED_FILE_TYPES 与 SUPPORTED_DOC_EXTENSIONS 一致 |

---

## 二、接口调用与 Key 配置

### 2.1 配置规则

- **统一入口**：`config/api_config.py`
- **Key 来源**：仅环境变量，无代码内默认 Key
- **按供应商/用途划分**：LLM 类、搜索类，详见 `docs/ENV_KEYS_REFERENCE.md`

### 2.2 必需环境变量

| 变量 | 类型 | 用途 | 未配置时 |
|------|------|------|----------|
| DASHSCOPE_API_KEY | LLM | 意图、策略、分析、评估、生成、记忆、嵌入 | 启动/调用报错 |
| DATABASE_URL | 基础设施 | PostgreSQL | 启动失败 |
| REDIS_URL | 基础设施 | 会话、缓存 | 启动失败 |

### 2.3 可选环境变量

| 变量 | 类型 | 用途 | 未配置时 |
|------|------|------|----------|
| SEARCH_PROVIDER | 搜索 | mock \| baidu | 默认 mock |
| BAIDU_SEARCH_API_KEY | 搜索 | 百度千帆 web_search | 搜索使用 mock |
| DEEPSEEK_API_KEY 等 | LLM | 切换 provider 时 | - |

### 2.4 当前 .env 注意点

- 若使用 `.env` 且未配置 `SEARCH_PROVIDER`、`BAIDU_SEARCH_API_KEY`，深度思考中的网络检索会使用 **mock**（模拟数据）
- 需真实搜索时，在 `.env` 中添加 `SEARCH_PROVIDER=baidu` 和 `BAIDU_SEARCH_API_KEY=...`

---

## 三、项目运行可用性

### 3.1 启动前提

1. **PostgreSQL**：`docker compose -f docker-compose.dev.yml up -d`
2. **Redis**：同上
3. **环境变量**：`.env` 或 `.env.dev`，至少配置 `DASHSCOPE_API_KEY`、`DATABASE_URL`、`REDIS_URL`

### 3.2 启动命令

```bash
# 后端
uvicorn main:app --reload

# 前端
python frontend/app_enhanced.py

# 诊断
python check_backend.py
```

### 3.3 主要 API 端点

| 路径 | 方法 | 说明 |
|------|------|------|
| /health | GET | 健康检查 |
| /api/v1/frontend/session/init | GET | 初始化会话 |
| /api/v1/frontend/chat | POST | 聊天（chat / deep 模式） |
| /api/v1/documents/upload | POST | 文档上传 |

---

## 四、架构与模块通信

### 4.1 分层结构

```
main.py (API)
  ├── services/ (ai, input, document, feedback, memory)
  ├── workflows/ (meta_workflow, basic_workflow)
  ├── domain/ (content, memory)
  ├── core/ (ai, intent, document, link, reference, search)
  └── config/ (api_config, media_specs)
```

### 4.2 接口引用链

| 接口 | 引用模块 |
|------|----------|
| intent | core/intent/processor, services/ai_service.reply_casual |
| strategy | dashscope_client, meta_workflow, supplement_extractor, thinking_narrative |
| analysis | domain/content/analyzer, services/ai_service |
| evaluation | domain/content/evaluator, services/ai_service |
| generation_text | domain/content/generators/text_generator |
| memory_optimizer | services/memory_optimizer |
| embedding | services/retrieval_service |
| web_search | workflows/meta_workflow, core/search/web_searcher |

### 4.3 通信路径

- **Chat**：main → InputProcessor → SimpleAIService(reply_casual / generate)
- **Deep**：main → MetaWorkflow(planning → orchestration → compilation)
- **Orchestration**：按规划调用 WebSearcher、MemoryService、ContentAnalyzer、ContentGenerator、ContentEvaluator

---

## 五、验证命令

```bash
# 语法与导入
python scripts/check_syntax.py

# Key 与配置
python -c "
from dotenv import load_dotenv
from pathlib import Path
for _f in ('.env', '.env.dev'):
    if Path(_f).exists():
        load_dotenv(_f)
        break
from config.api_config import get_model_config, get_search_config
print('LLM OK:', bool(get_model_config('intent').get('api_key')))
print('Search:', get_search_config().get('provider'))
"

# 后端连通性
python check_backend.py
```

---

## 六、已知告警与建议

- **Pydantic V1**：LangChain 与 Python 3.14 兼容告警，不影响运行
- **搜索 mock**：未配置 `SEARCH_PROVIDER=baidu` 和 `BAIDU_SEARCH_API_KEY` 时，深度思考中的网络检索使用模拟数据
