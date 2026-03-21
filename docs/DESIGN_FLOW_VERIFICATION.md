# 设计流程实现对照

对照「用户输入阶段 → Plan 生成阶段 → Plan 执行阶段 → 最终输出阶段」逐项核对代码实现。

---

## 一、用户输入阶段（Intake）

| 步骤 | 设计描述 | 实现位置 | 状态 |
|------|----------|----------|------|
| 1 | 用户输入业务/产品信息 | 前端/API：`message` → `main.py` frontend_chat；`user_input` 进入 workflow | ✅ |
| 2 | IntentAgent 解析意图 + 字段抽取 | **首轮（未进 workflow）**：`main.py` 使用 `InputProcessor.process()` → `intent`、`structured_data`（brand_name, product_desc, topic）。**进入 workflow 后**：`meta_workflow.ip_build_router_node` 在 `phase==IP_BUILD_PHASE_INTAKE` 时调用 `IntentAgent(llm).classify_intent(raw_query)`；字段从当轮 `user_input` 解析出的 `user_data` 中取（main 将 `structured_data` 放入 `user_input_payload`） | ✅ |
| 3 | 更新 ip_context | `intake_guide.merge_context(session_ip_context, extracted)`；首轮在 main 门控里合并 `current_extract`；workflow 内由 `ip_build_flow.intake_node` 调用 `merge_context(base.get("ip_context"), extracted_fields)` | ✅ |
| 4 | 检查缺失字段 → 生成 pending_questions | `intake_guide.missing_required(ip_context)`、`intake_guide.build_pending_questions(missing, intent, max_questions=3)`；intake_node 中 `missing = missing_required(ip_context)`，有缺失则 `pending_questions = build_pending_questions(...)` | ✅ |
| 5 | 向用户友好提问（选项化/少量/可跳过） | `intake_guide.questions.QUESTION_MAP` 配置 options、optional；`build_pending_questions` 最多 3 条；main 门控与 intake_node 返回的 `pending_questions` 含 question/options/optional，前端可渲染 | ✅ |
| 6 | 用户回答 → 更新 ip_context | 下一轮请求带新 message；main 将 `structured_data` 写入 `user_input_payload`；workflow 若 `phase==intake` 再次走 intake_node，`extracted` 从 `user_data` 取，`merge_context` 更新 ip_context | ✅ |
| 7 | 判断是否达到阈值（必填字段齐） | `intake_node`：`if not missing` → 返回 `phase=IP_BUILD_PHASE_PLANNED`、`pending_questions=[]`；否则保持 `phase=IP_BUILD_PHASE_INTAKE` | ✅ |

**入口与门控**：创作意图且缺必填时，`main.py` 在调用 workflow 前做「创作前 Intake 门控」：`needs_clarification` + 创作类 intent → 用 intake_guide 生成 ip_context、pending_questions，写 session（phase=intake, ip_context, pending_questions），直接返回引导回复，不进入策略链。下一轮 session 带 phase=intake，进入 workflow 后由 `ip_build_router` 走 intake 分支。

---

## 二、Plan 生成阶段（Planned）

| 步骤 | 设计描述 | 实现位置 | 状态 |
|------|----------|----------|------|
| 1 | 判断 Plan 类型 | `ip_build_flow.plan_once_node`：`resolve_template_id(intent, ip_context)` → 固定模板 ID 或 `PLAN_TEMPLATE_DYNAMIC`；`get_plan(template_id)` 有步骤则为固定 Plan，否则走 PlanningAgent | ✅ |
| 1a | 固定 Plan：选择系统模板（IP诊断、账号打造、内容矩阵） | `plans.registry.resolve_template_id` 按已注册的 intent_selector 匹配；`plans.templates.*` 下各模板（ip_diagnosis, account_building, content_matrix 等） | ✅ |
| 1b | 动态 Plan：LLM 分析 Intent → 生成 Plan + 参数模板 | `plan_once_node` 中 `plan = get_plan(template_id)` 为 None 时调用 `planning_agent.plan_steps(intent_data, user_data, ...)`，得到 `steps`，并设 `plan_template_id=PLAN_TEMPLATE_DYNAMIC` | ✅ |
| 2 | Plan 写入 session/MetaState | `plan_once_node` 返回的 state 含 `plan`、`plan_template_id`；main 在 workflow 返回后 `if result.get("ip_build_handled")` 将 `phase, ip_context, plan, current_step, step_outputs, pending_questions, plan_template_id, intent` 写回 `session.initial_data`（main 2180–2210 行） | ✅ |
| 3 | phase = "executing" | `plan_once_node` 返回 `phase=IP_BUILD_PHASE_EXECUTING` | ✅ |
| 4 | current_step_idx = 0 | `plan_once_node` 返回 `current_step=0`、`step_outputs=[]` | ✅ |

---

## 三、Plan 执行阶段（Execute）

| 步骤 | 设计描述 | 实现位置 | 状态 |
|------|----------|----------|------|
| 1 | 读取 current_step_idx → 当前 step | `ip_build_flow.execute_one_step_node`：`current_step = int(base.get("current_step") or 0)`，`step_config = plan[current_step]` | ✅ |
| 2 | 填充参数 (ip_context + step_outputs) | `_fill_step_params(step_config, ip_context, step_outputs, user_input_data)` → `(filled_params, missing)`；generate 步补 platform 等 | ✅ |
| 3 | 参数缺失? | `if missing`：返回 `pending_questions`（platform 等有专用选项文案）、`phase=IP_BUILD_PHASE_EXECUTING`、不递增 current_step，暂停执行 | ✅ |
| 3b | 否 → 执行对应插件/模块 → 保存 step_outputs | `step_runner(base, step_config_filled, ip_context, step_outputs)` 即 `_ip_run_one_step`（analyze/memory_query/generate/casual_reply/web_search/kb_retrieve/evaluate 等）；结果 append 到 `step_outputs` | ✅ |
| 4 | step 完成 → current_step_idx += 1 | `next_idx = current_step + 1`；未到 plan 末尾则返回 `current_step=next_idx`、`step_outputs` 更新 | ✅ |
| 5 | Plan 完成? | `if next_idx >= len(plan)` → 返回 `phase=IP_BUILD_PHASE_DONE`、`content=_compile_step_outputs(step_outputs)` | ✅ |
| 5b | 否 → 循环下一 step | 返回仍为 `phase=IP_BUILD_PHASE_EXECUTING`、`current_step=next_idx`；下一轮请求再次进入 `ip_build_router`（phase==executing）→ `execute_one_step_node` | ✅ |
| 6 | 用户中断 Plan? | `_detect_execute_interrupt(user_input_data, raw_query)`：继续/放弃/重规划 关键词 | ✅ |
| 6a | 是 → 提示用户: 继续 / 放弃 / 重规划 | **放弃**：返回 `phase=IP_BUILD_PHASE_DONE`、content 提示已放弃。**重规划**：返回 `phase=IP_BUILD_PHASE_PLANNED`、`plan=[]`、`current_step=0`、`step_outputs=[]`、`pending_questions` 含“已清空当前计划…” | ✅ |
| 6b | 否 → 持续执行下一步 | 不进入 interrupt 分支，按 3/4/5 执行当前步并推进 | ✅ |

---

## 四、最终输出阶段

| 步骤 | 设计描述 | 实现位置 | 状态 |
|------|----------|----------|------|
| 1 | 合并所有 step_outputs | `ip_build_flow._compile_step_outputs(step_outputs)`：按 step 的 result（reply/summary/content/account_diagnosis/angle/overall_score+suggestions）拼成文案 | ✅ |
| 2 | 生成用户期待的 IP 打造方案/内容方案 | 执行阶段最后一步完成后返回的 `content` 即 _compile_step_outputs 结果；main 中 `final_content = result.get("content")`，作为 `response` 返回前端 | ✅ |
| 3 | 返回前端/用户 | frontend_chat 返回 JSON：`response`、`session_id`、`phase`、`ip_context`、`pending_questions`、`thinking_process` 等；流式时最后一帧同样含 content 与上述字段 | ✅ |
| 4 | 可展示中间步骤/执行说明（可选） | `step_outputs`、`thinking_logs` 写回 session；响应中可带 `thinking_process`；前端可根据 `phase`、`pending_questions`、step_outputs 展示进度与中间步骤 | ✅ |

---

## 五、会话与状态持久化

| 约定 | 实现 |
|------|------|
| 请求前从 session.initial_data 合并 phase、ip_context、plan、current_step、step_outputs 到 state | main 构建 `initial_state` 时从 `existing_session_data["initial_data"]` 恢复 `phase, ip_context, plan, current_step, step_outputs, pending_questions, plan_template_id, intent`（2078–2082 行） |
| 请求后将 state 中上述字段及 pending_questions、content 写回 session | main 在 workflow 返回后 `updated_initial_data.update(...)` 且 `if result.get("ip_build_handled")` 时写回 phase、ip_context、plan、current_step、step_outputs、pending_questions、plan_template_id、intent、content（2199–2210 行）；流式结束时同样更新（2122–2146 行） |

---

## 六、结论

- **用户输入阶段（Intake）**：1～7 均在 main 门控 + intake_guide + ip_build_flow.intake_node + meta_workflow.ip_build_router 中实现；首轮由门控直接返回引导，后续轮次由 workflow 内 intake 分支处理。
- **Plan 生成阶段（Planned）**：固定/动态判断、写入 state、phase=executing、current_step=0 均在 plan_once_node 及 session 写回中实现。
- **Plan 执行阶段（Execute）**：单步执行、参数填充、缺参暂停、步进、完成与中断（继续/放弃/重规划）均在 execute_one_step_node 与 _ip_run_one_step 中实现。
- **最终输出阶段**：合并 step_outputs、生成方案、返回前端、可选展示中间步骤均已实现。

整体设计流程与当前实现**一致**，可按本文档做回归与产品验收。
