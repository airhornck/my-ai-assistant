# 闲聊 ↔ 创作意图切换：上下文审查与「统一走策略脑」设计建议

## 一、当前上下文是否在意图切换时被正确记录？

### 1.1 数据流概览

| 数据 | 来源 | 闲聊路径是否写入 | 创作路径是否写入 | 切换后是否可用 |
|------|------|------------------|------------------|----------------|
| **request.history** | 前端每轮提交的最近 N 条对话 | 不写（前端维护） | 不写 | ✅ 两种路径都能读到同一份 history |
| **conversation_context / history_text** | 由 request.history 拼成（最近 10 条） | 只读，传给 reply_casual | 只读，传给意图识别 + user_input_payload | ✅ 创作/闲聊都能看到完整近期对话 |
| **Session (initial_data)** | session_id 对应服务端会话 | ❌ 不写 | ✅ 写（content、analysis、suggested_next_plan、session_intent 等） | ✅ 创作→闲聊→创作：session 仍是上一轮创作状态，可延续 |
| **InteractionHistory** | 每轮请求后写入 DB | ✅ 写（user_input + ai_output） | ✅ 写（创作完成后写） | ✅ 所有轮次都有记录，可用于反馈/统计 |

### 1.2 结论：**可以记录上下文**

- **创作 → 闲聊**：session 保留上一轮创作的 brand/product/content/suggested_next_plan；下一轮请求的 history 里会带上「用户/助手」的闲聊轮次；再切回创作时，conversation_context 含全程对话，session 仍含上次创作状态，策略脑可延续。
- **闲聊 → 创作**：conversation_context 含之前闲聊+更早的创作内容；若之前有过创作，session 里仍有 session_intent（brand/product/topic），可与 conversation_context 一起供策略脑使用。
- **唯一注意点**：闲聊路径**不**更新 session_intent（不调用 _update_session_intent）。若用户先多轮纯闲聊、再首次说「生成文案」且未再提品牌，则依赖 conversation_context 和 session 里**上一次创作**的残留；通常仍有足够信息，可视为可接受。

---

## 二、是否应取消独立「闲聊意图」，统一走策略脑？

### 2.1 当前设计（网关层意图分流）

```
请求 → 意图识别(LLM/规则) → casual_chat → reply_casual → 存 InteractionHistory，不写 session
                         → free_discussion/creation → 策略脑 → 编排执行 → 写 session + InteractionHistory
```

- **优点**：纯闲聊成本低（1 次 LLM：reply_casual），时延小。
- **缺点**：意图分类与策略脑「两套判断」，易出现误判（如「还好」被判成 free_discussion）；闲聊与创作两条分支，上下文与逻辑要分别维护。

### 2.2 参考：豆包 / ChatGPT / DeepSeek 的共性

- **单线程、单入口**：不先在网关区分「闲聊」和「任务」，而是**一条对话流**。
- **由模型或内部规划决定行为**：根据当前句 + 上下文决定是「随便聊聊」还是「执行任务」；必要时再调用插件/检索/生成。
- **等价到本系统**：可以理解为「所有请求都先进入策略脑，由专家原则判断是闲聊还是创作；若判断为闲聊，则规划为一步 [闲聊回复] 并走闲聊能力」。

### 2.3 统一走策略脑的两种做法

**方案 A：全部进策略脑，策略脑输出「闲聊」则只执行一步**

- 流程：**所有请求** → 策略脑（带 conversation_context）→ 若专家判断为「用户当前在闲聊」→ 规划为 `steps: [{ step: "casual_reply", ... }]` → 编排层只执行这一步（调用现有 reply_casual 或闲聊插件）→ 汇总/报告可极简（如只返回回复文案，无「深度思考报告」）。
- **优点**：意图只由策略脑一家判断，与「专家原则」一致；不再有「还好」被误判为创作；上下文统一在一套 state + history 里。
- **缺点**：纯闲聊也从 1 次 LLM 变为「1 次规划 + 1 次闲聊」= 2 次调用，时延与成本略增。

**方案 B：保留网关意图，但仅作「快捷分支」；策略脑仍为权威**

- 网关层：仅对**极短、明确闲聊**（如 SHORT_CASUAL_REPLIES）做**规则级**快捷分支 → 直接 reply_casual，不调策略脑。
- 其余全部进策略脑；策略脑里也可定义「若判断为闲聊则 plan = [casual_reply]」。
- **优点**：大部分闲聊仍可 1 次调用；创作与「模糊句」统一走策略脑，误判少。
- **缺点**：仍存在两处判断（规则 + 策略脑），逻辑略复杂。

### 2.4 建议

- **若优先「体验一致、少误判、和豆包/ChatGPT/DeepSeek 类似」**：采用**方案 A（统一走策略脑）**，接受闲聊多一次规划调用。
- **若优先「纯闲聊时延与成本」**：采用**方案 B**，保留对「还好」「嗯」等的规则级快捷分支，其余统一策略脑。

---

## 三、若采用「统一走策略脑」（方案 A）需要做的改动

1. **main.py**
   - 去掉 `if intent == INTENT_CASUAL_CHAT: ... return` 的**提前 return**；不再在网关根据 intent 分流到 reply_casual。
   - 所有非 command 的请求（包括当前会判成 casual_chat 的）都组好 `user_input_payload`、`initial_state`，走同一套 meta_workflow；`conversation_context` 继续带入。

2. **策略脑（meta_workflow planning_node）**
   - 在「专家原则」与 system/user prompt 中明确：若用户当前输入为**闲聊**（问候、寒暄、无明确推广/生成需求），则规划为 **仅一步**，例如 `steps: [{ step: "casual_reply", reason: "用户处于闲聊，直接回复" }]`，且不再规划 web_search / analyze / generate 等。
   - 可约定：当规划结果仅为 `casual_reply` 时，task_type 可为 `casual_chat` 或沿用现有某一类。

3. **编排层（orchestration_node / router）**
   - 增加对步骤类型 **casual_reply** 的处理：调用现有 `ai.reply_casual(message, history_text)` 或统一的「闲聊插件」，将结果写入 state（如 `content` 或专用字段），以便后续汇总。

4. **汇总 / 返回**
   - 若本轮规划仅为 `casual_reply`：可走极简汇总（不生成「深度思考报告」），直接返回闲聊回复 + 简单 thinking_process（如「策略脑：判定为闲聊，已直接回复」）；或与前端约定 mode=casual 时只展示回复内容。

5. **会话与历史**
   - 创作路径已有的 session 更新、InteractionHistory 写入逻辑可复用；**闲聊轮次**也走同一套 state 更新与历史写入，这样「闲聊 ↔ 创作」的上下文完全由一套流程记录，无需再分叉维护。

6. **意图处理器（可选）**
   - 若完全统一走策略脑，可考虑**弱化或移除**网关层对 casual_chat 的区分，仅保留 command 等必须前置的分支；或保留为「仅用于统计/打标」，不再用于路由。

---

## 四、总结

| 问题 | 结论 |
|------|------|
| 闲聊 ↔ 创作来回切换时，是否能记录上下文？ | **能**。history + conversation_context + session 组合足以在切换时保留上下文；仅闲聊路径不更新 session_intent，一般可接受。 |
| 是否应该取消独立闲聊意图，统一走策略脑？ | **建议上可以**。与豆包/ChatGPT/DeepSeek 的「单入口、由模型/规划决定行为」一致，且能消除「还好」类误判；代价是纯闲聊多一次规划调用。若希望兼顾成本，可保留对极短句的规则级闲聊分支（方案 B）。 |

以上可作为是否落地「统一走策略脑」的审查与设计依据；若你选定方案 A 或 B，再按上列改动清单逐项实现即可。
