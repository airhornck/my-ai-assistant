# 三态流程 + 双 Plan 模式设计验证

本文档对照设计要点逐条验证当前实现，并标注差异与后续可改进点。

---

## 一、Intake 阶段

| 设计要点 | 实现位置 | 验证结果 |
|----------|----------|----------|
| 主要收集信息和做轻量理解 | `workflows/ip_build_flow.py`：`intake_node` 合并 `ip_context`、检查必填、生成 `pending_questions`；`meta_workflow.py`：`ip_build_router_node` 在 phase=intake 时调用 `intake_node` | ✅ 已实现：仅做字段合并与必填检查，不做重规划 |
| 即使没有固定 Plan，也可以用 IntentAgent + LLM 做自然语言理解 | `meta_workflow.py`：phase=intake 时先 `IntentAgent(llm).classify_intent(raw_query, ...)`，再 `intake_node(..., intent_result, extracted, llm)` | ✅ 已实现：每轮 intake 都走 IntentAgent，不依赖固定模板 |
| 根据用户输入生成动态 Plan 或直接决定响应类型 | `ip_build_flow.py`：`plan_once_node` 内先 `resolve_template_id(intent, ip_context)`，有固定模板则用 `get_plan(template_id)`，否则调用 `planning_agent.plan_steps(...)` 生成动态 Plan；plan 中可仅含一步如 `casual_reply`，即“直接决定响应类型” | ✅ 已实现：固定/动态二选一，动态 Plan 由 LLM 输出 steps |

---

## 二、动态 Plan 阶段

| 设计要点 | 实现位置 | 验证结果 |
|----------|----------|----------|
| 用户没有固定模板需求时，可生成动态 Plan | `ip_build_flow.py`：`resolve_template_id` 无匹配时返回 `PLAN_TEMPLATE_DYNAMIC`，随后 `plan_once_node` 调用 `planning_agent.plan_steps(...)`，得到 `steps` 写入 state.plan | ✅ 已实现 |
| 动态 Plan 不必包含 IP 打造步骤 | `core/intent/planning_agent.py`：规划原则中 casual_chat → 只规划 casual_reply；query_info → analyze + casual_reply（可选 web_search）；free_discussion → 可仅 casual_reply | ✅ 已实现：LLM 可按意图只输出闲聊/问答等，无 IP 步骤 |
| 可包含：闲聊（casual_reply）、问答（query_info）、建议（recommendation）、其他工具调用（如查询 KB、分析数据等） | `planning_agent.py`：STEP_TYPES 含 casual_reply、analyze、generate、web_search、memory_query、kb_retrieve、evaluate；`step_descriptions_for_planning.py` 描述齐全；`_ip_run_one_step` 已支持 memory_query / analyze / generate / casual_reply / web_search / kb_retrieve / evaluate | ✅ 已实现：动态 Plan 可含上述步骤，执行层均支持（含本次补充的 kb_retrieve、evaluate） |

---

## 三、执行阶段

| 设计要点 | 实现位置 | 验证结果 |
|----------|----------|----------|
| 每轮执行单步 | `ip_build_flow.py`：`execute_one_step_node` 只处理 `plan[current_step]`，执行一次 `step_runner(...)`，然后 `current_step += 1`；`meta_workflow.py` 在 phase=executing 时每轮只调一次 `execute_one_step_node` | ✅ 已实现 |
| step 类型：analyze → 调用插件分析；generate → 调用生成插件；casual_reply → 自然语言响应 | `meta_workflow.py`：`_ip_run_one_step` 内对 `analyze` 调 `ai_svc.analyze(..., analysis_plugins=...)`；对 `generate` 调 `ai_svc.generate(...)`；对 `casual_reply` 用 llm 生成简短回复或 params.message | ✅ 已实现 |
| 固定 Plan 与动态 Plan 执行逻辑一致 | `execute_one_step_node` 与 `_ip_run_one_step` 不区分 plan_template_id；统一按 `plan[current_step]` 的 step 类型与 params 执行 | ✅ 已实现 |

---

## 四、本次代码补充（与验证结论一致）

- **执行层支持 kb_retrieve / evaluate**：在 `meta_workflow.py` 的 `_ip_run_one_step` 中为 `kb_retrieve`、`evaluate` 增加分支，使动态 Plan 中若包含这两类步骤也能在 IP 流程中执行，而不是返回 `skipped`。
- **汇总输出包含评估结果**：在 `ip_build_flow.py` 的 `_compile_step_outputs` 中，对 step 的 `result` 含 `suggestions` 或 `overall_score` 时拼入最终文案，保证以 evaluate 结尾的 Plan 能展示评估结果。

---

## 五、小结

| 维度 | 结论 |
|------|------|
| Intake：收集 + 轻量理解 | ✅ 符合设计 |
| Intake：无固定 Plan 时仍用 IntentAgent + LLM 理解 | ✅ 符合设计 |
| Intake：可生成动态 Plan 或直接决定响应类型 | ✅ 符合设计 |
| 动态 Plan：可不含 IP 步骤、可含闲聊/问答/建议/工具调用 | ✅ 符合设计 |
| 执行：每轮单步；analyze/generate/casual_reply 及 kb_retrieve、evaluate 统一执行 | ✅ 符合设计 |
| 固定 Plan 与动态 Plan 执行逻辑一致 | ✅ 符合设计 |

当前实现满足「三态流程 + 双 Plan 模式」的上述设计要求；后续若新增 step 类型，只需在 `_ip_run_one_step` 与（按需）`_fill_step_params`、`_compile_step_outputs` 中扩展即可。
