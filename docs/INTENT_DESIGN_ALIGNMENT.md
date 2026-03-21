# 意图模块改造对照：设计 vs 当前实现

本文档对照《总体改造思路》检查当前意图相关实现是否对齐。

---

## 一、总体结论

| 模块 | 设计要点 | 当前实现 | 对齐情况 |
|------|----------|----------|----------|
| 意图识别（Intent Agent） | 大模型理解、多轮上下文、结构化输出、置信度 + fallback | 已实现，支持多轮、置信度、澄清 | ✅ 已对齐 |
| 策略脑（Planning Agent） | 只输出 plan（步骤+插件），不生成文案 | 已实现，从插件中心动态取插件列表 | ✅ 已对齐 |
| 执行脑 / Analyzer | 按 plan 动态调用插件，不硬编码 | 分析脑按插件列表调用；router 已改为优先保留 plan 的插件，analyze_node 按当前步 plugins 执行 | ✅ 已对齐（见文档内修改说明） |
| 循环推理 | ReAct 风格：模型根据状态决定下一步 | 有 reasoning_loop 节点，但是**规则判断**，非模型决策 | ⚠️ 部分对齐 |

---

## 二、分模块对照

### 1️⃣ 意图识别模块（Intent Agent）—— ✅ 已对齐

**位置**: `core/intent/intent_agent.py`

- **大模型理解自然语言**: 使用 `INTENT_CLASSIFY_SYSTEM` + 示例，调用 `llm.invoke`。
- **多轮上下文**: `classify_intent(user_input, conversation_context)` 支持传入 `conversation_context`。
- **结构化输出**: 返回 `intent`, `confidence`, `raw_query`, `notes`；并扩展了 `need_clarification`, `clarification_question`。
- **置信度 + fallback**: `CONFIDENCE_THRESHOLD = 0.6`，低于时置 `need_clarification=True`，并给出澄清问题；解析失败时 `_default_result()` 返回默认意图。
- **意图类型**: 除设计中的 `generate_content | casual_chat | query_info` 外，增加了 `account_diagnosis`, `strategy_planning`, `free_discussion`，符合业务需求。

**在 meta_workflow 中的使用**（`workflows/meta_workflow.py`）:

- `planning_node` 中先调用 `intent_agent.classify_intent(raw_query, conversation_context)`。
- 若 `need_clarification`，直接返回仅含 `casual_reply` 的 plan，并带上澄清话术，不进入后续规划与执行。

结论：意图识别部分已按设计实现，且与 workflow 正确衔接。

---

### 2️⃣ 策略脑（Planning Agent）—— ✅ 已对齐

**位置**: `core/intent/planning_agent.py`

- **角色**: 只做“根据意图规划步骤和插件”，不生成最终文案或策略正文。
- **输出结构**: `plan_steps()` 返回 `task_type` + `steps`，每步含 `step`, `plugins`, `reason`，与设计中的 JSON 一致。
- **插件动态化**: 通过 `_get_available_plugins()` 从 `BrainPluginCenter` 的 `ANALYSIS_BRAIN_PLUGINS` / `GENERATION_BRAIN_PLUGINS` 拉取可用插件名，并写入系统 prompt，由模型在 plan 的 `plugins` 里选择。
- **fallback**: 解析失败或异常时 `_fallback_plan(intent)` 按意图给出兜底步骤（如 generate_content → analyze + generate）。

**在 meta_workflow 中的使用**:

- `planning_node` 在意图识别后调用 `planning_agent.plan_steps(intent_result, user_data, conversation_context)`。
- 从 `plan_result["steps"]` 中按 step 类型汇总出 `analysis_plugins` / `generation_plugins` 并写入 state（见 planning_node 中 196–209 行）。

结论：策略脑已按“计划/调度脑”改造，输出 plan 且与插件列表一致。

---

### 3️⃣ 执行脑 / Analyzer —— ⚠️ 插件列表被覆盖，未完全按 plan 执行

**设计**: 根据策略脑的 plan 调用插件；插件调用动态化，由 plan 指定，不硬编码。

**当前实现**:

- **分析脑**（`domain/content/analyzer.py`）  
  - `ContentAnalyzer.analyze(..., analysis_plugins=...)` 支持传入插件列表，并通过 `_run_analysis_plugins()` 调用 `plugin_center.get_output(name, context)`，行为上支持“按列表动态调用”。
- **执行路径**  
  - 主流程走 LangGraph 分节点：`router` → `parallel_retrieval` / `analyze` / `generate` / … → `reasoning_loop` → 继续或 `compilation`。  
  - `planning_node` 已正确从 plan 的 steps 中解析出 `analysis_plugins`、`generation_plugins` 并写入 state。
- **问题所在**（`workflows/meta_workflow.py` 的 `router_node`）:  
  - 在 `router_node` 中会调用 `get_plugins_for_task(task_type, step_names)`，并用其结果**覆盖** state 中的 `analysis_plugins` 和 `generation_plugins`（约 776–781 行）。  
  - `get_plugins_for_task` 来自 `core/task_plugin_registry.py`，是静态的 `task_type → 插件列表` 映射。  
  - 因此，Planning Agent 在 plan 中动态选择的插件**没有真正被使用**，实际执行的是 `TASK_PLUGIN_MAP` 的固定配置。

**已做修改**（保持“以 plan 为准”的设计）:

- 在 `router_node` 中：**仅当** planning 阶段未给出任何插件列表（`analysis_plugins` 与 `generation_plugins` 均为空）时，才用 `get_plugins_for_task()` 兜底；否则保留 planning 写入的列表。  
- 在 `analyze_node` 中：当前步骤的插件优先从该步的 `step_config["plugins"]`（Planning Agent 输出）读取，其次从 `params.analysis_plugins`，再次从 state 已汇总的 `analysis_plugins`。  
- 这样“执行脑”真正按 plan 指定插件动态调用，与设计一致。

---

### 4️⃣ 循环推理（OpenClaw / ReAct 风格）—— ⚠️ 仅规则判断，非模型决策

**设计**: 类似 ReAct agent；模型不断接收用户输入 + 当前状态 + 插件输出，决定下一步动作（generate / analyze / casual_reply / ask_clarification），意图误判可在循环中纠正。

**当前实现**（`workflows/reasoning_loop.py`）:

- `reasoning_loop_node(state)` 根据 `intent`、`current_step`、`plan`、上一步输出（如是否已生成内容、是否闲聊回复等）做**规则判断**，得到 `_should_continue`、`_next_action`（continue / end）。
- 没有调用 LLM，也没有“根据用户输入 + 状态 + 插件输出再识别意图或再规划”的步骤。
- 循环结构存在：`parallel_retrieval` / `analyze` / `generate` / `skip` → `reasoning_loop` → 继续到 `router` 或结束到 `compilation`，因此**多步执行 + 上下文累积**是有的，但**意图纠正与下一步动作的模型决策**未实现。

**若要完全对齐设计**（可选增强）:

- 在 `reasoning_loop_node` 中，在关键节点（例如某步失败、或置信度曾较低）调用 Intent Agent 或一个小型“下一步决策”模型，输入：用户输入、当前 state 摘要、最近插件输出，输出：是否继续、下一动作类型、是否更新意图。  
- 当前规则版可保留为轻量、低成本方案；若需“意图在循环中纠正”，再引入上述模型调用。

---

## 三、是否还需要策略脑？—— ✅ 已按设计保留并调整角色

- **旧策略脑**（若曾存在于 analyzer 中）：直接输出推广策略/文案，硬编码。  
- **新策略脑**（Planning Agent）：只做“根据意图规划步骤 + 插件”，不生成最终内容；CoT 链规划保留，workflow 可控、可扩展。  
- 当前代码中策略脑已按“计划/调度脑”使用；执行脑（分析脑/生成脑）负责真正输出。  
- 唯一偏差是：执行时插件列表被 `task_plugin_registry` 覆盖，需按上文修改 router，以 plan 的插件列表为准。

---

## 四、修改建议汇总

1. **必须（完全符合设计）** —— ✅ 已实现  
   - **router 不再覆盖 plan 的插件列表**：`router_node` 仅在 state 中无任何 plan 插件列表时才用 `get_plugins_for_task` 兜底。  
   - **analyze_node 使用当前步骤的 plugins**：当前步的插件优先从 `step_config["plugins"]` 读取，与 Planning Agent 输出一致。

2. **可选（增强 ReAct/意图纠正）**  
   - 在 `reasoning_loop_node` 中增加“模型决策”分支：在需要时调用 LLM，根据当前状态与插件输出决定是否继续、下一动作或是否更新意图，实现设计中的“意图误判可在循环中纠正”。

---

## 五、文件索引

| 模块 | 文件路径 |
|------|----------|
| 意图识别 | `core/intent/intent_agent.py` |
| 策略规划 | `core/intent/planning_agent.py` |
| 执行（分析脑） | `domain/content/analyzer.py` |
| 插件中心 | `core/brain_plugin_center.py` |
| 任务→插件映射（当前覆盖 plan） | `core/task_plugin_registry.py` |
| 循环推理节点 | `workflows/reasoning_loop.py` |
| 主工作流（planning + router + 执行） | `workflows/meta_workflow.py` |
