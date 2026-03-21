# 编排与记忆系统对比：本产品 vs OpenClaw

本文对比 **本产品（my_ai_assistant）** 与 **OpenClaw**（代码根目录 `D:\openclaw-main`）在**编排（Orchestration）**和**记忆（Memory）**两方面的设计与实现差异。  
对比依据：本仓库代码 + OpenClaw 官方文档（`docs/concepts/` 等）。

---

## 一、编排（Orchestration）

### 1.1 本产品（my_ai_assistant）

| 维度 | 说明 |
|------|------|
| **技术栈** | Python + **LangGraph**（StateGraph），单仓库内自建完整 DAG。 |
| **入口** | FastAPI HTTP（如 `/api/v1/chat/new`、`/api/v1/analyze-deep`、`/api/v1/frontend/chat` 等），请求进入后由 `meta_workflow` 驱动。 |
| **主流程结构** | **规划 → 编排 → 汇总** 的线性 + 可选循环：<br>1. **planning_node**（策略脑）：IntentAgent 意图识别 → PlanningAgent 输出 steps + plugins<br>2. **orchestration_node**（编排层）：按 plan 顺序执行 web_search、memory_query、kb_retrieve、analyze（分析脑子图）、generate（生成脑子图）、evaluate 等<br>3. **compilation_node**：整合 step_outputs，生成最终回复<br>4. **reasoning_loop_node**（可选）：ReAct 风格“是否继续/重规划/结束”的规则判断，可多轮执行。 |
| **状态** | 集中式 **MetaState**（TypedDict）：user_input、plan、current_step、step_outputs、thinking_logs、analysis_plugins、generation_plugins、memory_context、search_context、kb_context 等；由 LangGraph 在单次 run 内传递。 |
| **会话持久化** | 对话状态（如 plan、step_outputs）依赖调用方传入的 session_id；若使用 LangGraph Checkpoint，可由 thread_id 持久化图状态。业务侧另有 DB 存 InteractionHistory、UserProfile 等。 |
| **插件/能力** | 分析脑、生成脑由 **BrainPluginCenter** 管理；plan 中每步指定 `plugins: ["xxx"]`，编排层按名调用 `get_output(plugin_name, context)`，**动态选插件**。 |
| **多轮与澄清** | 意图置信度低时，planning_node 可直接返回“澄清”步骤（如 casual_reply 带澄清话术）；reasoning_loop 根据 step_outputs 规则判断是否继续或结束。 |

**特点小结**：显式“策略脑 + 编排层 + 汇总”的 CoT 链，步骤与插件由 LLM 规划、代码按 plan 执行；状态在 LangGraph 状态对象内流转，可选 Redis/Postgres 做 Checkpoint。

---

### 1.2 OpenClaw

| 维度 | 说明 |
|------|------|
| **技术栈** | TypeScript/Node，**嵌入式 pi-agent-core 运行时**（来自 pi-mono），Gateway 通过 WebSocket 与客户端通信。 |
| **入口** | Gateway RPC：`agent`、`agent.wait`；CLI：`openclaw agent`。请求进入后由 Gateway 调用 `runEmbeddedPiAgent`，**单次 run 即一次 agent 循环**。 |
| **主流程结构** | **Agent Loop** 单次串行执行：<br>1. **intake**：校验参数、解析 session（sessionKey/sessionId）、持久化 session 元数据<br>2. **context assembly**：加载 workspace、skills、bootstrap 文件（AGENTS.md、SOUL.md、TOOLS.md 等），构建 system prompt<br>3. **model inference**：调用大模型（pi-agent-core 内部）<br>4. **tool execution**：模型产生 tool call，Gateway 执行工具（如 `memory_search`、`memory_get`、read、edit、exec 等）<br>5. **streaming replies**：将 assistant/tool 的 delta 通过 WebSocket 推给客户端<br>6. **persistence**：session 写 JSONL；可选 compaction、memory flush。 |
| **状态** | **会话级**：Session 由 Gateway 管理，transcript 存于 `~/.openclaw/agents/<agentId>/sessions/<SessionId>.jsonl`。**无显式“规划步骤”状态对象**；模型自主决定是否调用工具、多轮 tool-use 在单次 agent run 内完成。 |
| **并发** | 按 **session 串行**（per-session lane）+ 可选 global lane，避免同会话并发导致状态错乱。 |
| **Hook** | 提供 **Gateway hooks**（如 `agent:bootstrap`）与 **Plugin hooks**（`before_prompt_build`、`before_tool_call`、`after_tool_call`、`agent_end`、`before_compaction` 等），在 agent 循环的固定阶段插入逻辑。 |
| **与“规划”** | 无独立“Planning Agent”节点；**模型自己决定**下一步是继续推理、调工具还是结束，即“agentic loop”由模型+工具迭代完成。 |

**特点小结**：以“单次 agent run = 一次模型推理 + 多轮 tool 执行”为主，状态在 session transcript 与 workspace 文件中；编排由模型驱动，而非显式 DAG。

---

### 1.3 编排对比摘要

| 对比项 | 本产品（my_ai_assistant） | OpenClaw |
|--------|---------------------------|----------|
| 编排模型 | **显式 DAG**（LangGraph）：规划 → 编排 → 汇总，步骤与插件由 Planning Agent 输出 | **模型驱动**：单次 agent run 内模型自主决定调用哪些工具、何时结束 |
| 规划 | 有独立 **IntentAgent + PlanningAgent**，输出 steps + plugins | 无独立规划节点；模型在对话中“边想边做” |
| 状态载体 | **MetaState**（plan、step_outputs、thinking_logs 等）在图中传递 | **Session transcript**（JSONL）+ workspace 文件；无 step 级状态对象 |
| 插件/工具 | 分析脑/生成脑 **按 plan 动态调用**；步骤类型固定（analyze、generate、web_search 等） | **工具**由 skills + 内置工具注册，模型在推理中**按需调用** |
| 循环 | **reasoning_loop_node** 规则判断是否继续/重规划/结束（可配合 LangGraph 条件边） | 单次 run 内模型可多轮 tool call，run 结束后需再次发起 `agent` 才会进入下一轮 |
| 入口 | HTTP API（FastAPI） | WebSocket RPC（Gateway）+ CLI |

---

## 二、记忆（Memory）

### 2.1 本产品（my_ai_assistant）

| 维度 | 说明 |
|------|------|
| **存储** | **关系型 DB**（PostgreSQL）：<br>• **UserProfile**：user_id、brand_name、industry、product_desc、tags、brand_facts、success_cases、preferred_style 等<br>• **UserMemoryItem**：用户级语义记忆条（可做向量检索）<br>• **InteractionHistory**：历史交互（user_input、ai_output、session_id 等） |
| **服务层** | **MemoryService**（`services/memory_service.py` / `domain/memory`）：<br>• `get_memory_for_analyze()`：为分析/生成提供“用户画像 + 品牌事实 + 成功案例 + 语义 top_k 记忆条 + 近期交互”的聚合上下文，可带 **SmartCache** 按请求指纹缓存<br>• `get_user_summary()`：短摘要（品牌、行业、偏好）<br>• `get_recent_conversation_text()`：近期对话文本（多轮上下文）<br>• `query_brand_facts()` / `query_success_cases()`：按 topic 查结构化事实与案例 |
| **注入方式** | 编排层在 **memory_query** 步骤调用 `memory_svc.get_memory_for_analyze()`，结果写入 state 的 **memory_context**，供后续 analyze/generate 节点使用；能力接口（如内容方向榜单）通过 `_load_user_context` 拉取画像 + 偏好后再调插件。 |
| **会话状态** | 对话级状态（plan、step_outputs）不写入 MemoryService；若用 LangGraph Checkpoint，则由 thread_id 持久化图状态，与“业务记忆”分离。 |
| **语义检索** | 可选 **UserMemoryItem** + 向量检索（如 `memory_embedding`），在 `_get_memory_for_analyze_impl` 中做 top_k 召回，与画像、近期交互一起拼成 preference_context。 |

**特点小结**：记忆以 **DB 为中心**（用户画像、事实、案例、历史交互、语义条），由 **MemoryService** 统一封装，在工作流中作为 **memory_context** 注入；与 LangGraph 的“图状态”分工明确。

---

### 2.2 OpenClaw

| 维度 | 说明 |
|------|------|
| **存储** | **文件系统**：Markdown 为唯一事实来源。<br>• **memory/YYYY-MM-DD.md**：按日日志（append-only），会话启动时读今天+昨天<br>• **MEMORY.md**：长期记忆，仅在**主私有会话**加载（不在群聊等上下文加载）<br>• 文件位于 **agent workspace**（如 `~/.openclaw/workspace`）。 |
| **工具** | 由 **memory plugin**（默认 `memory-core`）提供：<br>• **memory_search**：语义检索（向量 + 可选 BM25 混合），返回片段（ path、line range、score）<br>• **memory_get**：按 path/行范围读指定 Markdown 文件<br>模型在 **agent run 内**按需调用这两类工具，而非服务端在“某一步”自动注入。 |
| **向量与索引** | 默认对 MEMORY.md + memory/*.md 做 **chunk + embedding**，存于 per-agent SQLite（`~/.openclaw/memory/<agentId>.sqlite`）；支持多种 embedding 提供商（OpenAI、Gemini、Voyage、Mistral、local、Ollama 等）；可选 **QMD 后端**（BM25+向量+rerank）、**hybrid search**、**MMR 去重**、**temporal decay** 等。 |
| **预压缩 memory flush** | 当 session 接近 **auto-compaction** 时，触发一次**静默 agent 轮次**，提醒模型把需持久化的内容写入 memory 文件（如 memory/YYYY-MM-DD.md），再执行压缩；由 `agents.defaults.compaction.memoryFlush` 配置。 |
| **Bootstrap 与上下文** | **AGENTS.md、SOUL.md、TOOLS.md、USER.md、IDENTITY.md** 等在 **session 首轮**注入 system prompt；它们与 memory 文件不同，属于“工作区配置/人格”，不是由模型随时写入的日记。 |
| **Session transcript** | 存于 `~/.openclaw/agents/<agentId>/sessions/<SessionId>.jsonl`，可选纳入 **session memory search**（实验性），供 memory_search 检索近期对话。 |

**特点小结**：记忆以 **Markdown 文件**为源，**模型通过工具**（memory_search / memory_get）按需读取与写入；索引与检索由 memory plugin 管理，支持向量/混合检索与丰富后处理；与“上下文”的关系是：context = system prompt + 会话历史 + 工具结果，memory 通过工具结果进入 context。

---

### 2.3 记忆对比摘要

| 对比项 | 本产品（my_ai_assistant） | OpenClaw |
|--------|---------------------------|----------|
| 存储形态 | **关系型 DB**（UserProfile、UserMemoryItem、InteractionHistory） | **Markdown 文件**（MEMORY.md、memory/YYYY-MM-DD.md） |
| 谁使用记忆 | **编排层/服务层**：memory_query 步骤或能力接口拉取 MemoryService，把结果写入 state 或 context，再交给分析/生成 | **模型**：在 agent run 内**主动调用** memory_search / memory_get，结果作为 tool result 进入下一轮推理 |
| 语义检索 | MemoryService 内 **UserMemoryItem + 向量 top_k**，与画像、近期交互拼成 preference_context | memory plugin 对 **MEMORY.md + memory/*.md** 做 chunk+embedding，**memory_search** 返回片段；支持 hybrid、MMR、temporal decay 等 |
| 写入记忆 | 由业务逻辑/插件写 DB（如更新 UserProfile、插入 UserMemoryItem、写 InteractionHistory） | **模型**在工具调用或 memory flush 轮次中，通过写文件（如 edit/write）写入 memory 目录 |
| 会话历史 | InteractionHistory 表 + 可选 get_recent_conversation_text；与“图状态”分离 | Session JSONL + 可选 session memory 检索；compaction 时可压缩旧轮次 |
| 与上下文边界 | memory_context 为工作流中**显式字段**，由服务端在固定步骤注入 | context = system + 会话 + 工具结果；memory 作为**工具返回值**进入 context |

---

## 三、总结表

| 领域 | 本产品（my_ai_assistant） | OpenClaw |
|------|---------------------------|----------|
| **编排** | LangGraph 显式 DAG；Intent + Planning 输出 plan → 编排层按 step 执行 → 汇总；状态在 MetaState 中 | 嵌入式 pi-agent 单次 run：模型推理 + 多轮 tool 执行；状态在 session transcript + workspace |
| **规划** | 独立策略脑（IntentAgent + PlanningAgent），步骤与插件由 LLM 规划 | 无独立规划；模型在对话中自主决定调用工具与结束时机 |
| **记忆存储** | PostgreSQL（UserProfile、UserMemoryItem、InteractionHistory） | Markdown（MEMORY.md、memory/YYYY-MM-DD.md） |
| **记忆使用** | 服务端在编排步骤中调用 MemoryService，将结果注入 memory_context | 模型在 run 内调用 memory_search / memory_get，结果通过 tool result 进入 context |
| **记忆写入** | 业务/插件写 DB | 模型通过写文件 + 预压缩 memory flush 写 memory 目录 |
| **适用场景** | 强流程控制、需可解释的步骤与插件选择、以 DB 为中心的用户/品牌记忆 | 个人助手、多通道、以文件与工具为中心的“模型自主”记忆与上下文 |

若需对某一块做更细的代码级对照（例如 meta_workflow 的 orchestration_node 与 OpenClaw 的 agentCommand），可指定模块或文件路径继续展开。
