# 意图、会话状态与记忆系统设计

## 一、问题与目标

1. **僵化澄清**：推广需求一律弹出固定「发布平台、篇幅要求」问答，交互僵硬；且营销IP搭建、策略建议等不必导向生成文案。
2. **策略脑过度执行**：不一定要跑完分析脑→生成脑→评估脑，应根据用户真实意图按需规划。
3. **生成形态多样**：生成脑不限于文案，可为图片、脚本等，需根据用户需求调用。
4. **文档/链接丢失上文**：添加文档或链接后，主推广对象（品牌、产品、话题）丢失。
5. **记忆与会话关系**：短期会话状态与长期记忆的边界、冲突与协作。

---

## 二、会话意图状态（短期记忆）

### 2.1 存储位置与结构

在 Redis 会话 `initial_data` 中维护 `session_intent`：

```python
session_intent = {
    "intent": str,           # 当前意图
    "brand_name": str,
    "product_desc": str,
    "topic": str,
    "raw_query": str,
    "output_type_hint": str, # 可选：copy|image|script|strategy|analysis
    "updated_at": str,       # ISO 时间
}
```

### 2.2 合并规则

- **每轮对话**：若意图识别得到非空的 `brand_name/product_desc/topic`，更新 `session_intent`。
- **用户仅添加文档/链接**：当轮 `structured_data` 可能为空，此时**以会话中已存的 `session_intent` 为主**，与当轮输入合并，延续上下文。
- **新建会话**：`session_intent` 为空，首轮从意图识别结果填充。

### 2.3 与记忆系统关系

| 层级 | 存储 | 用途 | 更新时机 |
|------|------|------|----------|
| **会话意图** | Redis session.initial_data | 当前对话链的主推广对象、意图 | 每轮有结构化信息时更新 |
| **短期记忆** | Redis thread/session | 同一 thread 内的多轮会话 | 会话创建/更新时 |
| **长期记忆** | PostgreSQL UserProfile, InteractionHistory | 跨会话画像、习惯、历史 | 交互结束或定期沉淀 |

**无冲突**：会话意图是「当前对话状态」，长期记忆是「跨会话学习」。会话意图在文档/链接轮次可防止主推广对象丢失；长期记忆用于后续会话的个性化。

---

## 三、灵活澄清逻辑

### 3.1 原则

- **缺基础信息时**：品牌、产品、话题任一缺失且意图涉及营销，优先引导补充基础信息。
- **缺平台/篇幅时**：仅当用户明确要「生成文案/宣传稿」等，再询问平台、篇幅；否则不强制。
- **非生成类意图**：如策略建议、IP 搭建、竞品分析等，不触发「平台/篇幅」澄清，按需输出建议或分析。

### 3.2 澄清触发条件（重写 needs_clarification）

- 意图为 `structured_request` / `free_discussion` / `document_query`（文档作补充）
- 且满足其一：
  - **缺基础信息**：brand_name、product_desc、topic 均空或过短 → 引导补充「品牌/产品/主题」
  - **明确要生成内容**：raw_query 含「生成、写、出、文案、文稿」等，且缺平台或篇幅 → 引导补充平台/篇幅

### 3.3 澄清文案（动态 get_clarification_response）

根据「缺什么」生成不同引导：

- 缺基础信息 → 「请补充：品牌/产品/推广主题」
- 缺平台 → 「打算在哪个平台发布？B站、小红书…」
- 缺篇幅 → 「需要完整文稿还是简短简介？」

---

## 四、策略脑意图驱动规划

### 4.1 规划原则

- **按需规划**：根据用户真实意图决定步骤，不强制 analyze→generate→evaluate 全跑。
- **可用步骤**：web_search、memory_query、analyze、generate、evaluate。
- **generate 参数**：支持 `output_type`（copy/image/script 等），按需求调用。

### 4.2 规划示例

| 用户意图 | 建议步骤 |
|----------|----------|
| 推广产品，要文案 | web_search? → analyze → generate(copy) → evaluate |
| 营销 IP 搭建思路 | analyze → 策略建议（或仅 analyze，输出即建议） |
| 竞品分析 | web_search → analyze |
| 只要热点关联 | web_search → analyze |

### 4.3 实现方式

- 规划 prompt 中明确：根据用户意图规划，不必全流程；若仅要策略、分析、建议，可不调用 generate。
- 将 `intent`、`output_type_hint` 传入规划，供策略脑参考。

---

## 五、长期记忆优化（建议）

- **UserProfile**：brand_name、industry、preferred_style、brand_facts、success_cases。
- **习惯沉淀**：从 InteractionHistory 提炼「常要小红书」「常要完整文稿」等，写入 UserProfile 或独立习惯表。
- **实现时机**：作为后续迭代，不影响本次会话意图与澄清改造。

---

## 六、与现有记忆系统的关系

| 类型 | 存储 | 更新时机 | 用途 |
|------|------|----------|------|
| **会话意图 (session_intent)** | Redis session.initial_data | 每轮有结构化信息时 | 延续主推广对象，防止文档/链接轮次丢失 |
| **短期记忆** | Redis thread/session | 会话创建、更新 | 同一对话链内的多轮会话 |
| **长期记忆** | PostgreSQL UserProfile, InteractionHistory | 交互结束、定期沉淀 | 跨会话画像、习惯 |

**无冲突**：会话意图是「当前对话状态」，长期记忆是「跨会话学习」。会话过程中可更新 session_intent（短期），长期记忆在交互结束或批处理时沉淀。
