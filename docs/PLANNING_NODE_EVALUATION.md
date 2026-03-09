# planning_node 修改前后对比评估

## 结论：**各有优劣；整体上「新版本」更易维护，「旧版本」功能更全**

- **若优先考虑**：逻辑简单、少分支、易读易改、与 InputProcessor 职责清晰 → **新版本更好**。
- **若优先考虑**：少调 LLM、改写/插件推断/模糊反馈等行为与旧版完全一致 → **旧版本部分能力更强**，可择要迁回或在下游补足。

---

## 一、结构对比摘要

| 维度 | 修改前（旧版） | 修改后（新版） |
|------|----------------|----------------|
| **篇幅** | 约 250+ 行（含长 system_prompt + 多短路） | 约 115 行 |
| **短路逻辑** | ① 极短闲聊（SHORT_CASUAL_REPLIES + len≤8）直接 casual_reply，不调 LLM<br>② `has_ambiguous_feedback_after_creation` 直接 casual_reply，不调 LLM | 无；依赖上游 InputProcessor 已识别的 intent / 上下文 |
| **explicit_content_request** | 仅来自 `data`（InputProcessor 结果）+ 采纳建议且建议含 generate | 同上 + **本节点内规则**：`generation_keywords` 命中即视为明确生成 |
| **系统提示词** | 很长：14 条专家原则、task_type 三选一、改写/B站/热点等示例、改写请求/采纳建议/模糊评价等专门说明 | 短：6 条原则 + 统一 JSON 格式，无示例、无改写/采纳/模糊评价细则 |
| **用户 prompt** | 多块条件拼接：ctx_section、accept_suggestion_section、rewrite_section、ambiguous_feedback_section、explicit_hint | 固定模板：品牌/产品/话题/意图/是否明确生成 + 上下文截断 600 字 |
| **安全过滤** | 有：`not explicit_content_request` 时移除 plan 中的 generate | 有：逻辑相同 |
| **改写请求** | **代码注入**：若 `rewrite_previous_for_platform`，遍历 plan 给 generate 步注入 `output_type=rewrite`、`platform` | 仅在 system/user prompt 中说明「可根据 rewrite_previous_for_platform 注入」，**无代码注入** |
| **analysis_plugins / generation_plugins** | 从 LLM 解析 + **get_plugins_for_task(task_type, step_names)** 推断，合并后写入 state | 固定返回 **[]**，不解析、不推断 |
| **空 plan 兜底** | 有：若 `not plan` 再按 explicit 给 2 步兜底 | 无：仅异常时兜底，正常解析若得到空 list 就空 |
| **日志** | 短路、移除 generate、改写注入、完成时 steps 数等均有 logger | 仅 thought 写入 thinking_logs，无单独 logger |

---

## 二、新版更好的点

1. **代码更短、更易读**  
   单函数 110 行左右，无大段条件拼接，维护和排查成本低。

2. **explicit 规则在策略脑内有一层保障**  
   `generation_keywords`（如「生成」「写」「帮我写」等）在本节点内即可把「明确要求生成」设为 True，不完全依赖 InputProcessor 的 `explicit_content_request`，减少漏判。

3. **与 InputProcessor 职责更清晰**  
   极短闲聊、模糊评价等由 InputProcessor 做意图与反馈分类；planning_node 只做「在已有 user_input 上的步骤规划」，不再重复短路，避免两处改逻辑。

4. **安全过滤保留**  
   「未明确要求生成则移除 generate」在新版中仍然存在，行为与旧版一致，避免误生成。

5. **提示词精简**  
   专家原则收敛为几条，模型更容易遵守格式与「仅明确要生成时才 generate」，有利于稳定输出 JSON 和减少多余步骤。

---

## 三、旧版更强或独有的点

1. **少调 LLM 的短路**  
   - 极短闲聊（如「还好」「嗯」）：旧版直接返回 1 步 casual_reply，不调 LLM。  
   - 模糊评价（如「还行吧」且 `has_ambiguous_feedback_after_creation`）：旧版直接返回 casual_reply 引导句，不调 LLM。  
   新版这两类都会进入 LLM 规划，延迟与成本略高（若上游已把 intent 设为 casual_chat，后续仍会走 casual_reply，但 planning 已调 LLM）。

2. **改写请求的可靠注入**  
   旧版在解析出 plan 后，若 `rewrite_previous_for_platform`，**在代码里**给 generate 步写入 `output_type=rewrite`、`platform`。新版只靠提示词让 LLM 写 params，容易漏写或写错，改写链路的确定性不如旧版。

3. **analysis_plugins / generation_plugins 的推断**  
   旧版用 `get_plugins_for_task(task_type, step_names)` 推断插件，并和 LLM 返回的 analysis_plugins 合并，写入 state，供后续编排使用。新版固定返回空列表，若下游没有别处补全，分析脑/生成脑可用的插件会变少。

4. **空 plan 兜底**  
   旧版在解析成功但 `plan == []` 时，会按是否 explicit 再给 2 步兜底。新版只在异常时兜底，正常解析出空 list 就保持空，可能造成后续编排无步可执行。

5. **复杂场景的提示词**  
   旧版长提示词里对「改写」「采纳建议」「模糊评价」「B站/热点」等有专门说明，对复杂多轮、多意图的规划可能更稳；新版依赖短提示 + 上游信息，在极端组合下可能不如旧版稳。

---

## 四、建议

- **保留当前「新」planning_node 作为主实现**：更简单、explicit 有规则兜底、职责清晰，且安全过滤仍在，适合作为默认版本。
- **按需从旧版迁回或在下游补足**（在确认主流程依赖再动手）：
  1. **改写请求**：若主流程仍依赖「改写为某平台」的稳定行为，建议在 **编排层**（或 planning 解析后）根据 `user_input` 里的 `rewrite_previous_for_platform` / `rewrite_platform` 对 plan 中 generate 步做 params 注入，与旧版行为对齐。
  2. **analysis_plugins / generation_plugins**：若后续节点依赖 state 里这两项，可在 **编排层** 根据当前 `task_type` 与 `plan` 的 step 列表调用 `get_plugins_for_task`，写回 state，避免插件能力缺失。
  3. **极短闲聊 / 模糊评价**：若希望继续「不调 LLM」的短路，可在 **进入 planning 前**（例如在 main 或路由里）根据 intent + `has_ambiguous_feedback_after_creation` 直接构造 1 步 casual_reply 的 plan 并跳过 planning_node，效果与旧版短路一致。
  4. **空 plan**：在 planning_node 末尾若 `not plan`，可像旧版一样按 explicit 补 2 步兜底，避免空链。

---

## 五、总结表

| 评价维度       | 更优一方 |
|----------------|----------|
| 可读性 / 维护性 | **新版** |
| 与 InputProcessor 职责划分 | **新版** |
| explicit 规则兜底（本节点内） | **新版** |
| 少调 LLM（短路） | **旧版** |
| 改写请求 params 注入可靠性 | **旧版** |
| 插件推断（analysis/generation_plugins） | **旧版** |
| 空 plan 兜底 | **旧版** |
| 复杂场景提示词细节 | **旧版** |
| 「未明确要生成则去掉 generate」 | **相同** |

**综合**：新版在整体架构和日常维护上更优；若你需要与旧版完全一致的行为（少调 LLM、改写注入、插件推断、空 plan 兜底），可在保留新 planning_node 的前提下，按上面四点在下游或前置做小范围补齐，而不是整体回退到旧版长实现。
