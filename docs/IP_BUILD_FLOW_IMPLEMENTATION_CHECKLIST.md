# IP 打造三态流程实现检查清单

对照「三态流程图 + 双 Plan + 用户补充 + 执行逻辑」规格的落地情况。

---

## 一、用户输入阶段（Intake）

| 规格项 | 实现位置 | 状态 |
|--------|----------|------|
| 1. 用户输入业务/产品信息 | 请求 body / user_input | ✅ |
| 2. IntentAgent 解析意图 + 字段抽取 | `meta_workflow.ip_build_router_node` 调用 IntentAgent；extracted 从 user_data 取 `IP_INTAKE_REQUIRED_KEYS` + `IP_INTAKE_OPTIONAL_KEYS` | ✅ |
| 3. 更新 ip_context | `ip_build_flow.intake_node` → `_merge_ip_context`，不覆盖已有非空 | ✅ |
| 4. 检查缺失字段 → 生成 pending_questions | `_missing_required_keys` + `_build_pending_questions`（1～3 条） | ✅ |
| 5. 向用户友好提问（选项化/少量/可跳过） | `_build_pending_questions` 中 Q_MAP 含 options、optional | ✅ |
| 6. 用户回答 → 更新 ip_context | 下一轮请求带新字段，intake_node 再次 _merge_ip_context | ✅ |
| 7. 判断是否达到阈值（必填字段齐） | `_missing_required_keys` 为空则返回 phase=planned | ✅ |

**缺口**：无。可选增强：返回中带 `ip_context_summary` 供前端「回显已收集信息」。

---

## 二、Plan 生成阶段（Planned）

| 规格项 | 实现位置 | 状态 |
|--------|----------|------|
| 1. 判断 Plan 类型 | `ip_build_flow.plan_once_node` + `_choose_plan_template` | ✅ |
| 1a. 固定 Plan：系统模板（IP诊断、账号打造、内容矩阵） | `config/ip_build_plan_templates.py`：`TEMPLATE_IP_DIAGNOSIS`、`TEMPLATE_ACCOUNT_BUILDING`、`TEMPLATE_CONTENT_MATRIX`；`get_fixed_plan(template_id)` | ✅ |
| 1b. 动态 Plan：LLM 分析 Intent → 生成 Plan + 参数模板 | `PlanningAgent.plan_steps(intent_data, user_data, ...)`，steps 带 params | ✅ |
| 2. Plan 写入 session/MetaState | 返回 state 含 plan、plan_template_id，由调用方写回 session | ✅ |
| 3. phase = "executing" | plan_once_node 返回 `phase=IP_BUILD_PHASE_EXECUTING` | ✅ |
| 4. current_step_idx = 0 | 返回 `current_step=0`、`step_outputs=[]` | ✅ |

**缺口**：无。

---

## 三、Plan 执行阶段（Execute）

| 规格项 | 实现位置 | 状态 |
|--------|----------|------|
| 1. 读取 current_step_idx → 当前 step | `execute_one_step_node` 中 `plan[current_step]` | ✅ |
| 2. 填充参数 (ip_context + step_outputs) | `_fill_step_params(step_config, ip_context, step_outputs, user_input_data)` | ✅ |
| 3. 参数缺失? → 生成 pending_questions → 暂停执行 | 若 missing 非空则返回 pending_questions，不调用 step_runner | ✅ |
| 3. 否 → 执行对应插件/模块 → 保存 step_outputs | `step_runner(...)` → 结果 append 到 step_outputs | ✅ |
| 4. step 完成 → current_step_idx += 1 | next_idx = current_step + 1，返回 current_step=next_idx | ✅ |
| 5. Plan 完成? → phase = "done" → 汇总输出 | next_idx >= len(plan) 时 phase=done，content=_compile_step_outputs(step_outputs) | ✅ |
| 5. 否 → 循环下一 step | 下一轮请求再次进入 ip_build_router(phase=executing) | ✅ |
| 6. 用户中断 Plan?（继续/放弃/重规划） | 见下 | ✅ 已补 |

**缺口（已补）**：执行阶段检测用户输入「放弃」「重规划」「继续」（`_detect_execute_interrupt`），放弃 → phase=done 并提示；重规划 → 清空 plan、phase=planned；继续 → 正常执行当前步。

---

## 四、最终输出阶段

| 规格项 | 实现位置 | 状态 |
|--------|----------|------|
| 1. 合并所有 step_outputs | `_compile_step_outputs(step_outputs)` | ✅ |
| 2. 生成用户期待的 IP 打造方案/内容方案 | 返回 state.content | ✅ |
| 3. 返回前端/用户 | 调用方从 result 取 content、pending_questions、phase 等返回 API | ✅ |
| 4. 可展示中间步骤/执行说明（可选） | step_outputs 在 state 中，调用方可选返回 | ✅ |

**缺口**：无。

---

## 五、双 Plan 模式

| 规格项 | 实现位置 | 状态 |
|--------|----------|------|
| 固定 Plan：步骤 → 插件/模块 | FIXED_PLAN_TEMPLATES 每步含 step、plugins、params、reason | ✅ |
| 动态 Plan：Intent → steps → plugins | PlanningAgent.plan_steps 输出 steps，每步含 plugins | ✅ |

**缺口**：无。

---

## 六、用户友好引导

| 规格项 | 实现位置 | 状态 |
|--------|----------|------|
| 每轮只问 1～3 个关键问题 | missing[:3]、_build_pending_questions 最多 3 条 | ✅ |
| 选项化 + 可跳过 | Q_MAP 中 options、optional | ✅ |
| 实时回显已收集信息 | ip_context 在 state 中，前端可从 session 取；可选在 API 中带 ip_context_summary | ⚠️ 前端可做 |
| ip_context 持久化，多轮累积 | 约定 session.initial_data 存 phase、ip_context，请求前合并、请求后写回 | ✅ 需调用方配合 |
| 可作为独立 Intake 组件 | intake_node 纯函数式，可单独调用 | ✅ |

**缺口**：main 中需在请求前从 session 合并 IP 字段、请求后写回（见下节）。

---

## 七、Session 持久化（调用方）

| 规格项 | 实现位置 | 状态 |
|--------|----------|------|
| 请求前：从 session 合并 phase、ip_context、plan、current_step、step_outputs 到 state | main.py 构建 initial_state 时合并 initial_data 中 IP 相关字段 | ✅ 已补 |
| 请求后：将 state 中 phase、ip_context、plan、current_step、step_outputs、pending_questions、content 写回 session | main.py frontend/chat 在 result.ip_build_handled 时写回上述字段 | ✅ 已补 |
| 启动 IP 流程：设置 phase=intake、ip_context={} | 需调用方在创建会话或首条请求时设置（如专用 API 或前端「开始IP打造」） | ⚠️ 文档约定 |

---

## 八、流程特点总结对照

| 特点 | 实现情况 |
|------|----------|
| 三态流程：Intake → Planned → Execute → Done | ✅ phase 与节点分工一致 |
| 双 Plan：固定模板 + LLM 动态 | ✅ _choose_plan_template + get_fixed_plan / PlanningAgent |
| 单步执行，缺参就问用户 | ✅ execute_one_step_node + _fill_step_params + pending_questions |
| 中断管理：继续/放弃/重规划 | ✅ 已补：解析用户输入执行相应动作 |
| 用户友好：少量关键问题 + 选项化 + 可跳过 | ✅ _build_pending_questions |

---

## 九、测试

- 见 `tests/test_ip_build_flow.py`：intake 合并与必填检查、固定/动态 Plan、单步执行与缺参追问、中断处理、_compile_step_outputs。
