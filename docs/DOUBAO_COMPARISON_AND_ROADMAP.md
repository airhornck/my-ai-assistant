# 对话逻辑、处理流程与豆包对比分析

## 一、当前对话逻辑与处理流程

### 1.1 入口与分流

```
frontend_chat (POST /api/v1/frontend/chat)
    │
    ├─ 会话管理：校验/创建 session_id，加载 session_intent
    ├─ 文档/链接：加载 session_doc_context，抓取 message 中链接
    ├─ 历史：从 request.history 构建 conversation_context
    │
    └─ mode 分流
        ├─ chat：意图识别 → 闲聊/澄清/直接生成
        └─ deep：意图识别 → 澄清/MetaWorkflow（策略脑→编排→汇总）
```

### 1.2 Chat 模式流程

```
InputProcessor.process(raw_input, conversation_context)
    → intent（casual_chat | structured_request | free_discussion | document_query）
    → structured_data (brand, product, topic)
    → 合并 session_intent
    ↓
casual_chat → reply_casual（无记忆、无生成）
needs_clarification → 动态澄清文案
否则 → extract_reference_supplement + 单轮 LLM 生成
```

**局限**：Chat 模式不调用 memory_query、不加载用户画像/标签，上下文仅来自 history 文本。

### 1.3 Deep 模式流程

```
InputProcessor → 合并 session_intent → 澄清检查
    ↓
user_input_payload (brand, product, topic, intent, session_document_context, conversation_context)
    ↓
MetaWorkflow:
  planning_node     → 策略脑规划 (web_search | memory_query | analyze | generate | evaluate)
  orchestration_node → 按规划执行
  compilation_node  → 汇总报告（含 DeepSeek 风格思考叙述）
```

**编排步骤**：
- `web_search`：百度搜索
- `memory_query`：MemoryService.get_memory_for_analyze（品牌事实、成功案例、画像、近期交互）
- `analyze`：分析脑，关联热点
- `generate`：生成脑，文案
- `evaluate`：评估脑

### 1.4 会话意图与记忆

| 层级 | 存储 | 更新 |
|------|------|------|
| session_intent | Redis initial_data | 每轮有结构化信息时 |
| UserProfile (tags, brand_facts, success_cases) | PostgreSQL | 显式写入 / memory_optimizer 每 6h |
| InteractionHistory | PostgreSQL | 每轮 deep 成功时 |

---

## 二、产品完整形态设想（含热点/竞品/行业知识库）

### 2.1 拟扩展插件

| 插件 | 能力 | 触发方式 |
|------|------|----------|
| **热点榜单** | 拉取微博/抖音/小红书热搜，供切入点分析 | planning 规划 web_search 或独立热点模块 |
| **竞品分析** | 检索竞品信息、价位、卖点 | web_search 或专用竞品数据源 |
| **行业知识库** | RAG 检索行业术语、案例、规范 | document_query 或 analyze 前检索 |
| **营销 IP 模板库** | 人设、话术、脚本模板 | generate 时按平台/场景选用 |

### 2.2 架构扩展点

- **PluginBus**：已有 `document_query`、`document_uploaded`，可增 `hotspot_query`、`competitor_query`、`industry_kb_query`
- **策略脑**：规划步骤可含 `hotspot_search`、`competitor_analyze`、`kb_retrieve`
- **编排层**：新增步骤类型，调用对应插件/服务

---

## 三、与豆包对比（营销 IP 搭建与内容创作垂直赛道）

### 3.1 豆包能力（公开信息）

- **多轮对话**：追问-修正-迭代
- **营销文案**：短视频脚本、带货脚本、多模态
- **语音**：移动端语音交互
- **内容生态**：依托字节内容数据
- **提示词**：5W1H 等结构化提示

### 3.2 能力对比矩阵

| 维度 | 本应用（含完整形态设想） | 豆包 | 结论 |
|------|--------------------------|------|------|
| **用户体验** | 双模式（chat/deep）、Gradio 前端 | 产品成熟、多端、语音 | 豆包更成熟 |
| **意图识别** | 5 类意图 + 结构化提取 | 通用对话，无显式意图 | **本应用更精准** |
| **上下文能力** | history(10 条) + session_intent + conversation_context | 长上下文 | 豆包更泛化 |
| **文档/链接后意图延续** | session_intent 合并、参考材料补充 | 支持上传，延续性一般 | **本应用更可控** |
| **短期记忆** | session_intent（Redis） | 会话内隐式 | **本应用更显式** |
| **长期记忆** | UserProfile + InteractionHistory + memory_optimizer | 可能有用户画像 | **本应用可定制** |
| **用户标签** | 6h 批量更新，显式标签防覆盖 | 隐式 | **本应用可解释** |
| **垂直深度** | 分析→生成→评估闭环、策略脑规划 | 通用创作 | **本应用更垂直** |
| **可扩展性** | 插件总线、策略脑按需规划 | 闭源 | **本应用更灵活** |
| **联网/实时** | web_search（百度） | 有 | 相当 |
| **热点/竞品/知识库** | 可扩展插件 | 无公开 | **本应用可独占** |

### 3.3 优势与劣势总结

**本应用优势**：
1. 意图与主推广对象显式建模，文档/链接作为补充不喧宾夺主
2. 策略脑按需规划，不强制全流程
3. 分析→生成→评估闭环，带质量反馈
4. 插件化扩展，可做热点、竞品、行业知识库
5. 用户标签与长期记忆可解释、可运维

**本应用劣势**：
1. 前端体验不及豆包成熟
2. Chat 模式不用记忆，上下文弱
3. 标签更新 6h 延迟，非实时
4. 无语音、多模态等
5. 热点/竞品/知识库尚为设想，未实现

---

## 四、改进建议（按优先级）

### P0：核心体验 ✅ 已实现

| 项 | 问题 | 实现 |
|---|------|------|
| Chat 模式不用记忆 | 快速回复无用户画像、标签 | ✅ 在 chat 生成前调用 `get_memory_for_analyze`，将 preference_context 注入 prompt |
| 前端发送 tags / 后端沉淀 | 前端未传 tags，长期画像难沉淀 | ✅ 后端在 deep 成功后异步提炼标签并回写 profile |
| session_intent 在新会话为空 | 新建会话无历史 | ✅ 新建会话时从 UserProfile 预填 brand_name、industry 到 session_intent |

### P1：记忆与标签 ✅ 已实现

| 项 | 问题 | 实现 |
|---|------|------|
| 标签更新延迟 | 6h 才更新，新用户无标签 | ✅ deep 成功后异步触发 `_derive_and_update_tags_background` 提炼并更新 tags |
| 标签应用可见性 | 用户不知道系统用了什么标签 | ✅ 思维链叙述中传入 effective_tags，提示 LLM 体现「根据您的偏好（xxx）」 |
| 近期交互利用 | 仅取 3 条，且 topic 从 JSON 解析 | ✅ 扩至 5 条，提取 brand/product/topic/raw，header 强调「重要：用于延续用户偏好与主题」 |

### P2：垂直能力

| 项 | 问题 | 建议 |
|---|------|------|
| 热点榜单 | 未实现 | 新增热点插件，策略脑可规划 hotspot_search |
| 竞品分析 | 仅靠 web_search | 建竞品数据源或专用检索，策略脑规划 competitor_analyze |
| 行业知识库 | 未实现 | RAG 知识库，analyze 前可选 kb_retrieve |
| 营销 IP 模板 | 仅媒体规范 | 增加人设/话术模板库，generate 时按场景选用 |

### P3：体验与差异化

| 项 | 问题 | 建议 |
|---|------|------|
| 前端 | Gradio 基础 | 增强 UI、快捷指令、模板选择 |
| 语音 | 无 | 后续可接 ASR/TTS |
| 结构化输出 | 主要 Markdown | 支持 JSON、表格等，便于二次加工 |

---

## 五、当前逻辑与流程检查结论

### 5.1 已实现且有效

- 意图识别 + 会话意图合并，解决文档/链接轮次丢失
- 策略脑按需规划，不强制全流程
- 澄清逻辑按「缺基础信息 vs 缺平台/篇幅」分情况处理
- 短期 session_intent、长期 UserProfile/InteractionHistory 分层清晰

### 5.2 需补齐

1. **Chat 模式接入记忆**：在生成前注入用户画像与偏好
2. **标签实时/准实时更新**：deep 成功后的轻量分析或缩短周期
3. **热点/竞品/知识库插件**：落地垂直数据源与策略脑步骤
4. **标签对用户可见**：在思考过程或回复中体现「基于您的偏好」

### 5.3 与豆包的差异化定位

在「营销 IP 搭建与内容创作」赛道上，通过 **显式意图与主推广对象、闭环分析-生成-评估、可扩展插件（热点/竞品/知识库）** 形成垂直优势；豆包强在通用体验与生态。建议优先补齐 P0、P1，再逐步实现热点/竞品/知识库等 P2 能力。
