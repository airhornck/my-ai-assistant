# 策略脑规划编排 vs 模型驱动的 Agent/工具编排（OpenClaw 式）

本文档梳理当前**策略脑**的规划与编排逻辑，并与 **OpenClaw 式「模型驱动、多步选工具+参数」** 的 Agent 编排做对比，便于后续演进为「可多步、参数由模型从自然语言解析」的能力。

---

## 一、当前策略脑的规划与编排逻辑

### 1.1 整体流程

```
用户请求 → planning_node（策略脑）→ router → [ parallel_retrieval | analyze | generate | evaluate | skip | casual_reply ] → … → router → compilation → END
```

- **单次规划**：入口只调用一次 `planning_node`，由 LLM 输出**整条思维链**（一个 JSON：`task_type` + `steps: [{step, params, reason}, ...]`）。
- **固定序列执行**：编排层不再次问模型「下一步做什么」，而是严格按 `plan` 与 `current_step` 推进；router 根据 `plan[current_step]` 决定进入哪个节点，执行完后 `current_step += 1` 再回到 router，直到 `current_step >= len(plan)` 进入 compilation。

### 1.2 策略脑（planning_node）在做什么

| 环节 | 行为 |
|------|------|
| 输入 | `state.user_input`（JSON：brand_name, product_desc, topic, raw_query, intent, conversation_context, explicit_content_request, session_suggested_next_plan 等） |
| 快路径 | 极短闲聊、模糊评价、采纳建议等可走规则/短路，直接给出 `plan`（如 `[casual_reply]`），不调 LLM。 |
| 主路径 | 将「可用模块」列表 + 大量专家规则写进 **system_prompt**，user_prompt 里注入用户目标、是否要求生成、上下文等；**一次 LLM 调用** 得到 `{ task_type, steps }`。 |
| 输出 | `plan`（步骤数组）、`task_type`、`analysis_plugins` / `generation_plugins`（可由注册表推断或 LLM 指定）。 |

**工具/能力描述方式**：在 system 里用自然语言枚举（如 web_search、memory_query、kb_retrieve、bilibili_hotspot、analyze、generate、evaluate、casual_reply），并约定每步的 `step`、`params`、`reason`。**模型只产出「步骤序列 + 每步的 params」**，不产出可被运行时直接解析的 tool_call schema（如 name + arguments）。

### 1.3 编排层如何执行

| 节点 | 作用 |
|------|------|
| **router** | 根据 `plan[current_step]` 的 `step` 名字，决定下一跳：并行检索类 → `parallel_retrieval`，analyze → `analyze`，generate → `generate`，evaluate → `evaluate`，casual_reply → `casual_reply`，未知 → `skip`；若 `current_step >= len(plan)` → `compilation`。 |
| **parallel_retrieval** | 从当前 `current_step` 起，连续执行 plan 中所有「并行步」（web_search, memory_query, bilibili_hotspot, kb_retrieve），合并结果，然后 `current_step` 跳到下一个非并行步。 |
| **analyze / generate / evaluate** | 各对应一个子图或直接调用；**参数来源**：从 `plan[current_step].params` 读（如 generate 的 platform、output_type），**不是**本步再问模型「生成时用什么参数」。 |
| **skip** | 未识别的 step 只做 `current_step += 1`，不执行能力。 |
| **compilation** | 汇总 thinking_logs、step_outputs、content，生成叙述式思维链与最终回复、后续建议等。 |

**参数从哪里来**：  
- 绝大部分来自 **planning 时 LLM 一次性写好的 `steps[i].params`**（如 `web_search` 的 `query`、`generate` 的 `platform`）。  
- 少数在编排层用上下文**补全**：例如 web_search 若 params 无 `query`，用 `brand + product + topic` 拼。  
- **没有**「执行完一步 → 把结果再给模型 → 模型决定下一步选哪个工具、传什么参数」的闭环。

### 1.4 小结：当前模式

- **规划**：一次 LLM，输出整条 `plan`（多步序列 + 每步 params）。  
- **执行**：按 `plan` 与 `current_step` 顺序/并行执行，**不再**让模型根据中间结果做「下一步选谁、参数填什么」。  
- **参数**：主要由首轮规划时的 LLM 生成（自然语言理解体现在「写 steps + params」），执行层只做读取与少量补全，**没有**「每步前由模型从自然语言解析出工具参数」的循环。

---

## 二、OpenClaw 式「模型驱动」Agent/工具编排

### 2.1 核心：Reasoning Loop（推理环）

OpenClaw 的 agent 不是「先规划一整条链再执行」，而是**循环**：

1. **Load**：加载上下文（对话历史、记忆、system prompt）。
2. **Call**：把**工具列表**（名称、描述、参数 schema）和当前上下文一起给 LLM。
3. **Parse**：解析 LLM 输出 —— **纯文本**（最终回复）或 **tool_call(name, arguments)**。
4. **Execute**：若是 tool_call，执行对应工具，得到结果。
5. **Append**：把「本次 tool_call + 执行结果」追加进上下文。
6. **Loop**：回到步骤 2，直到 LLM 产出**最终文本**（不再发起 tool_call）。

这样，**每一步「选哪个工具、传什么参数」都由模型在看到「当前上下文 + 上一步结果」后当场决定**，实现「规划 → 执行 → 观察 → 再规划」的多步能力。

### 2.2 与「工具列表 + 参数由模型解析」的对应关系

| 维度 | OpenClaw 式 | 当前策略脑 |
|------|-------------|------------|
| 工具暴露方式 | 工具列表（名 + 描述 + 参数 schema）显式给模型，模型输出**结构化 tool_call**。 | 在 system 里用自然语言描述「可用模块」，模型输出**步骤数组 + 每步 params**（仍是 JSON，但非标准 tool_call 接口）。 |
| 参数来源 | **每步**由模型根据当前上下文和上一步结果，**解析自然语言/上下文**后填 tool 的 arguments。 | **首轮规划**时模型一次性写出所有 steps 的 params；执行时只读 `plan[i].params`，不再问模型。 |
| 多步如何产生 | **循环**：执行 → 结果进上下文 → 再调 LLM → 再选工具+参数 → … 直到模型返回最终文本。 | **单次规划**：一次 LLM 产出整条 steps；执行层按 steps 顺序跑，**不**在每步后再问模型。 |
| 是否可「根据结果再决策」 | 可以。例如搜索无结果，下一轮模型可改 query 或换工具。 | 不可以。plan 固定后，不会因为某步结果差而「换下一步」或「改参数」。 |

因此，要实现「**模型驱动：把工具列表给模型 → 模型选工具+参数（并可多步）→ 执行 → 结果再给模型决定是否继续**」，需要引入的就是这类 **reasoning loop**，而不是「一次 plan，线性执行」。

---

## 三、对比总结

| 能力/特性 | 当前策略脑 | OpenClaw 式 Agent 编排 |
|-----------|------------|--------------------------|
| 规划次数 | **一次**（首轮产出整条 plan） | **多轮**（每步执行后都可再调 LLM） |
| 工具列表 | 自然语言写在 prompt 里，模型输出自定义 JSON（steps + params） | 工具列表 + schema 显式给模型，模型输出标准 tool_call(name, args) |
| 参数由谁定 | 首轮规划时模型写出 params；执行层只读 | **每步**由模型根据最新上下文和上一步结果解析出参数 |
| 多步 | 有（plan 里多步），但**顺序与内容固定** | 多步且**可自适应**（根据结果改下一步或参数） |
| 错误/结果不佳 | 无法在本轮根据执行结果「换策略」 | 可看到错误/空结果，下一轮改 tool 或 params |
| 自然语言解析参数 | 仅体现在「首轮写 steps[].params」 | 每一步都可从自然语言/对话中解析出当前步的参数 |

---

## 四、若要演进为「模型驱动、可多步、参数由模型解析」

在不完全重写的前提下，可以分阶段做：

1. **工具层统一**  
   - 将现有「步骤」（web_search、memory_query、analyze、generate 等）抽象成**统一工具表**：name、description、parameters（JSON schema）。  
   - 编排层不再依赖「步骤名 + 手写 params」，而是接收「tool_call(name, arguments)」。

2. **引入单步「模型选工具+参数」**  
   - 在**每一步**执行前（或仅在「需要下一步」时）：  
     - 把**当前上下文**（用户目标、已有 step_outputs、上一步结果）+ **工具列表** 给 LLM；  
     - 要求 LLM 输出：要么 `tool_call(name, arguments)`，要么 `final_response(text)`。  
   - 若为 tool_call：执行该工具，把结果 append 到上下文，再调 LLM；若为 final_response：结束并返回该文本。

3. **保留现有策略脑作为「建议序列」**（可选）  
   - 仍可保留当前 planning_node 作为**建议**（suggested_plan），在 loop 中作为 hint 注入模型（「专家建议的步骤顺序是 …」），但**下一步实际选谁、参数是什么**由 loop 中的模型调用决定，从而兼容「可多步 + 参数由模型从自然语言解析」的目标。

4. **终止与防护**  
   - 最大迭代次数（如 10～20）、超时、用户中断等，与 OpenClaw 的 guardrails 一致，避免死循环或过长链。

这样即可在保留现有「策略脑」语义（专家规则、任务类型、插件体系）的基础上，逐步对齐「模型驱动：工具列表 → 模型选工具+参数 → 执行 → 结果再给模型决定是否继续」的成熟 Agent/工具编排模式，最终实现**可多步、且参数由模型从自然语言与上下文解析**的能力。

---

## 五、深度思考/思维链规划：哪种编排更合理？是否有必要改？

### 5.1 你的早期目的

目标是**类似深度思考的思维链规划**：先有一条可见的「思考链」（检索 → 分析 → 生成 → 评估），再按链执行，便于可解释、可审计、可控制。因此设计了**策略脑（一次产出整条 plan）+ 插件列表**的模式。

### 5.2 两种编排的适用场景对比

| 维度 | 当前策略脑（一次规划 + 按 plan 执行） | OpenClaw 式（每步由模型选工具+参数再执行） |
|------|--------------------------------------|--------------------------------------------|
| **目标** | 显式思维链、可解释、流程可控 | 开放任务、根据结果灵活调整下一步 |
| **「深度思考」体现** | **强**：plan 本身就是思维链的显式表示，用户/调试可见「先搜→再分析→再生成」 | **弱**：链是隐式的（在多次 LLM 调用中），单次没有「整条链」的文档 |
| **可审计性** | **强**：一条 plan 对应一次执行轨迹，易复现、易排查 | 依赖多轮对话与 tool 历史，链更长、更散 |
| **可控性** | **强**：专家规则在 prompt 里约束「何时生成、何时只分析」，执行不跑偏 | 模型每步都可「自作主张」，需靠 prompt/guardrail 约束 |
| **适应性** | **弱**：某步失败或结果差，不会自动换策略或改参数 | **强**：可根据上一步结果改 query、换工具、重试 |
| **与插件模式** | **天然契合**：plan 的 step 名直接对应插件/能力，注册即可被编排 | 需把插件包装成「工具」+ schema，模型输出 tool_call 再映射到插件 |

结论：**没有绝对「更合理」**，取决于你要优先保证什么。

- **优先「深度思考/思维链规划」**：希望有一条**可见、可解释、可控制的思维链** → 当前策略脑 + 插件列表的模式**更贴合**。
- **优先「开放任务、根据结果随时改下一步」**：例如通用助手、复杂检索+多轮决策 → OpenClaw 式**更合适**。

### 5.3 在保留插件模式的前提下，是否有必要修改？

**不必为「像 OpenClaw」而重写**，理由可以概括为：

1. **目标一致**：你要的是思维链规划 + 可解释，当前设计正是「先出链、再按链执行」，和深度思考的诉求一致。
2. **插件模式保留**：step 与插件/能力一一对应，扩展新能力只需注册插件并在策略脑的「可用模块」里描述，无需改成 tool_call schema 才能用。
3. **成本与风险**：全盘改成「每步都调模型选工具+参数」会引入更多 LLM 调用、更长上下文、更复杂的终止与防护，对「可解释、可控」不一定更好。

**可选的小步增强（不推翻现有设计）**：

- **失败/空结果时的补救**：某一步执行失败或返回空（如搜索无结果）时，**可选**地再调一次模型：「当前 plan 第 i 步结果为空/失败，请给出补救步骤（如换 query 或跳过）」，得到 1～2 步的补充 plan 再执行。这样仍保留「主链由策略脑一次规划」，只在异常时引入一次「模型再决策」。  
  **实现**：在 `parallel_retrieval_node` 中，首轮并行步执行后若存在失败或检索结果为空（且计划含 web_search），则调用 `_request_remedial_steps` 请求 1～2 步补救（仅允许 `web_search` / `skip`），再执行并合并结果；每轮只做一次补救，避免循环。可通过 `user_input.remedial_on_empty: false` 关闭。
- **参数补全**：若某步 `params` 缺关键字段（如 web_search 的 query），可以在执行前用**规则**从 `raw_query` / 品牌·产品·话题 补全，再执行。  
  **实现**：`_complete_step_params(step_name, params, user_data)` 对 `web_search`、`kb_retrieve` 补全 `query`（缺省时用 `raw_query` 或 `brand + product + topic`），在 `parallel_retrieval_node` 的 `_run_web_search` / `_run_kb_retrieve` 中执行前调用，无额外 LLM。

这样可以在**保留插件模式与当前策略脑主流程**的前提下，按需增加一点「根据结果再决策」或「参数补全」能力，而不必整体切到 OpenClaw 式编排。
