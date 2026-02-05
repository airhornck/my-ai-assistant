# LangGraph + LangSmith 多脑协同与动态闭环实现说明

## 一、设计目标

实现「LangGraph + LangSmith + 自定义记忆/调度引擎」的**多脑协同 + 动态闭环**：

- **多脑协同**：策略脑（规划）→ 调度（router）→ 并行检索 / 分析脑子图 / 生成脑子图 / 评估 → 汇总；分析脑、生成脑以**子图**方式接入，新增能力在各脑内以插件/子图扩展。
- **动态闭环**：评估后若 `need_revision` 则回到生成脑（条件边），形成「生成 → 评估 → 修订」闭环。
- **自定义记忆/调度**：记忆由现有 MemoryService 提供；调度由 **router 节点 + plan/current_step** 驱动，按 plan 决定下一节点（parallel_retrieval | analyze | generate | evaluate | skip | compilation）。

## 二、图结构（当前实现）

```
planning → router ─┬→ parallel_retrieval → router
                   ├→ analyze (分析脑子图) → router
                   ├→ generate (生成脑子图) → router
                   ├→ evaluate ─┬→ generate (需修订) ──→ router
                   │             └→ router (通过)
                   ├→ skip → router
                   └→ compilation → END
```

- **router**：根据 `plan` 与 `current_step` 决定下一节点（`_router_next`）；未知步骤走 `skip`，步数用尽走 `compilation`。
- **parallel_retrieval**：执行 plan 中从 `current_step` 起所有连续并行步（web_search、memory_query、bilibili_hotspot、kb_retrieve），合并结果并推进 `current_step`。
- **analyze**：调用**分析脑子图**（`workflows/analysis_brain_subgraph.py`），内部按 `analysis_plugins` 调插件中心，输出 `analysis`、`analyze_cache_hit`，并递增 `current_step`。
- **generate**：调用**生成脑子图**（`workflows/generation_brain_subgraph.py`），内部按 `generation_plugins` 调插件中心，输出 `content`，并递增 `current_step`。
- **evaluate**：调用 `ai_svc.evaluate_content`，写 `evaluation`、`need_revision`，并递增 `current_step`。
- **evaluate 后条件边**：`need_revision` 为真则下一节点为 `generate`（动态闭环），否则为 `router`。
- **skip**：未知步骤时仅递增 `current_step` 后回到 router。
- **compilation**：汇总思考过程与最终报告（与原先一致）。

## 三、子图与扩展约定；各脑插件是否已是 LangGraph 子图

- **分析脑 / 生成脑**：已以 **LangGraph 子图** 形式接入主图。分析脑子图、生成脑子图各自是独立的 `StateGraph`，主图通过 `analyze_node` / `generate_node` 调用 `analysis_subgraph.ainvoke(state)`、`generation_subgraph.ainvoke(state)`。
- **各脑内的插件**（如 methodology、case_library、knowledge_base、campaign_context、text_generator、campaign_plan_generator）：**尚未**变成 LangGraph 子图或节点。它们仍由「插件中心」调度：分析脑子图内单节点 `run_analysis` 调 `ai_svc.analyze()`，analyzer 内部再对 `analysis_plugins` 做 `plugin_center.get_output(name, context)` 并合并结果；生成脑同理。因此：
  - **脑** = 子图（已实现）；
  - **脑内插件** = 仍是插件中心的 `get_output` 调用，未建模为 LangGraph 的节点/子图。
- 若要将**各脑插件也变成 LangGraph 能力**（可观测、可流式、可单独 checkpoint）：需在分析脑子图内为每个插件建节点（如 `methodology`、`case_library`、`knowledge_base`、`campaign_context`），用条件边或顺序边组合，再合并结果；生成脑子图同理。当前未做此改造，扩展仍以「在插件中心注册 + 任务表配置」即可。
- **当前扩展约定**：
  - **分析脑子图**（`workflows/analysis_brain_subgraph.py`）：单节点 `run_analysis` 调 `ai_svc.analyze`，写回 `analysis`、`analyze_cache_hit`、`current_step`。**新增分析能力**：在分析脑插件中心注册插件，并在任务→插件注册表中配置 `analysis_plugins`，无需改子图结构。
  - **生成脑子图**（`workflows/generation_brain_subgraph.py`）：单节点 `run_generate` 调 `ai_svc.generate`，写回 `content`、`current_step`。**新增生成能力**：在生成脑插件中心注册插件，并在任务→插件注册表中配置 `generation_plugins`，无需改子图结构。

## 四、流式 / 人工介入 / 多轮：当前状态（已实现）

| 能力 | 是否已实现 | 说明 |
|------|------------|------|
| **流式** | ✅ 已实现 | 前端聊天接口支持 query 参数 `stream=true`，返回 SSE（`text/event-stream`），每步完成后推送当前 state（`stream_mode="values"`）。 |
| **人工介入（interrupt）** | ✅ 已实现 | 评估后若 `need_revision` 进入 `human_decision` 节点，节点内调用 `interrupt(...)` 暂停；返回 `__interrupt__` 与 state_snapshot。前端调用 `POST /api/v1/chat/resume` 传入 `session_id` 与 `human_decision`（revise \| skip），后端用 `Command(resume=human_decision)` 从断点继续。 |
| **多轮（断点续跑）** | ✅ 已实现 | 所有 meta 调用均传 `config={"configurable": {"thread_id": session_id}}`，同一 session_id 即同一线程；resume 时用同一 thread_id 调用 `meta.ainvoke(Command(resume=...), config=...)` 从上次断点继续。 |

## 五、Checkpointer 与流式（已接入）

- **Checkpointer**：`workflow.compile(checkpointer=...)` 已接入，默认使用 `MemorySaver()`（内存）；可替换为 Redis 等以实现跨请求/会话的暂停恢复与回溯。多轮续跑已在 ainvoke/astream 时传入 `config={"configurable": {"thread_id": session_id}}`。
- **流式**：主图支持 `astream`。前端聊天接口传 `?stream=true` 即返回 SSE，每步推送完整 state（`stream_mode="values"`）；可选 `stream_mode="updates"` 仅推送增量。子图内部流式可传 `subgraphs=True`（视 LangGraph 版本而定）。

## 六、LangSmith 与可观测性

- **LangSmith**：LangChain/LangGraph 在设置环境变量后会自动将调用轨迹上报 LangSmith，便于调试与监控。
- **配置**（建议在 `.env` 或部署环境中设置）：
  - `LANGCHAIN_TRACING_V2=true`
  - `LANGCHAIN_API_KEY=<your-langsmith-api-key>`
  - `LANGCHAIN_PROJECT=<project-name>`（可选，用于区分项目）
- **效果**：规划、各编排节点、分析脑子图、生成脑子图的执行会出现在 LangSmith 的 trace 中，可按 run/节点/步骤查看耗时与输入输出。
- **文档**：完整 Key 说明可放在 `docs/ENV_KEYS_REFERENCE.md` 的「可观测」一节。

## 七、涉及文件

| 文件 | 说明 |
|------|------|
| `workflows/types.py` | MetaState 增加 `search_context`、`memory_context`、`kb_context`、`effective_tags`。 |
| `workflows/analysis_brain_subgraph.py` | 分析脑子图：单节点调 `ai_svc.analyze`，写 `analysis`、`analyze_cache_hit`、`current_step`。 |
| `workflows/generation_brain_subgraph.py` | 生成脑子图：单节点调 `ai_svc.generate`，写 `content`、`current_step`。 |
| `workflows/meta_workflow.py` | 主图：planning → router（条件边）→ parallel_retrieval | analyze | generate | evaluate | skip | compilation；evaluate 后条件边实现闭环；`compile(checkpointer=MemorySaver())`。 |
| `main.py` | 各入口的 `initial_state` 增加 `search_context`、`memory_context`、`kb_context`、`effective_tags`、`analysis_plugins`、`generation_plugins`。 |

## 八、流式与性能

- **流式**：`POST /api/v1/frontend/chat?stream=true` 返回 SSE，使用 `meta.astream(..., stream_mode="values")` 按步骤推送 state；前端（Gradio 增强版）勾选「流式输出」可逐步看到思考过程与结果，避免长时间白屏。
- **耗时日志**：主图各节点（planning_node、parallel_retrieval_node、analyze_node、compilation_node）打 `logger.info` 耗时，便于定位瓶颈。
- **加速汇总**：环境变量 `USE_SIMPLE_THINKING_NARRATIVE=1` 时，汇总阶段不再调用 LLM 生成叙述，改为步骤列表拼接，约省 10–25s。见 [ENV_KEYS_REFERENCE.md](./ENV_KEYS_REFERENCE.md)。

## 九、LangGraph 上下文能力（多轮对话）

| 能力 | 是否具备 | 说明 |
|------|----------|------|
| **thread_id 持久化** | ✅ | 每次调用传 `config={"configurable": {"thread_id": session_id}}`，同一会话即同一 thread；Checkpointer（MemorySaver）按 thread_id 存图状态，用于**断点恢复**（evaluate 后 interrupt → resume）。 |
| **会话内上下文延续** | ✅ | 每轮请求的 `initial_state` 由当前请求 + **Redis 中的 session** 共同构建：`session_intent`（brand_name、product_desc、topic 等）从 `sm.get_session(session_id)` 的 `initial_data.session_intent` 读取并合并，实现「上一轮填过的品牌/话题在本轮延续」。 |
| **对话历史传入** | ✅ | 前端传 `request.history`，后端转为 `conversation_context` 供意图识别与规划使用；`user_input` 的 JSON 中可带 `conversation_context`，供策略脑/分析脑做多轮理解。 |
| **跨轮图状态恢复** | 仅断点 | 日常多轮是「每轮重新 ainvoke(initial_state)」；只有 **interrupt 后 resume** 才会从 Checkpointer 恢复图状态继续执行。 |

结论：**已具备多轮对话的上下文能力**——会话意图（session_intent）与对话历史（conversation_context）在轮次间延续；thread_id 保证同一会话下断点可恢复。每轮仍是一次完整图执行，上下文通过 initial_state 注入而非「接着上一轮图继续跑」。

## 十、后续可选

- **interrupt**：已在 `evaluate` 后通过 `human_decision` 节点 + `interrupt()` 实现人工修订/跳过。
- **Redis Checkpointer**：替换 `MemorySaver()` 为 LangGraph 的 Redis checkpointer，支持多实例与持久化。
