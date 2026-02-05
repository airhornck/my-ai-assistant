# AI 营销助手 — 项目整体总结（开发讲解用）

本文档面向开发同事，用于讲解项目定位、架构、主流程与扩展方式。

---

## 一、项目定位与目标

- **产品形态**：面向营销/内容创作的对话式 AI 助手，支持自然对话、深度思考式创作、多轮迭代。
- **核心能力**：根据用户意图完成「分析 → 生成 → 评估」的创作闭环，并支持检索、记忆、知识库、文档/链接等增强。
- **设计目标**：友好交互、意图识别、引导收集、策略脑泛化（不专为营销）、分析脑/生成脑模块化与可扩展、汇总与后续建议自然可读。

---

## 二、技术栈与目录概览

| 类别 | 技术/位置 |
|------|------------|
| **Web** | FastAPI，Uvicorn + Gunicorn |
| **工作流** | LangGraph（StateGraph），异步节点 |
| **LLM** | LangChain + OpenAI 兼容接口（可配 Dashscope/OpenAI 等） |
| **数据** | PostgreSQL（asyncpg）、Redis（会话/缓存） |
| **前端** | Gradio（`frontend/app_enhanced.py`），流式 SSE |
| **配置** | `.env` / `.env.prod`，`config/api_config.py`、`config/search_config.py` 等 |

**主要目录**：

```
main.py                 # 应用入口、HTTP 路由、会话与 MetaWorkflow 编排
config/                  # API/搜索/生成器等配置
core/                    # 意图、文档、链接、搜索、插件总线、插件注册中心
domain/                  # 领域：内容分析、生成、评估；memory
workflows/               # 元工作流、策略脑、分析脑子图、生成脑子图、后续建议、思维链叙述
plugins/                 # 脑级插件（B站热点、文案生成、方法论、知识库等）
modules/                 # 独立模块：知识库、方法论、案例模板、数据闭环
services/                # AI 服务、输入处理、文档、反馈、记忆优化
memory/                  # 会话管理（SessionManager）
frontend/                # Gradio 界面与流式请求
```

---

## 三、核心架构：三脑 + 编排 + 统一路由

### 3.1 整体数据流

```
用户输入
    → 意图识别（InputProcessor，可跳过极短闲聊）
    → 统一走策略脑（无单独闲聊分支）
    → 策略脑规划（planning_node）：输出 plan + 插件列表
    → 编排层按 plan 执行：parallel_retrieval | analyze | generate | evaluate | casual_reply | compilation
    → 汇总（compilation_node）：思维链叙述 + 最终输出 + 质量评估 + 后续建议
    → 流式/非流式返回前端
```

- **闲聊**：策略脑规划为一步 `casual_reply`，由 `casual_reply_node` 调用 `reply_casual`，汇总时极简输出，无思维链/后续建议。
- **创作**：策略脑规划 web_search、memory_query、analyze、generate、evaluate 等步骤，编排层依次或并行执行，最后汇总为「深度思考报告」。

### 3.2 三脑职责

| 脑 | 职责 | 实现位置 |
|----|------|----------|
| **策略脑** | 根据用户意图构建思维链（CoT），输出 plan 与 analysis_plugins/generation_plugins | `workflows/meta_workflow.py` 的 `planning_node` |
| **分析脑** | 品牌与热点关联、策略分析；按插件列表执行（B站热点、方法论、知识库等） | `workflows/analysis_brain_subgraph.py`，`domain/content/analyzer.py`，`core/brain_plugin_center.py` |
| **生成脑** | 按分析结果与参数生成文案/脚本等；按插件列表执行（文本、活动方案等） | `workflows/generation_brain_subgraph.py`，`domain/content/generator.py`，插件中心 |
| **评估** | 对生成内容做质量评估与是否需要修订（单节点，非子图） | `meta_workflow` 的 `evaluate_node`，`domain/content/evaluator.py` |

### 3.3 元工作流节点一览

- **planning** → **router** → 按 plan 与 current_step 路由到：
  - **parallel_retrieval**：web_search、memory_query、bilibili_hotspot、kb_retrieve 等并行
  - **analyze**：分析脑子图
  - **generate**：生成脑子图
  - **evaluate**：评估节点
  - **casual_reply**：闲聊回复
  - **compilation**：汇总报告
- evaluate 后可进入 **human_decision**（是否修订），再回到 router 或 generate。
- 所有步骤执行完后进入 **compilation**，输出带「思维链 + 最终输出 + 质量评估 + 后续建议」的报告。

---

## 四、请求主流程（与开发最相关的部分）

### 4.1 前端对话入口

- **流式**：`POST /api/v1/chat`（或前端封装的流式接口），请求体含 `message`、`session_id`、`history` 等。
- **main.py** 中：
  1. 会话恢复与历史拼接、文档/链接上下文加载。
  2. **采纳后续建议**：若会话存在 `suggested_next_plan` 且用户消息为采纳语（如「需要」「可以的」「好的」），置 `accepted_suggestion_this_request`，用会话 topic 覆盖 raw_query，避免把采纳语当新话题。
  3. **风格改写**：若识别为对上文内容的平台/风格改写（如「生成B站风格的」），置 `rewrite_previous_for_platform`，注入上文内容。
  4. 意图处理：极短闲聊可跳过 InputProcessor；否则走 InputProcessor 得到 intent、structured_data、raw_query 等。
  5. 命令/澄清/文档查询等分支后，构建 `user_input_payload` 与 `initial_state`，调用 **MetaWorkflow**（`build_meta_workflow` 编译后的图）。
  6. 流式时通过 `_stream_events` 产出 SSE；结束后更新会话（含 `suggested_next_plan`）。

### 4.2 策略脑（planning_node）

- 输入：`user_input`（JSON，含 raw_query、intent、brand_name、topic、user_accepted_suggestion、session_suggested_next_plan 等）。
- **快路径**：极短闲聊（如「还好」「嗯」）直接 `plan = [casual_reply]`，不调 LLM。
- **正常路径**：用 LLM 按「专家原则」规划步骤（web_search、analyze、generate、evaluate、casual_reply 等），输出 plan 与 task_type；若有采纳建议则直接采用 `session_suggested_next_plan` 作为 plan。
- 输出写入 state：`plan`、`task_type`、`thinking_logs` 等。

### 4.3 编排层执行

- **parallel_retrieval_node**：按 plan 中本步执行 web_search、memory_query、bilibili_hotspot、kb_retrieve 等，结果写入 search_context、memory_context、kb_context 等。
- **analyze_node**：调用 `analysis_subgraph.ainvoke(state)`，结果合并进 state（analysis、effective_tags 等）。
- **generate_node**：调用 `generation_subgraph.ainvoke(state)`，支持 platform、output_type（含 rewrite）、source_content 等；结果写入 content。
- **evaluate_node**：调用 `ai_svc.evaluate_content`，写入 evaluation、need_revision。
- **casual_reply_node**：调用 `ai_svc.reply_casual`，写入 content。
- **compilation_node**：拼「深度思考报告」：思维链叙述（可配置简单拼接或 LLM 叙述）、最终输出、质量评估；再调 **后续建议**（`get_follow_up_suggestion`），拼「后续建议」区块与 `suggested_next_plan`。

### 4.4 后续建议

- **位置**：`workflows/follow_up_suggestion.py`，在 compilation_node 内调用，**不是**独立子图节点。
- **作用**：根据用户意图、本轮步骤、输出摘要、系统能力，生成 1～3 条自然口语化建议 + 可选一句引导（如「如果你愿意，我可以帮你生成一版初稿」）；若有可执行下一步则返回 STEP: generate/analyze（仅系统解析，不展示给用户）。
- **展示**：报告内「---」分隔 +「## 后续建议」+ 正文；前端不展示「STEP: generate」等。

---

## 五、意图、会话与澄清

- **意图类型**：casual_chat、free_discussion、structured_request、document_query、command 等；见 `core/intent/processor.py`、`config/media_specs.py`。
- **短句修正**：如「还好」「嗯」等直接判为 casual_chat，避免误判为创作。
- **澄清**：缺品牌/产品/主题或明确要生成但缺平台/篇幅时，`needs_clarification` 为真，返回引导文案，不进入 MetaWorkflow。
- **会话**：SessionManager（Redis）+ 会话内 session_intent、suggested_next_plan、content 等，用于多轮话题延续、采纳建议、风格改写。

---

## 六、LangGraph 特性使用

本项目用 **LangGraph** 构建元工作流与子图，以下为实际用到的特性与对应代码位置，便于同事理解与扩展。

### 6.1 状态图与状态类型

- **StateGraph(MetaState)**：元工作流使用 TypedDict 状态 `MetaState`（见 `workflows/types.py`），继承自 `State`，扩展了 `plan`、`current_step`、`thinking_logs`、`step_outputs`、`search_context`、`analysis_plugins` 等。所有节点接收并返回与该状态兼容的 dict，LangGraph 会按 key 做**合并**（新值覆盖或与 reducer 结合，取决于状态定义）。
- **子图状态**：分析脑/生成脑子图使用 `StateGraph(dict)`，入参、出参均为与 MetaState 兼容的 dict，由调用方（analyze_node / generate_node）把父图 state 传入并合并子图返回结果。

**代码位置**：`workflows/meta_workflow.py` 中 `workflow = StateGraph(MetaState)`；`workflows/types.py` 中 `MetaState` 定义。

### 6.2 节点与边

- **add_node(name, fn)**：节点函数签名为 `(state) -> dict` 或 `async (state) -> dict`，返回要写回状态的字段（部分更新即可）。
- **set_entry_point("planning")**：指定图从 `planning` 节点开始执行。
- **add_edge(from, to)**：固定边，如 `planning → router`、`parallel_retrieval → router`、`compilation → END`。
- **END**：从 `langgraph.graph` 导入，表示图结束；`compilation` 后接 `END`。

**代码位置**：`workflows/meta_workflow.py` 中 `workflow.add_node(...)`、`workflow.add_edge(...)`、`workflow.set_entry_point("planning")`。

### 6.3 条件边与动态路由

- **add_conditional_edges(source, path_fn, path_map)**：根据当前 state 动态决定下一节点。
  - **router**：`_router_next(state)` 根据 `plan`、`current_step` 返回下一节点名（如 `"parallel_retrieval"`、`"analyze"`、`"generate"`、`"evaluate"`、`"casual_reply"`、`"compilation"`、`"skip"`），实现「按规划步骤循环执行」。
  - **evaluate 之后**：`_eval_after_evaluate(state)` 根据 `need_revision` 返回 `"human_decision"` 或 `"router"`。
  - **human_decision 之后**：`_human_decision_next(state)` 根据用户选择返回 `"generate"`（修订）或 `"router"`（不修订）。

**代码位置**：`workflows/meta_workflow.py` 中 `workflow.add_conditional_edges("router", _router_next, {...})`、`add_conditional_edges("evaluate", _eval_after_evaluate, ...)`、`add_conditional_edges("human_decision", _human_decision_next, ...)`。

### 6.4 子图组合（子图作为节点）

- 分析脑、生成脑各自是**独立编译的 StateGraph**（单节点 + END），在主图中**不作为嵌套子图挂载**，而是由主图节点**显式调用**：
  - `analyze_node` 内：`out = await analysis_subgraph.ainvoke(state)`，再把 `out` 与 step_outputs、thinking_logs 等合并写回 state。
  - `generate_node` 内：`out = await generation_subgraph.ainvoke(state_with_platform)`，同理合并。
- 这样做的原因：主图需要在本轮 state 上追加 `step_outputs`、`thinking_logs` 等，子图只负责「分析/生成」的输入输出，由主图节点做结果合并与步骤计数。

**代码位置**：`workflows/meta_workflow.py` 中 `build_analysis_brain_subgraph`、`build_generation_brain_subgraph` 的构建；`analyze_node` / `generate_node` 内 `subgraph.ainvoke(state)`。

### 6.5 检查点与持久化（Checkpointer）

- **workflow.compile(checkpointer=checkpointer)**：元工作流编译时传入 `MemorySaver()`（`langgraph.checkpoint.memory`），用于**保存每步后的状态快照**，支持中断与恢复。
- **config**：调用时传入 `config={"configurable": {"thread_id": session_id}}`，同一 `thread_id` 对应同一会话的检查点，便于「人工决策后恢复」时从断点继续。

**代码位置**：`workflows/meta_workflow.py` 末尾 `checkpointer = MemorySaver()`、`return workflow.compile(checkpointer=checkpointer)`；`main.py` 中 `meta.ainvoke(initial_state, config=config)`、`config = {"configurable": {"thread_id": session_id}}`。

### 6.6 人工中断与恢复（Interrupt / Resume）

- **interrupt(payload)**：在 **human_decision_node** 中，当评估结果为「需修订」时调用 `interrupt(payload)`（`langgraph.types.interrupt`），图在此暂停并返回带 `__interrupt__` 的结果；前端展示「是否修订」并调用恢复接口。
- **恢复执行**：前端提交用户选择后，调用 `meta.ainvoke(Command(resume=human_decision), config=config)`（`langgraph.types.Command`），用同一 `thread_id` 的 config 从断点恢复，将用户决策（如 `"revise"` / `"skip"`）注入，图从 human_decision 节点继续执行到下一节点（generate 或 router）。

**代码位置**：`workflows/meta_workflow.py` 中 `human_decision_node` 内 `decision = interrupt(payload)`；`main.py` 中 chat 返回 `__interrupt__`、`/api/v1/chat/resume` 中 `meta.ainvoke(Command(resume=human_decision), config=config)`。

### 6.7 执行方式

- **ainvoke(state, config=config)**：主流程使用异步调用，传入初始 state 与含 `thread_id` 的 config；返回完整 state（或含 `__interrupt__` 的字典）。
- **流式**：当前流式是在 main 层通过 `_stream_events` 等方式封装 SSE，并非使用 LangGraph 的 `astream`；若后续需要「按节点流式输出」，可考虑 `meta.astream_events` 或 `meta.get_graph().get_state(config)` 等 API。

### 6.8 小结（LangGraph 在本项目中的用法）

| 特性 | 用途 | 位置 |
|------|------|------|
| StateGraph + TypedDict 状态 | 元工作流状态形状与合并 | `meta_workflow.py`，`types.py` |
| add_node / add_edge / set_entry_point / END | 固定流程与入口、出口 | `meta_workflow.py`，分析/生成脑子图 |
| add_conditional_edges | 按 plan/current_step 路由、评估后分支、人工决策后分支 | `meta_workflow.py` |
| 子图 ainvoke(state) | 分析脑、生成脑作为可复用图，由主图节点调用 | `analyze_node`，`generate_node` |
| compile(checkpointer=...) | 支持中断与恢复 | `meta_workflow.py` |
| config.configurable.thread_id | 会话级检查点 | `main.py` 传入 config |
| interrupt / Command(resume=...) | 评估后「是否修订」的人机协作 | `human_decision_node`，`main.py` resume 接口 |

---

## 七、插件体系（脑级）

- **插件中心**：`core/brain_plugin_center.py`，按「分析脑」「生成脑」注册；策略脑只规划步骤与插件名，不执行。
- **分析脑插件**：如 bilibili_hotspot（定时）、methodology、case_library、knowledge_base、campaign_context（拼装）等。
- **生成脑插件**：如 text_generator、campaign_plan_generator、image_generator、video_generator（占位）等。
- **扩展方式**：实现 `register(plugin_center, config)`，在插件中心对应脑的列表中登记；策略脑在规划时把插件名加入 `analysis_plugins` / `generation_plugins`。详见 `docs/PLUGIN_DEVELOPMENT_GUIDE.md`、`docs/BRAIN_PLUGIN_ARCHITECTURE.md`。

---

## 八、前端与 API 概要

- **前端**：Gradio 在 `frontend/app_enhanced.py`，通过后端封装接口请求；支持流式展示（SSE 逐段返回）。
- **主要 API**：
  - 对话：`POST /api/v1/chat`（或项目内封装的流式 chat 接口）
  - 创建会话、恢复会话、历史记录等
  - 文档上传（带 session_id）、数据与知识相关接口（见 `routers/`、`main.py`）
- **健康与监控**：`/health`、`/metrics`（Prometheus），Docker 部署见 `docker-compose.prod.yml`、`docs/DOCKER_TROUBLESHOOTING.md`。

---

## 九、数据与存储

- **PostgreSQL**：用户、会话、交互历史、文档元数据、反馈与案例等。
- **Redis**：会话状态（SessionManager）、缓存（若使用 SmartCache）。
- **会话状态**：含 initial_data（session_intent、suggested_next_plan、content 等），用于多轮与采纳建议。

---

## 十、配置与部署

- **环境变量**：见 `docs/ENV_KEYS_REFERENCE.md`；典型包括 LLM API、数据库、Redis、搜索 API、是否简单思维链叙述等。
- **生产**：`docker compose --env-file .env.prod -f docker-compose.prod.yml up`；构建问题见 `docs/DOCKER_TROUBLESHOOTING.md`。

---

## 十一、扩展与开发指引（给同事的入口）

| 需求 | 建议入口 |
|------|----------|
| 改对话流程/策略 | `main.py` 中 chat 路由、采纳建议与改写逻辑；`workflows/meta_workflow.py` 的 planning_node、路由与节点 |
| 改分析/生成逻辑 | `workflows/analysis_brain_subgraph.py`、`workflows/generation_brain_subgraph.py`；`domain/content/analyzer.py`、`generator.py` |
| 新增脑级插件 | `plugins/` 下新建模块并实现 register；在 `core/brain_plugin_center.py` 登记；策略脑规划里按意图加入插件名 |
| 改意图识别 | `core/intent/processor.py`；短句集合与澄清逻辑在 `config/media_specs.py` |
| 改后续建议语气与结构 | `workflows/follow_up_suggestion.py`（prompt 与解析）；展示在 `meta_workflow.py` 的 compilation_node |
| 改评估维度或展示 | `domain/content/evaluator.py`；compilation_node 中质量评估区块 |
| 独立模块（知识库、方法论等） | `modules/`；供编排或脑内插件调用 |

---

## 十二、文档索引（可一并发给同事）

- 架构与流程：`ARCHITECTURE_AND_FLOW.md`、`BRAIN_ARCHITECTURE.md`
- 插件与脑：`BRAIN_PLUGIN_ARCHITECTURE.md`、`PLUGIN_DEVELOPMENT_GUIDE.md`
- 模块与解耦：`MODULE_ARCHITECTURE.md`
- 后续建议重构方案：`FOLLOWUP_SUGGESTION_REFACTOR.md`
- 性能与 Docker：`PERFORMANCE_OPTIMIZATION.md`、`DOCKER_TROUBLESHOOTING.md`、`ENV_KEYS_REFERENCE.md`

以上即为项目整体总结，可按「定位 → 架构 → 主流程 → LangGraph 特性 → 插件与扩展入口」顺序向开发同事讲解。
