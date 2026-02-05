# 项目整体检查报告

> 检查时间：2026-02  
> 范围：接口调用、运行可用性、架构、模块通信、语法、Key 配置、LangGraph/流式/人工介入/多轮

---

## 一、检查结果总览

| 项目 | 状态 | 说明 |
|------|------|------|
| Python 语法 | ✅ 通过 | 所有 .py 语法检查通过（`python scripts/check_syntax.py`） |
| main 导入 | ✅ 通过 | 无循环依赖 |
| 路由 | ✅ 通过 | 无重复（约 14+ 路由） |
| 代码内 Key | ✅ 无硬编码 | 无 sk-、bce-v3/ 等密钥字面量 |
| 接口配置 | ✅ 正常 | api_config 从环境变量读取；生成脑模型由插件中心 config 管理 |
| 环境加载 | ✅ 正常 | main / frontend 支持 .env、.env.dev、.env.prod 回退 |
| 模块引用 | ✅ 正常 | 统一从 config 获取；workflows → services → domain → core → config 连通 |
| 前后端文件格式 | ✅ 对齐 | ALLOWED_FILE_TYPES 与 SUPPORTED_DOC_EXTENSIONS 一致 |
| 流式/人工介入/多轮 | ✅ 已实现 | 见 LANGGRAPH_LANGSMITH_IMPLEMENTATION.md；thread_id + MemorySaver + interrupt + resume |

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
| /api/v1/frontend/chat | POST | 聊天（支持 stream=true SSE 流式、多轮 thread_id） |
| /api/v1/chat/resume | POST | 人工介入恢复（session_id + human_decision: revise \| skip） |
| /api/v1/analyze-deep、/api/v1/analyze-deep/raw | POST | 深度分析（元工作流） |
| /api/v1/documents/upload | POST | 文档上传 |

---

## 四、架构与模块通信

### 4.1 分层结构

```
main.py (API)
  ├── services/ (ai_service, input_service, document, feedback, memory)
  ├── workflows/ (meta_workflow + analysis_brain_subgraph + generation_brain_subgraph, basic_workflow)
  ├── domain/ (content: analyzer, generator, evaluator；memory)
  ├── core/ (ai, intent, document, link, reference, search, brain_plugin_center)
  ├── plugins/ (分析脑/生成脑插件，经 BrainPluginCenter 注册)
  ├── modules/ (knowledge_base, methodology, case_template)
  └── config/ (api_config, media_specs, search_config)
```

### 4.2 主图与子图（LangGraph）

- **主图**（`workflows/meta_workflow.py`）：planning → router → parallel_retrieval | analyze | generate | evaluate | human_decision | skip | compilation → END；Checkpointer=MemorySaver。
- **分析脑子图**：单节点 run_analysis → ai_svc.analyze(analysis_plugins)，内部插件中心并行 get_output。
- **生成脑子图**：单节点 run_generate → ai_svc.generate(generation_plugins)，内部插件中心顺序 get_output。
- **脑内插件**：仍为插件中心模式（未子图化），见 docs/PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION.md。

### 4.3 接口引用链

| 接口 | 引用模块 |
|------|----------|
| intent | core/intent/processor, services/ai_service.reply_casual |
| planning | meta_workflow.planning_node, ai_svc._llm |
| analysis | domain/content/analyzer + plugin_center.get_output(analysis_plugins) |
| generation | domain/content/generator + plugin_center.get_output(generation_plugins) |
| evaluation | domain/content/evaluator, services/ai_service |
| generation_text | 生成脑插件 text_generator，config 由插件中心 config["models"] 管理 |
| web_search | meta_workflow.parallel_retrieval_node, core/search/web_searcher |
| 知识库 | modules/knowledge_base.factory.get_knowledge_port，编排 kb_retrieve 步骤 + 分析脑 knowledge_base 插件 |

### 4.4 通信路径

- **Chat**：main → InputProcessor → reply_casual 或 build_meta_workflow(initial_state, config={thread_id})；可选 stream=true → astream + SSE。
- **Deep**：main → build_meta_workflow → planning → router → 按 plan 执行 parallel_retrieval / analyze 子图 / generate 子图 / evaluate；若 need_revision → human_decision(interrupt) → 前端调 POST /api/v1/chat/resume。
- **多轮**：同一 session_id 作为 thread_id 传入 config，MemorySaver 持久化状态。

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

---

## 七、Git 上传前总结

### 7.1 架构合理性

- **规划脑**：输出 plan（步骤）+ analysis_plugins / generation_plugins，供编排与前端思考过程展示。
- **编排层**：仅按 plan 与插件列表调度，无任务类型分支；分析脑/生成脑以 LangGraph 子图接入。
- **脑内能力**：方法论、知识库、案例、活动策划等以插件形式在分析脑/生成脑内实现，拼装逻辑在插件中心（如 campaign_context）。

### 7.2 语法与模块连通性

- **语法**：`python scripts/check_syntax.py` 全部通过。
- **连通性**：main → workflows.meta_workflow → analysis/generation 子图 → ai_service → domain.content + BrainPluginCenter；config/api_config、modules/knowledge_base、routers 等引用链正常。

### 7.3 项目可用性

- **启动**：需 PostgreSQL、Redis、.env（DASHSCOPE_API_KEY、DATABASE_URL、REDIS_URL）。
- **入口**：/api/v1/frontend/chat（含 stream、多轮、人工介入 resume）；/api/v1/analyze-deep、/api/v1/analyze-deep/raw。
- **扩展**：新增能力以脑级插件注册，见 docs/PLUGIN_DEVELOPMENT_GUIDE.md。

### 7.4 建议的 Git 提交信息（示例）

```
feat: LangGraph 多脑协同 + 流式/人工介入/多轮

- 元工作流：planning → router → 并行检索/分析子图/生成子图/评估/人工决策/汇总，MemorySaver checkpointer
- 分析脑、生成脑以子图接入；脑内插件保持插件中心模式
- 流式：POST /api/v1/frontend/chat?stream=true，SSE 推送 state
- 人工介入：evaluate 后 need_revision 时 interrupt，POST /api/v1/chat/resume 恢复
- 多轮：config.thread_id=session_id，状态按会话持久化
- 文档：LANGGRAPH_LANGSMITH_IMPLEMENTATION、PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION、PLUGIN_DEVELOPMENT_GUIDE 更新
```
