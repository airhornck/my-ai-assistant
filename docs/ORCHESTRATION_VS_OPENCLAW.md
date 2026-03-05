# 本项目编排层与 OpenClaw 编排层深度对比

本文档从**入口、规划与执行模型、状态与上下文、工具暴露、人机闭环、持久化与流式、会话与并发**等维度，对比本项目的元工作流编排与 [OpenClaw](https://github.com/openclaw/openclaw) 的 Agent Loop 编排，便于架构选型与演进参考。

---

## 一、总体定位

| 维度 | 本项目 | OpenClaw |
|------|--------|----------|
| **产品形态** | 营销/内容创作 AI 助手（B 端能力 API + 前端聊天） | 个人 AI 助手，多通道收件箱（WhatsApp/Telegram/Slack/Discord/WebChat 等） |
| **编排载体** | 服务内 LangGraph 元工作流（`build_meta_workflow`） | Gateway 控制面 + 嵌入式 Pi Agent 运行时（pi-agent-core） |
| **触发入口** | HTTP API：`/api/v1/analyze-deep`、`/api/v1/analyze-deep/raw`、`/api/v1/frontend/chat` 等 | CLI `openclaw agent`、Gateway RPC `agent` / `agent.wait`、通道消息入站 |
| **参考文档** | 本仓库 `STRATEGY_BRAIN_VS_AGENT_ORCHESTRATION.md`、`workflows/meta_workflow.py` | [Agent Loop](https://docs.openclaw.ai/concepts/agent-loop)、[Pi Integration](https://docs.openclaw.ai/pi) |

---

## 二、编排模型：规划 vs 推理环

### 2.1 本项目：一次规划 + 按 plan 线性/并行执行

```
用户请求
    → planning_node（策略脑，一次 LLM）
    → 得到 plan = [ step1, step2, ... ]，每步带 params、reason
    → router：根据 plan[current_step] 选下一节点
    → parallel_retrieval | analyze | generate | evaluate | skip | casual_reply
    → 执行完后 current_step += 1，回到 router
    → current_step >= len(plan) → compilation → END
```

- **规划**：仅入口处一次 LLM 调用，产出整条「思维链」JSON（`task_type` + `steps`）。  
- **执行**：编排层**不再**调用模型；下一步完全由 `plan[current_step]` 的 `step` 名决定，参数来自 `plan[i].params`。  
- **结果对后续步的影响**：仅通过 state 传递（如 `search_context`、`analysis`、`content`）；**不会**因为某步失败或结果为空而「再问模型换一步或改参数」。

### 2.2 OpenClaw：Agent Loop（推理环）

根据 [Agent Loop](https://docs.openclaw.ai/concepts/agent-loop) 文档，一次 run 的抽象流程为：

```
intake（消息入队）
    → context assembly（会话 + workspace + 系统 prompt 组装）
    → model inference（模型推理）
    → 若输出为 tool_call → tool execution（执行工具）
    → 将「tool_call + 执行结果」追加进上下文
    → 再次 model inference（模型看到上一步结果，决定下一个 tool_call 或最终回复）
    → … 循环直到模型产出最终文本（不再发起 tool_call）
    → streaming replies → persistence
```

- **规划**：**无**单独的「规划节点」；每一步「选哪个工具、传什么参数」都由**当轮**模型在看过当前上下文（含历史 tool 结果）后决定。  
- **执行**：工具执行由 Pi 运行时/网关协调；执行结果写回会话 transcript，作为下一轮推理的输入。  
- **结果对后续步的影响**：**直接**；例如搜索无结果，下一轮模型可改 query 或换工具。

### 2.3 对比小结

| 维度 | 本项目 | OpenClaw |
|------|--------|----------|
| **规划时机** | 入口一次，产出整条 plan | 无独立规划；每轮推理即「规划」下一步 |
| **下一步由谁决定** | 由 `plan[current_step]` 与 router 逻辑决定 | 由模型当轮输出（text 或 tool_call）决定 |
| **参数来源** | 首轮 plan 中的 `steps[i].params` + 编排层少量补全 | 每轮模型根据当前上下文解析出 tool 的 arguments |
| **是否「根据结果再决策」** | 否（仅补救逻辑在 parallel_retrieval 内可选触发） | 是（典型 Agent 推理环） |
| **可解释性** | 强：整条 plan 可见，步骤与 reason 可审计 | 依赖会话 transcript 与 stream 事件，链在多次调用中展开 |

---

## 三、状态与上下文

### 3.1 本项目

- **状态结构**：`MetaState`（LangGraph），包含 `user_input`、`plan`、`current_step`、`thinking_logs`、`step_outputs`、`search_context`、`memory_context`、`kb_context`、`analysis`、`content`、`evaluation`、`analysis_plugins`、`generation_plugins` 等。  
- **单轮语义**：一次 `ainvoke(initial_state)` 跑完「planning → router → … → compilation」整图；中断仅发生在 **evaluate 后 need_revision** 时，由人工 `chat/resume` 再继续。  
- **上下文注入**：规划时通过 `user_prompt` 注入品牌、产品、话题、意图、会话上下文、采纳建议等；执行时各节点从 state 读上一步产出。

### 3.2 OpenClaw

- **会话**：SessionManager + 会话 transcript（消息列表，含 assistant/tool 消息）；bootstrap 文件（SOUL.md、TOOLS.md 等）与 skills 注入到 system prompt。  
- **单轮语义**：一次 `agent` RPC 触发一条「run」；run 内是**多轮**模型调用 + 工具执行，直到模型返回最终文本。  
- **上下文注入**：系统 prompt 动态组装（base + skills + bootstrap + 可选 overrides）；每轮模型看到完整会话历史 + 最新 tool 结果。

### 3.3 对比小结

| 维度 | 本项目 | OpenClaw |
|------|--------|----------|
| **状态载体** | LangGraph state（内存 + Postgres Checkpointer） | 会话 transcript + 可选持久化 |
| **「一轮」含义** | 一次请求跑完整图（或到 human_decision 暂停） | 一次 run 内多轮 model+tool 直到结束 |
| **上下文形式** | 结构化 state 字段 + 规划时 user_prompt | 消息列表 + 动态 system prompt |

---

## 四、工具/能力暴露与执行

### 4.1 本项目

- **暴露方式**：策略脑 system 中「可用模块」为**自然语言枚举**（由 `step_descriptions_for_planning` 动态拼接）；模型产出 `steps` 数组，每步含 `step` 名、`params`、`reason`。  
- **执行**：router 根据 `step` 名路由到对应节点；`parallel_retrieval` 内按 step 名调用 `_run_web_search`、`_run_bilibili_hotspot` 等；analyze/generate 由子图 + 插件中心根据 `analysis_plugins`/`generation_plugins` 执行。  
- **参数**：来自 `plan[i].params`，无「每步前由模型从自然语言解析 tool 参数」的接口；仅编排层有少量补全（如 `_complete_step_params`）。

### 4.2 OpenClaw

- **暴露方式**：工具以**名 + 描述 + 参数 schema** 形式提供给模型；模型输出**结构化 tool_call**（name + arguments）。  
- **执行**：Pi 运行时/网关解析 tool_call，执行对应工具（browser、canvas、nodes、cron、sessions 等），结果写回 transcript；下一轮模型看到 tool 结果。  
- **钩子**：`before_tool_call` / `after_tool_call`、`tool_result_persist` 等，可拦截/改写参数与结果。

### 4.3 对比小结

| 维度 | 本项目 | OpenClaw |
|------|--------|----------|
| **工具描述** | 自然语言段落（可用模块列表） | 工具列表 + schema，模型输出 tool_call |
| **参数** | 首轮 plan 的 params，执行层只读 | 每轮由模型从上下文解析 arguments |
| **执行方** | 编排节点 + 子图 + 插件中心 | Pi 运行时 + 网关，统一 tool 执行与回写 |

---

## 五、人机闭环（Human-in-the-Loop）

### 5.1 本项目

- **唯一断点**：evaluate 节点后，若 `need_revision == True`，图进入 `human_decision` 节点并**中断**（`__interrupt__`）；前端需调 `POST /api/v1/chat/resume` 传入 `human_decision: "revise" | "skip"`，同一 thread_id 继续。  
- **用途**：评估不通过时选择「修订」或「跳过」；修订则回到 generate，否则回到 router 继续后续步或结束。

### 5.2 OpenClaw

- **Agent loop 内**：无强制「评估后必须人工」的断点；是否发消息、是否确认由通道与策略决定。  
- **通道与队列**：支持 queue modes（collect/steer/followup）、命令（如 `/new`、`/reset`）；可与人工操作结合，但非「图内固定断点」。

### 5.3 对比小结

| 维度 | 本项目 | OpenClaw |
|------|--------|----------|
| **图内断点** | 有：evaluate → human_decision，必须 resume 才继续 | 无固定「评估→人工」断点 |
| **恢复方式** | `chat/resume` + LangGraph Command(resume=…) | 新消息/命令入队，新 run 或继续会话 |

---

## 六、持久化、流式与会话

### 6.1 本项目

- **持久化**：LangGraph 使用 Postgres Checkpointer（若配置）持久化 state，便于 `chat/resume` 同一 thread；Redis 存会话元数据；DB 存交互历史（InteractionHistory）。  
- **流式**：`frontend/chat` 支持 `stream=true`，可逐步返回 state/思考过程；非流时一次性返回 JSON。  
- **会话**：`session_id` / `thread_id` 由后端创建；单次请求可带 `session_id` 延续会话。

### 6.2 OpenClaw

- **持久化**：会话 transcript 与 run 元数据；可选 compaction 与重试；插件可 hook `tool_result_persist`。  
- **流式**：`agent` 流式返回 `assistant`、`tool`、`lifecycle` 等事件；`agent.wait` 仅等待 run 结束。  
- **会话**：SessionManager + session key/lane；多通道、多会话隔离；队列串行化 per session（+ 可选 global lane）。

### 6.3 对比小结

| 维度 | 本项目 | OpenClaw |
|------|--------|----------|
| **状态持久化** | LangGraph Checkpointer + Redis + DB | 会话 transcript + run 元数据 |
| **流式** | 可选，按步/state 或最终 JSON | 标准：assistant/tool/lifecycle 流 |
| **会话/并发** | 单请求单 run；session 延续通过 thread_id | 每会话串行 run；队列与 lane 防并发冲突 |

---

## 七、架构图对照（概念）

### 本项目

```
  HTTP 请求
       │
       ▼
  ┌─────────────┐     plan + task_type
  │ planning    │ ────────────────────────┐
  └─────────────┘                          │
       │                                  │
       ▼                                  ▼
  ┌─────────────┐     plan[current_step]   state
  │   router    │ ◄───────────────────────┤
  └──────┬──────┘                          │
         │                                 │
    ┌────┴────┬────────┬────────┬──────────┴─────┐
    ▼         ▼        ▼        ▼                ▼
 parallel  analyze  generate  evaluate  skip  casual_reply
 retrieval                              │
    │         │        │        │       │         │
    └─────────┴────────┴────────┴───────┴─────────┘
                         │
                    need_revision?
                    ├─ yes → human_decision (中断) → resume → generate/router
                    └─ no  → router
                         │
                    current_step >= len(plan)
                         │
                         ▼
                  compilation → END
```

### OpenClaw（Agent Loop）

```
  消息 / agent RPC
       │
       ▼
  intake → context assembly（session + bootstrap + skills）
       │
       ▼
  ┌─────────────────────────────────────────────────────┐
  │  loop:                                              │
  │    model inference（看到 历史 + 上次 tool 结果）      │
  │         │                                            │
  │         ├─ 输出 text → 最终回复 → streaming → 退出   │
  │         └─ 输出 tool_call → 执行工具 → 结果进上下文  │
  │                    │                                 │
  │                    └─────────────────────────────────┘
  └─────────────────────────────────────────────────────┘
       │
       ▼
  persistence（transcript、compaction、hooks）
```

---

## 八、总结表

| 维度 | 本项目编排层 | OpenClaw 编排层（Agent Loop） |
|------|----------------|--------------------------------|
| **核心模型** | 一次规划，按 plan 顺序/并行执行 | 推理环：model → tool → 结果 → model，直到最终回复 |
| **规划** | 策略脑一次 LLM 产出整条 steps | 无单独规划；每轮推理即决策下一步 |
| **工具/步骤** | 自然语言描述 + steps JSON；执行由 router/节点实现 | 工具 schema + tool_call；执行由 Pi/网关统一执行 |
| **参数** | plan 内 params，执行层只读+补全 | 每轮模型解析 tool arguments |
| **适应性** | 低（固定 plan；补救仅限并行检索内） | 高（每步可根据结果改工具/参数） |
| **可解释性** | 高（整条 plan 与 reason 可见） | 依赖 transcript 与 stream |
| **人机断点** | evaluate → human_decision，resume 恢复 | 无图内固定断点 |
| **持久化** | LangGraph Checkpointer + Redis + DB | 会话 transcript + run 元数据 |
| **流式** | 可选 | 标准 assistant/tool/lifecycle 流 |
| **适用场景** | 深度思考/思维链可审计、营销创作流程固定 | 通用个人助手、多通道、开放任务与工具调用 |

---

## 九、演进时可选对齐点

若希望在不推翻「策略脑 + 插件」的前提下，局部吸收 OpenClaw 式能力，可考虑：

1. **补救与参数**：已做的「失败/空结果补救」与「参数补全」可保留；必要时再增加「单步前轻量模型解析参数」而不做全推理环。  
2. **工具描述**：若未来希望模型「每步选工具+参数」，可引入**工具 schema** 与 **tool_call 解析**，与现有 step 名做映射，执行仍走现有节点/插件。  
3. **流式与事件**：统一暴露「步骤开始/结束」「tool 开始/结束」类事件，便于前端/调试对齐 OpenClaw 的 `tool`/`lifecycle` 体验。  
4. **会话与队列**：多会话/多请求并发下，可参考 OpenClaw 的 per-session 串行与 queue modes，避免同一 session 并发 run 导致状态错乱。

本对比基于当前项目代码与 [OpenClaw 官方文档](https://docs.openclaw.ai/concepts/agent-loop) 整理；OpenClaw 实现细节以仓库与文档为准。
