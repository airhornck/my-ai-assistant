# 最终实现方案：设计回顾、今日改动与性能保障

## 一、设计回顾（最终形态）

1. **规划脑**：基于意图输出 **步骤**（供前端思考过程展示）+ **分析/生成插件列表**（供编排执行）；步骤与插件列表由同一意图推导，保证用户可见的「思考过程」体验。
2. **分析脑 / 生成脑**：以 **插件** 承载 IP 诊断、IP 打造、活动策划、知识库检索、营销方法论等能力；编排层执行 analyze/generate 时传入本轮插件列表，脑内按列表执行并合并结果。
3. **独立模块**：数据闭环、知识库检索、营销方法论管理、案例模板与打分，作为可维护的独立模块，被插件或编排层调用。
4. **性能与体验**：并行执行、超时降级、缓存复用、避免阻塞主链路，保障用户问答响应与体验。

---

## 二、今日已修改内容（回顾）

| 类别 | 内容 | 位置 |
|------|------|------|
| 数据闭环 | feedback_events / platform_metrics 表；DataLoopService；POST /data/feedback、/data/platform-metrics | database.py, modules/data_loop/, routers/data_and_knowledge.py |
| 知识库独立 | KnowledgePort + LocalKnowledgeAdapter + AliyunKnowledgeAdapter + get_knowledge_port() | modules/knowledge_base/ |
| 案例模板与打分 | MarketingCaseTemplate / CaseScore 表；CaseTemplateService；CRUD、from-session、scores API | database.py, modules/case_template/, routers |
| 方法论管理 | MethodologyService（文件）；GET/PUT/DELETE /methodology | modules/methodology/, routers |
| 活动策略编排 | run_campaign_with_context（方法论+知识库+案例并行）；prompt「以案例为基础改写或填空」 | workflows/strategy_orchestrator.py |
| 活动策划（统一入口） | 通过 frontend/chat，task_type=campaign_or_copy 时编排走 strategy_orchestrator | main.py + meta_workflow.py |
| 编排 kb_retrieve | PARALLEL_STEPS 含 kb_retrieve；context["kb_context"] 并入 analyze preference_ctx；规划提示含 kb_retrieve | workflows/meta_workflow.py |
| 保存为案例 | POST /api/v1/cases/from-session | routers/data_and_knowledge.py |
| 规划脑注入 knowledge_port | build_meta_workflow(..., knowledge_port=...)；三处调用传入 get_knowledge_port(smart_cache) | main.py, meta_workflow.py |
| 设计文档 | DATA_LOOP_AND_KNOWLEDGE_MODULES_DESIGN.md, IP_GOAL_AND_ROADMAP.md, IP_PLUGIN_ARCHITECTURE_ANALYSIS.md | docs/ |

---

## 三、本次最终实现（步骤 + 插件列表 + 性能）

### 3.1 规划脑输出：步骤 + 插件列表

- **保留**：`plan` 步骤数组不变，继续用于 `thinking_logs` 与前端「思考过程」展示。
- **新增**：在规划节点返回值中增加 `analysis_plugins`、`generation_plugins`。
  - **来源**：为保障性能与稳定性，**不增加规划 LLM 的额外输出字段**，由 **plan 步骤推导**：
    - `analysis_plugins`：若 plan 中含 `kb_retrieve` 则含 `"kb_retrieve"`，若含 `bilibili_hotspot` 则含 `"bilibili_hotspot"`；其余分析侧插件可后续按步骤名扩展。
    - `generation_plugins`：若 plan 中含 `generate` 则 `["copy_writer"]`，否则 `[]`；后续可扩展为 `campaign_plan`、`ip_building_plan` 等。
  - **状态**：写入 MetaState（或等价 state），供编排层读取。

### 3.2 编排层：执行 analyze 时传入 analysis_plugins

- 执行到步骤 `analyze` 时，从 state 读取 `analysis_plugins`（若无则 `[]`），调用 `ai_svc.analyze(..., analysis_plugins=...)`。
- 执行到步骤 `generate` 时，从 state 读取 `generation_plugins`（若无则 `[]`）；当前生成脑尚未插件化，可先传参占位，生成脑内部暂不按列表分支，保持现有行为。

### 3.3 分析脑：按 analysis_plugins 并行执行插件

- `ContentAnalyzer.analyze(..., analysis_plugins: Optional[List[str]] = None)`：
  - 若 `analysis_plugins` 为空或 None，行为与现有一致（仅主分析 LLM）。
  - 若非空：在 **主分析 LLM 调用之后**（或之前，视产品需求），对列表中的插件 **并行** 调用 `plugin_center.get_output(plugin_name, context)`，单插件 **超时**（如 5s），失败则降级为空 dict；将各插件输出合并进返回的 analysis 字典（如 `analysis[plugin_name] = output`），再与主分析结果合并。
- **性能**：`asyncio.gather` + 单插件 `asyncio.wait_for(..., timeout=5)`，避免单插件拖死整体；主分析继续走现有缓存（build_analyze_cache_key）。

### 3.4 性能保障要点

- **规划**：不增加额外 LLM 轮次；插件列表由 plan 推导，解析零成本。
- **编排**：已有并行步骤（web_search、memory_query、kb_retrieve、bilibili_hotspot）不变；analyze 内插件并行 + 超时。
- **分析**：analyze 结果继续使用 SmartCache（key 含请求指纹）；插件执行超时与降级，不阻塞主分析返回。
- **生成**：现有策略编排（campaign）已用 asyncio.gather 并行拉取知识库/案例/方法论；超时与降级已存在。
- **前端**：思考过程仅消费 `plan` + 各步 reason/thought，不依赖插件列表，体验不变。

---

## 四、实现清单（本次已执行）

- [x] 规划脑：在 planning_node 返回中增加 `analysis_plugins`、`generation_plugins`（由 plan 推导；当前 analysis_plugins=[] 避免与编排内 kb_retrieve/bilibili_hotspot 重复执行）。
- [x] MetaState / _ensure_meta_state：支持读写 `analysis_plugins`、`generation_plugins`。
- [x] 编排层：analyze 步骤从 base 读取 `analysis_plugins`，调用 `ai_svc.analyze(..., analysis_plugins=..., context_fingerprint 含 analysis_plugins)`。
- [x] SimpleAIService.analyze：增加参数 `analysis_plugins`；非空时不走缓存，透传 ContentAnalyzer。
- [x] ContentAnalyzer.analyze：增加 `analysis_plugins` 与 `_run_analysis_plugins`；非空时并行执行插件（单插件超时 5s），结果合并进 analysis。
- [x] 文档：本最终实现方案（FINAL_IMPLEMENTATION_PLAN.md）。

---

## 五、后续可扩展（不在此次执行）

- 规划脑由 LLM 直接输出 `analysis_plugins` / `generation_plugins`（需扩展 prompt 与解析，注意性能）。
- 生成脑插件化：ContentGenerator 支持 `generation_plugins`，按列表路由到 campaign_plan、ip_building_plan、copy_writer 等插件。
- IP 诊断 / IP 打造方案 专用插件与输出结构（见 IP_GOAL_AND_ROADMAP.md）。
