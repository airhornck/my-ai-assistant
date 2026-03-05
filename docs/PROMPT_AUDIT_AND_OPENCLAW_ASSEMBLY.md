# 系统 Prompt 分布审查与 OpenClaw 式动态拼接评估

本文档审查当前系统中**所有写入/使用 prompt 的位置**，并评估是否有必要引入 **OpenClaw 式的动态拼接 prompt** 能力。

---

## 一、当前系统中 Prompt 的分布与写法

### 1.1 按调用场景分类

| 场景 | 位置 | System 来源 | User 来源 | 动态程度 |
|------|------|-------------|-----------|----------|
| **策略脑规划** | `workflows/meta_workflow.py` planning_node | 超长静态字符串（含「可用模块」枚举、专家原则、输出格式） | f-string：brand/product/topic/intent + 可选 ctx_section / accept_suggestion_section / rewrite_section / ambiguous_feedback_section | User 动态；System 完全静态 |
| **补救步骤** | `workflows/meta_workflow.py` _request_remedial_steps | 无（仅 HumanMessage） | f-string：步骤摘要、失败/空标志、用户问题 | 单条动态 |
| **闲聊回复** | `services/ai_service.py` reply_casual | 无或简短固定 | f-string：history + message；可选 date_time 块 | User 动态 |
| **分析脑** | `domain/content/analyzer.py` | 多处内联 SystemMessage 固定文案 | 多分支 f-string（分析/检索回答/策略方案），按需 += memory/search_results | User 动态、分支多 |
| **生成脑** | `domain/content/generators/text_generator.py` + `config/media_specs.py` | MediaSpec.system_prompt（按平台静态） | build_user_prompt(spec, analysis_text, topic, raw_query) 模板 | 平台选 spec 后固定 system；user 模板插槽 |
| **评估** | `domain/content/evaluator.py` | 静态 system_prompt 常量 | f-string：内容+维度说明 | 常规静态+插槽 |
| **后续建议** | `workflows/follow_up_suggestion.py` | FOLLOWUP_SYSTEM 常量 | f-string：intent、分析、内容摘要等 | 常规静态+插槽 |
| **思维链叙述** | `workflows/thinking_narrative.py` | NARRATIVE_SYSTEM 常量 | f-string：目标、步骤、输出等 | 常规静态+插槽 |
| **意图分类** | `core/intent/processor.py` | INTENT_CLASSIFY_SYSTEM | 单条 user：用户输入 | 静态 + 单变量 |
| **热点刷新** | `services/*_hotspot_refresh.py`（B站/抖音/小红书/AcFun） | 各模块 BILIBILI_HOTSPOT_SYSTEM 等常量 | f-string：来源类型 + 原始内容 | 静态 + 插槽 |
| **记忆压缩** | `services/memory_optimizer.py` | 静态 system_prompt | f-string：近期交互摘要 | 静态+插槽 |
| **补充信息抽取** | `core/reference/supplement_extractor.py` | SUPPLEMENT_SYSTEM | f-string：主推广对象等 | 静态+插槽 |
| **各插件** | `plugins/*.py`（topic_selection, account_diagnosis, business_positioning, content_positioning, script_replication, text_viral_structure, campaign_plan_generator, weekly_decision_snapshot, content_direction_ranking 等） | 多为内联固定或单条 SystemMessage | 各插件内 f-string，注入上下文/诊断结果/样本等 | 每处自建，无统一结构 |

### 1.2 共性结论

- **System 侧**：几乎全是**静态**——要么单一大段（策略脑）、要么常量/MediaSpec，**没有**「按运行时的工具列表/能力列表动态生成 system」的机制。
- **User 侧**：普遍是 **f-string 或模板 + 插槽**（brand、topic、analysis_text、conversation_context、session_suggested_next_plan 等），**已有**按请求/上下文注入的动态内容；**结构**（要不要加某 section）由代码分支决定，不是配置/数据驱动的「多 section 组装」。
- **策略脑的「可用模块」**：当前是**写死在 system_prompt 里**的一段枚举（web_search、memory_query、kb_retrieve、bilibili_hotspot、analyze、generate、evaluate、casual_reply、自定义插件）。新增步骤（如 xiaohongshu_hotspot、douyin_hotspot）需要**改 meta_workflow.py 里这段长字符串**，没有从「插件/步骤注册表」自动生成描述。

---

## 二、OpenClaw 式「动态拼接」指什么

（基于公开资料与常见 Agent 实践归纳。）

- **System 按「区块」组装**：同一 agent 的 system 不是单一大段，而是由多块组成，例如：
  - 身份/原则
  - **当前工具列表 + 每个工具的描述**（随注册表变化）
  - 当前时间/运行环境
  - 工作区/项目上下文（如注入 SOUL.md、TOOLS.md 等）
  - 沙箱/权限说明
- **按模式裁剪**：例如 full / minimal / none，决定包含哪些区块，适合主 agent vs 子 agent。
- **工具描述随注册表变化**：新加工具只需在注册表里加 name + description，**无需改 prompt 文案**，运行时把当前工具表拼进 system。

对应到本系统：若做「类 OpenClaw」的动态，最相关的是——**策略脑的 system 中「可用模块」这一块，是否由「步骤/插件注册表」动态生成**，而不是手写长字符串。

---

## 三、是否需要引入 OpenClaw 式动态拼接

### 3.1 不必全盘照搬

- 当前架构是**策略脑一次规划 + 编排按 plan 执行**，不是「每步都让模型选工具」的 Agent loop，因此**不需要**像 OpenClaw 那样为「每轮选工具」动态拼一整套 tool 描述。
- 现有 user 侧已经按请求/上下文注入内容，**动态性主要在 user 消息**，这点已够用；问题集中在**策略脑的 system 是否要动态**。

### 3.2 值得考虑的一点：策略脑「可用模块」动态化

- **现状**：新增一步能力（新检索、新平台热点等）就要改 `meta_workflow.py` 里的大段「可用模块」枚举，容易漏改、难维护。
- **若引入「轻量动态拼接」**：  
  - 维护一个**步骤能力注册表**（step name → 简短描述，供规划用），与现有编排的 step 名、插件注册表对齐。  
  - 策略脑 system 不再手写「可用模块」长列表，改为：固定前缀（身份、专家原则、输出格式等） + **一段由注册表生成的「可用模块」列表**。  
  - 这样**新增/下线步骤只需改注册表**，不用改 prompt 正文，可视为「OpenClaw 式动态拼接」在本项目中的最小落地。

### 3.3 建议结论

| 问题 | 结论 |
|------|------|
| 是否必须引入 OpenClaw 那种「多区块、多模式、bootstrap 文件注入」的完整能力？ | **不必**。与当前「一次规划 + 固定执行」的形态不匹配，收益有限。 |
| 是否值得做「策略脑可用模块」的轻量动态拼接？ | **值得**。新增步骤时只需维护注册表与简短描述，避免反复改长 prompt，且与现有插件/步骤扩展方式一致。 |
| 其他调用点（分析脑、生成脑、评估、意图、插件内）是否要改成「动态拼接」？ | **不必**。当前静态 system + 动态 user 已满足需求；若未来有「按任务类型/角色切换 system 区块」的需求，再考虑按场景加小块组装即可。 |

---

## 四、若做「策略脑可用模块」动态拼接：实现要点

- **数据源**：新增或复用一张「步骤 → 规划用描述」表（可与 `task_plugin_registry` 或编排侧 step 名对齐），例如：
  - `web_search` → "网络检索（竞品、热点、行业动态、通用信息）"
  - `bilibili_hotspot` → "B站热点榜单（…）"
  - 新增 `xiaohongshu_hotspot` 时只在此表加一行，不改 meta_workflow 正文。
- **组装**：在 `planning_node` 内，构造 system 时：
  - 保留现有「专家原则」「输出格式」等固定段落；
  - 将「可用模块」段落改为：`"\n".join(f"- {name}: {desc}" for name, desc in get_step_descriptions_for_planning())` 或等价逻辑。
- **兼容**：若某步骤暂无描述，可回退为仅输出 step 名，或从现有长字符串里拆出默认描述做 fallback，保证旧行为可复现。

这样即可在**保留现有插件模式与编排逻辑**的前提下，只引入「策略脑 system 中能力列表」的轻量动态拼接，而不上整套 OpenClaw 式架构。

---

## 五、已实现的轻量动态拼接（步骤描述表）

- **模块**：`core/step_descriptions_for_planning.py`
  - `STEP_DESCRIPTIONS`：步骤名（小写）→ 规划用描述；已包含 web_search、memory_query、kb_retrieve、bilibili_hotspot、xiaohongshu_hotspot、douyin_hotspot、acfun_hotspot、analyze、generate、evaluate、casual_reply。
  - `get_step_descriptions_for_planning()`：返回 (name, desc) 有序列表。
  - `build_available_modules_section()`：返回整段「可用模块」文案（含标题与「自定义插件」说明），供 planning 拼入 system。
- **使用处**：`workflows/meta_workflow.py` 的 `planning_node` 中，在构造 system_prompt 时调用 `build_available_modules_section()` 动态插入可用模块段落，专家原则与输出格式等仍为固定文案。
- **扩展**：新增步骤时在 `STEP_DESCRIPTIONS` 中加一行并在 `get_step_descriptions_for_planning` 的 `order` 中加入顺序即可；若编排侧已支持该 step（如加入 PARALLEL_STEPS 或 router），无需再改 meta_workflow 的 prompt 正文。
