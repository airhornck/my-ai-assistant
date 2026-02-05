# 项目文件说明与架构关系（新人必读）

> 面向完全不了解项目的同事，说明每个目录/文件的作用及相互调用关系。

---

## 一、项目概述

**my-ai-assistant** 是一个 AI 营销助手后端服务，主要能力：

- **闲聊**：打招呼、寒暄、简单问答
- **创作**：根据用户需求生成营销文案、活动方案等，并做质量评估
- **多轮对话**：记忆品牌/产品/话题，支持采纳建议、风格改写等

采用「三脑协同」架构：**策略脑**规划步骤 → **分析脑**分析热点与品牌关联 → **生成脑**产出内容 → **评估脑**打分建议。

---

## 二、整体架构图（调用关系）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户请求入口                                     │
│  POST /api/v1/frontend/chat  （main.py）                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  输入处理层                                                                   │
│  services/input_service.py (InputProcessor)                                  │
│  core/intent/processor.py, feedback_classifier.py                            │
│  → 意图识别、澄清、反馈分类（闲聊 vs 创作 vs 采纳建议）                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  工作流层（核心）                                                              │
│  workflows/meta_workflow.py (策略脑 + 编排)                                   │
│    planning_node → router → parallel_retrieval / analyze / generate /       │
│    evaluate / casual_reply / compilation                                     │
│  workflows/analysis_brain_subgraph.py (分析脑子图)                            │
│  workflows/generation_brain_subgraph.py (生成脑子图)                          │
│  workflows/follow_up_suggestion.py (后续建议)                                │
│  workflows/thinking_narrative.py (思维链叙述)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
          ┌─────────────────────────────┼─────────────────────────────┐
          ▼                             ▼                             ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  services/       │         │  domain/content/  │         │  modules/        │
│  ai_service      │         │  analyzer         │         │  knowledge_base  │
│  memory_service  │         │  generator        │         │  methodology     │
│  document_svc    │         │  evaluator        │         │  case_template   │
└──────────────────┘         └──────────────────┘         └──────────────────┘
          │                             │                             │
          ▼                             ▼                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  基础设施层                                                                   │
│  core/ai (LLM 调用), config/ (配置), database.py, cache/, memory/            │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、根目录文件说明

| 文件 | 说明 |
|------|------|
| **main.py** | FastAPI 应用入口，定义所有 API 路由（聊天、分析、文档上传、会话管理等） |
| **database.py** | 数据库模型与连接（PostgreSQL，SQLAlchemy 异步） |
| **check_backend.py** | 健康检查脚本，验证数据库、Redis、工作流是否可用 |
| **requirements.txt** | Python 依赖清单 |
| **Dockerfile** | 生产镜像构建 |
| **docker-compose.dev.yml** | 开发环境（PostgreSQL + Redis + 应用） |
| **docker-compose.prod.yml** | 生产环境编排 |
| **.env.prod.example** | 环境变量示例（不含真实 Key） |
| **README.md** | 项目简介与快速链接 |
| **START_HERE.md** | 快速启动步骤 |
| **TROUBLESHOOTING.md** | 常见问题排查 |

---

## 四、各目录说明

### 4.1 config/ — 配置

| 文件 | 说明 |
|------|------|
| **api_config.py** | LLM 接口配置（intent、strategy、analysis、evaluation、generation_text 等），从环境变量读取 |
| **search_config.py** | 搜索接口配置（百度/SerpAPI 等） |
| **generator_config.py** | 生成器相关配置 |
| **media_specs.py** | 各平台（B站、小红书、抖音等）的生成规范与澄清逻辑 |

### 4.2 core/ — 核心能力（可独立复用）

| 路径 | 说明 |
|------|------|
| **ai/dashscope_client.py** | 阿里云 DashScope LLM 客户端，按 task_type 路由到不同模型 |
| **ai/port.py** | LLM 接口抽象（ILLMClient） |
| **intent/processor.py** | 意图识别处理器，调用 LLM 判断意图（闲聊/创作/文档查询等） |
| **intent/feedback_classifier.py** | 创作结果后的反馈分类：采纳建议 / 模糊评价 / 寒暄 |
| **intent/marketing_intent_classifier.py** | 营销意图细分类 |
| **intent/types.py** | 意图相关类型定义 |
| **document/parser.py** | 文档解析（PDF、DOCX、PPTX 等） |
| **document/storage.py** | 文档存储 |
| **document/session_binding.py** | 文档与会话绑定 |
| **link/parser.py** | 链接内容提取 |
| **search/web_searcher.py** | 网络搜索（百度千帆等） |
| **reference/supplement_extractor.py** | 参考材料补充提取 |
| **brain_plugin_center.py** | 脑级插件中心，管理分析脑/生成脑的插件加载与调度 |
| **plugin_bus.py** | 事件总线（DocumentQueryEvent 等） |
| **plugin_capabilities.py** | 插件能力描述，供「后续建议」使用 |
| **plugin_registry.py** | 工作流插件注册表 |
| **task_plugin_registry.py** | 任务类型 → 分析/生成插件映射 |

### 4.3 workflows/ — 工作流（LangGraph）

| 文件 | 说明 |
|------|------|
| **meta_workflow.py** | 元工作流：策略脑 + 编排 + 汇总，入口为 `build_meta_workflow()` |
| **analysis_brain_subgraph.py** | 分析脑子图（热点、知识库、品牌关联等） |
| **generation_brain_subgraph.py** | 生成脑子图（按插件调用文本/图片/视频生成） |
| **evaluation_node.py** | 评估节点：对生成内容打分、给建议 |
| **follow_up_suggestion.py** | 后续建议：根据本轮结果生成引导话术 |
| **thinking_narrative.py** | 思维链叙述：将执行记录撰写成连贯思考过程 |
| **strategy_orchestrator.py** | 活动策划编排（方法论 + 知识库 + 案例） |
| **campaign_planner.py** | 活动方案规划 |
| **basic_workflow.py** | 简化工作流（analyze → generate → evaluate），供 create_workflow |
| **types.py** | MetaState 等工作流状态类型 |

### 4.4 services/ — 服务层（门面与编排）

| 文件 | 说明 |
|------|------|
| **ai_service.py** | AI 服务门面：整合 analyze、generate、evaluate、reply_casual |
| **input_service.py** | 输入处理：意图识别、澄清、文档上下文合并 |
| **memory_service.py** | 记忆服务：品牌事实、用户画像、近期交互 |
| **memory_optimizer.py** | 后台异步更新用户画像 |
| **document_service.py** | 文档上传、绑定、查询 |
| **feedback_service.py** | 反馈记录与触发优化 |
| **retrieval_service.py** | 向量检索（RAG） |
| **bilibili_hotspot_refresh.py** | B站热点榜单定时刷新 |

### 4.5 domain/ — 领域层

| 路径 | 说明 |
|------|------|
| **content/analyzer.py** | 内容分析：品牌热点关联度、切入点 |
| **content/generator.py** | 内容生成编排，调用各 generator 插件 |
| **content/evaluator.py** | 内容评估：多维度打分 |
| **content/generators/text_generator.py** | 文本生成 |
| **content/generators/image_generator.py** | 图片生成（占位） |
| **content/generators/video_generator.py** | 视频生成（占位） |
| **memory/** | 领域内记忆模型（由 services/memory_service 使用） |

### 4.6 plugins/ — 脑级插件实现

| 插件 | 所属脑 | 说明 |
|------|--------|------|
| **bilibili_hotspot** | 分析脑 | B站热点榜单 |
| **campaign_context** | 分析脑 | 活动策划上下文 |
| **methodology** | 分析脑 | 营销方法论 |
| **knowledge_base** | 分析脑 | 知识库检索 |
| **case_library** | 分析脑 | 案例库检索 |
| **text_generator** | 生成脑 | 文本生成 |
| **image_generator** | 生成脑 | 图片生成（占位） |
| **video_generator** | 生成脑 | 视频生成（占位） |
| **campaign_plan_generator** | 生成脑 | 活动方案生成 |

### 4.7 modules/ — 独立业务模块

| 路径 | 说明 |
|------|------|
| **knowledge_base/** | 知识库：本地向量 / 阿里云百炼，factory 提供统一 port |
| **methodology/** | 营销方法论服务 |
| **case_template/** | 案例模板与打分 |
| **data_loop/** | 数据闭环相关 |

### 4.8 models/ — 请求/响应模型

| 文件 | 说明 |
|------|------|
| **request.py** | ContentRequest、FrontendChatRequest 等 Pydantic 模型 |
| **document.py** | 文档相关模型 |

### 4.9 memory/ — 会话与状态

| 文件 | 说明 |
|------|------|
| **session_manager.py** | 会话管理（Redis），session_id / thread_id，initial_data 存储 |

### 4.10 cache/ — 缓存

| 文件 | 说明 |
|------|------|
| **smart_cache.py** | Redis 缓存，AI 分析、记忆查询等可缓存 |

### 4.11 frontend/ — 前端（Gradio）

| 文件 | 说明 |
|------|------|
| **app_enhanced.py** | 增强版前端（三列布局、双模式、流式） |
| **app.py** | 简化版前端 |
| **config.py** | 前端配置（后端 URL 等） |

### 4.12 routers/ — 路由子模块

| 文件 | 说明 |
|------|------|
| **data_and_knowledge.py** | 数据与知识库相关路由 |

### 4.13 knowledge/ — 知识库文档

| 文件 | 说明 |
|------|------|
| **marketing_knowledge.md** | 营销领域知识，供 RAG 检索 |

### 4.14 scripts/ — 脚本与测试

| 文件 | 说明 |
|------|------|
| **check_syntax.py** | 语法检查、main 导入、路由重复检测 |
| **test_feedback_classifier.py** | 反馈分类器单元测试 |
| **test_casual_creation_pattern.py** | 闲聊/创作交叉模式测试 |
| **test_frontend_api.py** | 前端 API 测试 |
| **refresh_bilibili_hotspot.py** | 手动刷新 B站热点 |
| **add_brand_memory_columns.sql** | 数据库迁移脚本 |
| **conftest.py** | pytest 配置 |

### 4.15 monitoring/ — 监控

| 路径 | 说明 |
|------|------|
| **prometheus.yml** | Prometheus 配置 |
| **grafana/** | Grafana 仪表盘与数据源 |

### 4.16 plugin_template/ — 插件开发模板

| 路径 | 说明 |
|------|------|
| **example_plugin/** | 示例插件 |
| **workflow.py** | 工作流插件模板 |

---

## 五、典型请求流程（示例）

**用户说：「帮我写个 B 站风格的耳机推广文案」**

1. **main.py** 收到 `POST /api/v1/frontend/chat`，解析 message
2. **InputProcessor** 识别意图为 creation，无澄清需求
3. **feedback_classifier** 判断非采纳/模糊评价，走正常流程
4. **build_meta_workflow** 执行：
   - **planning_node**：策略脑规划 steps = [web_search, kb_retrieve, analyze, generate, evaluate]
   - **router** 按步骤调度
   - **parallel_retrieval**：并发 web_search、kb_retrieve
   - **analyze**：调用 analysis_brain_subgraph，执行 bilibili_hotspot、knowledge_base 等插件
   - **generate**：调用 generation_brain_subgraph，执行 text_generator
   - **evaluate**：evaluation_node 打分
   - **compilation**：汇总思维链 + 输出 + 后续建议
5. 返回 JSON：`response`、`thinking_process`、`content_sections`

---

## 六、依赖关系简图

```
main.py
  ├── workflows/meta_workflow
  │     ├── workflows/analysis_brain_subgraph
  │     ├── workflows/generation_brain_subgraph
  │     ├── workflows/follow_up_suggestion
  │     ├── workflows/thinking_narrative
  │     └── services/ai_service
  ├── services/input_service
  │     └── core/intent/*
  ├── core/intent/feedback_classifier
  ├── config/*
  ├── database
  ├── memory/session_manager
  ├── cache/smart_cache
  └── modules/knowledge_base, case_template, methodology

services/ai_service
  ├── domain/content/* (analyzer, generator, evaluator)
  ├── core/ai (dashscope_client)
  └── core/brain_plugin_center
```

---

## 七、新人上手建议

1. **先看**：`README.md`、`START_HERE.md`
2. **理解流程**：`main.py` 中 `frontend_chat` 函数，从请求到响应的主链路
3. **理解工作流**：`workflows/meta_workflow.py` 的 `build_meta_workflow`，各节点职责
4. **理解意图**：`core/intent/processor.py`、`feedback_classifier.py`
5. **跑测试**：`python scripts/check_syntax.py`、`python scripts/test_casual_creation_pattern.py`
6. **改配置**：`config/api_config.py`、`docs/ENV_KEYS_REFERENCE.md`
