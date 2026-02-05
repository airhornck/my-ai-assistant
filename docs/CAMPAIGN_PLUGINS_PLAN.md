# 活动策划（方法论 + 知识库 + 案例）—— 分析脑/生成脑插件规划（修订版）

## 一、设计原则（回应你的四点）

1. **能力全部收口到脑内、插件式实现**  
   方法论、知识库、案例的「拉取与产出」都作为**分析脑插件**实现，编排层**不再**单独做 kb_retrieve / methodology_retrieve / case_retrieve 等步骤；编排层只保留通用步骤（如 web_search、memory_query、**analyze**、generate、evaluate），由**规划脑**决定本轮要跑哪些分析脑插件，分析脑内部按插件列表执行并合并结果。

2. **案例、方法论可单独取用与查看**  
   案例、方法论的后端（CaseTemplateService、MethodologyService）与现有 **REST API**（如 GET /api/v1/methodology、GET /api/v1/cases）保持不变，供「单独查看、单独取用」。分析脑里的**方法论插件、案例库插件**与这些 API **共用同一数据源**；插件只是「脑内使用」的入口，且**每次使用都优先读缓存/结果报告**，不替代也不阻塞「直接查 API」的能力。

3. **编排层不增加任务分支，避免性能与复杂度**  
   编排层**不**根据 task_type 或任务类型做分支，不增加额外步骤；只按规划脑给出的 **plan（步骤列表）** 和 **analysis_plugins / generation_plugins** 执行。任务语义完全由**规划脑**和**脑内插件**承担，编排层保持「按步骤调用、按列表调插件」的单一逻辑。

4. **插件每次使用都直接用缓存或结果报告，性能影响最小**  
   所有相关插件都遵循「**get_output() 只读缓存或预生成报告**」：  
   - **定时插件**（如方法论、案例库）：定时刷新把数据写入缓存/报告，get_output() 只返回缓存内容，不在此刻访问 DB 或检索。  
   - **实时但带缓存的插件**（如知识库）：get_output() 先查缓存（如按 query 的 key），命中则直接返回；未命中再检索并回写缓存。  
   这样每次调用对性能影响最小，且与 B站热点插件的模式一致。

---

## 二、整体数据流（修订后）

- **编排层**：只执行 plan 中的步骤；其中 **analyze** 步骤调用 `ai_svc.analyze(request, preference_context, analysis_plugins=[...])`，**generate** 步骤调用 `ai_svc.generate(..., generation_plugins=[...])`。不注入 CaseTemplateService/MethodologyService，也不做 kb_retrieve 等编排级检索。
- **规划脑**：根据意图输出 plan 与 **analysis_plugins**、**generation_plugins**。**插件列表只登记拼装后或无需拼装的插件**；例如活动策划意图下，analysis_plugins = [**campaign_context**]（拼装插件，由插件中心内聚 methodology+case_library+knowledge_base），generation_plugins = [campaign_plan_generator] 或 [text_generator]。
- **分析脑**：拼装逻辑在**插件中心**内完成。**campaign_context** 插件在 get_output 时调用同脑内 methodology、case_library、knowledge_base 的 get_output，再拼成 campaign_context；规划脑只登记 **campaign_context**，不登记子插件。其他插件（methodology、case_library、knowledge_base）仍注册在插件中心供 campaign_context 调用及定时刷新。
- **生成脑**：**文本/图片/视频/PPT 等能力均以插件方式登记**；ContentGenerator 仅通过 plugin_center 按 generation_plugins（或按 output_type 的默认插件列表）调用插件。模型配置由**各脑的插件中心 config** 管理（如 config["models"]["text_generator"]），插件从 config 读模型。

**单独查看**：用户/前端需要「只看方法论」或「只看案例」时，继续走现有 **GET /api/v1/methodology**、**GET /api/v1/cases** 等 API，与插件共用同一后端服务，互不影响。

---

## 三、分析脑插件（全部能力在脑内、每次用缓存/报告）

### 3.1 方法论插件（methodology）

| 项目 | 说明 |
|------|------|
| **插件名** | `methodology` |
| **类型** | **定时插件** (scheduled)，与 B站热点一致。 |
| **职责** | 定时将「营销方法论」文档列表/内容刷新到缓存（结果报告）；get_output() **只读该缓存/报告**，返回一段可供主分析或下游使用的文本，写入例如 `result["methodology"]`。 |
| **刷新** | refresh()：调用 MethodologyService.list_docs() + get_content()，拼成报告文本，写入 cache（如 key = `plugin:analysis:methodology:report`），TTL 可配置。 |
| **get_output** | 只从 cache 读报告；若无则返回「暂无方法论」类兜底，不在此刻调 MethodologyService。 |
| **单独查看** | 与现有 GET /api/v1/methodology 共用 MethodologyService；前端可直接调 API 查看/取用，不经过插件。 |

### 3.2 案例库插件（case_library）

| 项目 | 说明 |
|------|------|
| **插件名** | `case_library` |
| **类型** | **定时插件** (scheduled)。 |
| **职责** | 定时将案例列表/摘要或精选案例内容刷新到缓存（结果报告）；get_output() **只读该缓存/报告**，返回案例相关文本，写入例如 `result["case_library"]`。 |
| **刷新** | refresh()：调用 CaseTemplateService.list_cases(..., order_by_score=True, include_content=True)，取 top N，拼成报告，写入 cache（如 key = `plugin:analysis:case_library:report`）。 |
| **get_output** | 只从 cache 读报告；若无则返回「暂无案例」类兜底，不在此刻调 CaseTemplateService。 |
| **单独查看** | 与现有 GET /api/v1/cases 等 API 共用 CaseTemplateService；单独取用、查看案例仍走 API。 |

### 3.3 知识库插件（knowledge_base）

| 项目 | 说明 |
|------|------|
| **插件名** | `knowledge_base` |
| **类型** | **实时插件 + 强缓存**：get_output(context) 用 request/topic 等拼出 query，以 query 的 cache key 查缓存；命中则直接返回，未命中再调 KnowledgePort.retrieve() 并写入缓存。 |
| **职责** | 为分析/生成提供「行业知识」片段；每次使用**优先走缓存**，避免重复检索。 |
| **get_output** | 先查 cache（key 如 `plugin:analysis:kb:{hash(query)}`），命中则返回；否则 retrieve 后 set cache，再返回。写入例如 `result["knowledge_base"]`。 |
| **单独查看** | 若需要「单独查知识库」能力，可保留现有检索 API 或通过同一 KnowledgePort 提供查询接口，与插件共用数据源。 |

### 3.4 分析脑内「活动策划」的拼装方式（可选）

- 若希望主分析 LLM 和生成脑拿到的是一段「方法论 + 知识库 + 案例」合并文本，有两种做法（二选一，不增加编排逻辑）：  
  - **A**：分析脑在执行完上述三插件后，在脑内将 `result["methodology"]`、`result["knowledge_base"]`、`result["case_library"]` 拼成一段 `campaign_context`，写入 `result["campaign_context"]`，供生成脑使用；主分析若需要也可在同一轮把这段并入 preference_context（由分析脑内部机制完成，不依赖编排层）。  
  - **B**：规划脑在活动策划场景下直接列三个插件（methodology, case_library, knowledge_base），生成脑插件从 analysis 里读这三段自行拼接。  
- 推荐 **A**：在分析脑内做一次拼装并写入 `result["campaign_context"]`，生成脑只依赖 `campaign_context`，这样生成脑插件逻辑简单，且拼装仍在「脑内」完成。

---

## 四、生成脑插件（每次用缓存/报告）

### 4.1 活动方案生成插件（campaign_plan_generator）

| 项目 | 说明 |
|------|------|
| **插件名** | `campaign_plan_generator` |
| **类型** | 实时插件；若内部需要「参考案例/方法论」的固定模板，可依赖分析脑已写入的 `campaign_context`（本身来自缓存/报告），不再重复拉取。 |
| **职责** | 根据 analysis（含 `campaign_context`、angle、reason 等）调用 LLM 生成完整活动方案（Markdown）。输入全部来自 analysis，**不在此处再调方法论/案例服务**，因此等价于「每次使用都基于已有结果报告（analysis）」。 |
| **get_output** | 读 analysis，若有 `campaign_context` 则用之生成；否则可回退到默认文案生成。可对「相同 analysis 指纹」做短 TTL 缓存，进一步减少重复生成。 |

---

## 五、编排层与规划脑（不增加任务分支）

- **编排层**  
  - 仅保留通用步骤：如 web_search、memory_query、**analyze**、generate、evaluate。  
  - **不再**包含 kb_retrieve、methodology_retrieve、case_retrieve 等步骤；这些能力全部由分析脑插件（knowledge_base、methodology、case_library）在 **analyze** 步骤内完成。  
  - 编排层不根据 task_type 或任务类型做任何分支；只根据 plan 执行步骤，并把 planning 给出的 analysis_plugins / generation_plugins 传给 analyze / generate。

- **规划脑**  
  - 根据意图输出 plan 与插件列表。**插件列表只登记拼装后或无需拼装的插件**。例如：  
    - 活动策划意图 → plan 含 analyze + generate，analysis_plugins = [**campaign_context**]（拼装由分析脑插件中心内聚 methodology+case_library+knowledge_base），generation_plugins = [campaign_plan_generator]。  
    - 其他意图 → analysis_plugins = []（kb_retrieve、bilibili_hotspot 等由编排层按 step 执行），generation_plugins = [text_generator] 等。  
  - 不在编排层增加「是否活动策划」的判断；任务语义完全由规划脑的「步骤 + 插件列表」表达。

---

## 六、插件清单与缓存/报告约定小结

| 脑 | 插件名 | 类型 | 每次使用方式 | 单独查看/取用 |
|----|--------|------|--------------|----------------|
| 分析脑 | methodology | 定时 | get_output 只读缓存/报告 | 现有 GET /api/v1/methodology 等 |
| 分析脑 | case_library | 定时 | get_output 只读缓存/报告 | 现有 GET /api/v1/cases 等 |
| 分析脑 | knowledge_base | 实时+缓存 | get_output 先读缓存，未命中再检索并回写 | 可选：共用 KnowledgePort 的查询 API |
| 生成脑 | campaign_plan_generator | 实时（可带短 TTL 缓存） | 只读 analysis（含来自缓存的 campaign_context） | - |

**约定**：所有插件的 get_output() 路径都必须「优先缓存或结果报告」；禁止在 get_output() 内无缓存地直接打 DB/检索（定时插件靠 refresh 写缓存，实时插件靠 key 缓存）。

---

## 七、实现顺序建议

1. **分析脑**  
   - 实现 **methodology**、**case_library** 为定时插件（refresh 写 cache，get_output 只读 cache）；  
   - 实现 **knowledge_base** 为带 key 缓存的实时插件；  
   - 在分析脑内（可选）将三者的输出拼成 `campaign_context` 写入 result，供生成脑使用；  
   - 插件中心 config 注入 MethodologyService、CaseTemplateService、KnowledgePort（或工厂），仅用于 **refresh** 或缓存未命中时的拉取，不用于「每次请求都直接调服务」。

2. **生成脑**  
   - 实现 **campaign_plan_generator**，只读 analysis；  
   - 为生成脑增加 plugin_center 与 generation_plugins 执行逻辑（若尚未有）。

3. **编排层**  
   - 移除 kb_retrieve 等「编排级检索」步骤（或保留为可选兼容，但活动策划路径不依赖）；  
   - 不增加任何 task_type / 任务分支；只传 analysis_plugins / generation_plugins 给 analyze / generate。

4. **规划脑**  
   - 在 planning_node 中根据意图设置 analysis_plugins、generation_plugins；**只登记拼装后或无需拼装的插件**（例如活动策划时 analysis_plugins = [campaign_context]，generation_plugins = [campaign_plan_generator] 或 [text_generator]）。

这样满足：能力全部在脑内插件、案例/方法论可单独查看、编排层无任务分支、每次使用都走缓存或结果报告，对性能影响最小。

---

## 八、对已有插件与插件植入方式的影响（结论：不影响）

### 8.1 已有插件（如 B站热点）

- **不改变**：现有插件（如 `bilibili_hotspot`）的**注册方式**、**调用路径**、**返回格式**均保持不变。
- **当前用法**：B站热点是**编排层步骤**——规划脑在 plan 中输出 step `bilibili_hotspot`，编排层在并行步骤里执行 `_run_bilibili_hotspot`，内部调用 `plugin_center.get_output("bilibili_hotspot", context)`，结果写入 `context["analysis"]`。本方案**不删、不改**该步骤，也不改该插件的 `register` / `get_output` / `refresh` 契约。
- **结论**：已有插件继续按「编排步骤 + 插件中心 get_output」的方式工作，本方案不触碰。

### 8.2 插件植入方法（注册 + 调用）

- **注册方式不变**：  
  - 仍在 `core/brain_plugin_center.py` 的 **ANALYSIS_BRAIN_PLUGINS** / **GENERATION_BRAIN_PLUGINS** 中声明 `(模块路径, "register")`。  
  - 插件内仍实现 `register(plugin_center, config)`，调用 `plugin_center.register_plugin(name, type, get_output=..., refresh_func=..., ...)`。  
  本方案只是在该清单中**新增**条目（如 methodology、case_library、knowledge_base、campaign_plan_generator），不修改现有条目的约定。

- **调用路径保持两种，并存**：  
  - **路径 A（编排步骤）**：plan 中含有 step 名（如 `bilibili_hotspot`）→ 编排层有对应 `_run_xxx`，内部调用 `plugin_center.get_output(name, context)`。现有 B站热点走此路径，**不改为路径 B**。  
  - **路径 B（分析/生成脑内按列表执行）**：规划脑输出 `analysis_plugins` / `generation_plugins` 列表 → 编排层调用 `ai_svc.analyze(..., analysis_plugins=[...])` 或 `ai_svc.generate(..., generation_plugins=[...])` → 分析脑/生成脑内部对列表中的插件依次调用 `plugin_center.get_output(name, context)` 并合并结果。本方案新增的 methodology、case_library、knowledge_base、campaign_plan_generator 走**路径 B**。  
  两种路径共用同一套**注册与插件中心**，只是「由谁在何时调用 get_output」不同：路径 A 由编排层按 step 调用，路径 B 由脑内按 analysis_plugins/generation_plugins 调用。本方案不删除、不弱化路径 A。

- **结论**：植入方法仍是「注册到对应脑的插件清单 + 实现 register/get_output（及定时插件的 refresh）」；本方案仅**增加**一批走路径 B 的插件，不改变已有插件所采用的路径 A。

### 8.3 编排层步骤（kb_retrieve 等）

- **可选兼容**：若希望与现有「plan 里含 kb_retrieve」的用法兼容，编排层可**保留** `kb_retrieve` 步骤（及现有 `_run_kb_retrieve`）。活动策划路径下由规划脑输出 `analysis_plugins = [knowledge_base, methodology, case_library]`，不再依赖 plan 中的 kb_retrieve 步骤；其他场景仍可在 plan 中保留 kb_retrieve，编排层照常执行。  
  即：**不强制删除**编排层的 kb_retrieve，新旧两种用法可并存，已有插件与已有 plan 不受影响。

### 8.4 小结

| 维度 | 是否受影响 | 说明 |
|------|------------|------|
| 已有插件（如 bilibili_hotspot） | **否** | 注册、调用路径（编排步骤）、get_output/refresh 契约均不变。 |
| 插件注册方式 | **否** | 仍在 ANALYSIS_BRAIN_PLUGINS / GENERATION_BRAIN_PLUGINS 中声明，register(plugin_center, config) 约定不变。 |
| 插件调用路径 | **否** | 保留「编排步骤 → get_output」；新增「analysis_plugins/generation_plugins → 脑内 get_output」为**额外**路径，不替换现有路径。 |
| 编排层对已有步骤的处理 | **否** | 不删除 bilibili_hotspot、kb_retrieve 等现有步骤逻辑；kb_retrieve 可保留为可选步骤以兼容既有 plan。 |

因此，当前方案**不影响**已有插件，也**不改变**现有插件的植入方法；只是在同一套插件体系下**新增**若干插件，并让它们通过「分析/生成脑内按列表执行」这条已有机制参与执行。

---

## 九、插件灵活配置（cache key、refresh 频率等）

各插件从插件中心 `config` 中读取同名配置块（如 `config["methodology_plugin"]`），未提供则使用默认值。可通过 **SimpleAIService** 构造时传入对应参数覆盖。

### 9.1 methodology 插件

| 配置键 | 说明 | 默认值 |
|--------|------|--------|
| cache_key | 缓存键（报告写入/读取） | `plugin:analysis:methodology:report` |
| refresh_interval_hours | 定时刷新间隔（小时） | 6 |
| ttl_seconds | 缓存 TTL（秒） | 21600（6 小时） |
| max_docs | 最多拉取方法论文档数 | 10 |
| max_content_length | 每篇文档截断长度 | 800 |

**传入方式**：`SimpleAIService(..., methodology_plugin={"cache_key": "...", "refresh_interval_hours": 8})`

### 9.2 case_library 插件

| 配置键 | 说明 | 默认值 |
|--------|------|--------|
| cache_key | 缓存键 | `plugin:analysis:case_library:report` |
| refresh_interval_hours | 定时刷新间隔（小时） | 6 |
| ttl_seconds | 缓存 TTL（秒） | 21600 |
| page_size | 刷新时拉取案例条数 | 5 |
| max_content_length | 每条案例内容截断长度 | 1200 |

**传入方式**：`SimpleAIService(..., case_library_plugin={"cache_key": "...", "refresh_interval_hours": 4})`

### 9.3 knowledge_base 插件

| 配置键 | 说明 | 默认值 |
|--------|------|--------|
| cache_key_prefix | 按 query 缓存的键前缀 | `plugin:analysis:kb:` |
| ttl_seconds | 单条检索缓存 TTL（秒） | 3600 |
| top_k | 检索条数 | 4 |

**传入方式**：`SimpleAIService(..., knowledge_base_plugin={"cache_key_prefix": "...", "ttl_seconds": 7200})`

### 9.4 campaign_plan_generator 插件

| 配置键 | 说明 | 默认值 |
|--------|------|--------|
| cache_key_prefix | 按 analysis 指纹缓存的键前缀 | `plugin:generation:campaign_plan:` |
| cache_ttl_seconds | 生成结果缓存 TTL（秒）；0 表示不缓存 | 0 |

**传入方式**：`SimpleAIService(..., campaign_plan_generator={"cache_ttl_seconds": 1800})`
