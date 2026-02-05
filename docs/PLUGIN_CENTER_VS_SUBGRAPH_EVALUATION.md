# 各脑插件：插件中心 vs 子图模式 评估

> 评估各脑（分析脑、生成脑）内插件是否应从「插件中心」改为「子图/节点」模式，以及性能与架构的合理性。

## 一、当前实现概览

### 1.1 插件中心模式（现状）

| 脑 | 子图结构 | 插件调用方式 |
|----|----------|--------------|
| **分析脑** | 单节点 `run_analysis` → `ai_svc.analyze()` | `ContentAnalyzer` 内：先 LLM 分析，再 **并行** `asyncio.gather(plugin_center.get_output(name, ctx))` 合并结果 |
| **生成脑** | 单节点 `run_generate` → `ai_svc.generate()` | `ContentGenerator` 内：**顺序**遍历 `generation_plugins`，`plugin_center.get_output(name, ctx)` 取第一个有内容的返回 |

- **插件中心**（`BrainPluginCenter`）：负责注册、定时刷新（scheduled）、`get_output(name, context)`。
- **分析脑插件**：bilibili_hotspot、methodology、case_library、knowledge_base、campaign_context（拼装前三者）。
- **生成脑插件**：text_generator、campaign_plan_generator、image_generator、video_generator。

### 1.2 数据流（简化）

```
主图 router → analyze 子图(单节点 run_analysis)
                    → ai_svc.analyze()
                         → LLM 分析
                         → _run_analysis_plugins(): asyncio.gather(get_output(methodology), get_output(case_library), ...)
                         → 合并到 result
主图 router → generate 子图(单节点 run_generate)
                    → ai_svc.generate()
                         → for name in plugins: get_output(name, ctx); 取第一个 content
```

插件本身**不**作为 LangGraph 节点存在，只在「一个节点内部」通过插件中心被调用。

---

## 二、两种方案对比

### 方案 A：保持插件中心（当前）

- **结构**：脑子图 = 1 个节点（如 `run_analysis` / `run_generate`），节点内调用 `ai_svc.analyze/generate`，内部再通过 `plugin_center.get_output` 执行各插件。
- **分析脑**：LLM 分析 + 多插件 **并行**（`asyncio.gather`），单插件超时 5s，失败降级为空。
- **生成脑**：按 `generation_plugins` **顺序**尝试插件，第一个返回 content 即返回。

### 方案 B：插件子图化（每个插件为节点/子图）

- **结构**：脑子图 = 多节点，例如分析脑：`entry → node(methodology) → node(case_library) → node(campaign_context) → merge`，或并行分支再合并。
- **生成脑**：按 `output_type` / 插件列表条件边到 `node(text_generator)`、`node(image_generator)` 等，或顺序节点。
- **插件**：每个插件对应一个 LangGraph 节点（或一个最小子图），在图中可见、可观测、可条件分支。

---

## 三、性能对比

| 维度 | 插件中心（A） | 子图化（B） |
|------|----------------|-------------|
| **状态传递** | 1 次进/出脑子图，脑内无额外 state 传递 | N 个插件 = N 次节点调度与 state 读写 |
| **分析脑并行** | 已在节点内 `asyncio.gather` 并行，与「多节点并行」等价 | 若做成并行节点，并发度相同，但多 N 次图调度与序列化 |
| **生成脑顺序** | 顺序 `get_output`，早退出，无多余调度 | 顺序 N 个节点，每步都有图调度与 state 读写 |
| **定时/缓存** | 由插件中心统一管理（refresh_func、cache），逻辑集中 | 定时与缓存仍需在某处实现，若放进各节点则重复；若保留「插件运行器」则仍是中心式调用，只是多了一层图节点包装 |
| **结论** | **性能更优或持平**：脑内无多余图调度，分析脑已并行，生成脑顺序早退 | **略差**：多出 N 次节点执行与 state 序列化，收益主要在可观测与可分支 |

要点：**真正耗时在 LLM 与插件 I/O**，图调度是固定开销。插件中心下「一个节点内并行/顺序调插件」与「多节点分别调插件」在 I/O 上等价，但图模式多出调度与 state 读写，因此**性能上插件中心更合理**。

---

## 四、架构对比

| 维度 | 插件中心（A） | 子图化（B） |
|------|----------------|-------------|
| **职责分离** | **清晰**：图负责「何时跑哪一步」；插件中心负责「有哪些能力、如何执行、定时/缓存」 | 图既管编排又管「每个能力对应哪节点」，插件与图强绑定 |
| **扩展新插件** | **只改清单**：在 `ANALYSIS_BRAIN_PLUGINS` / `GENERATION_BRAIN_PLUGINS` 登记，无需改图代码 | **改图**：加节点、加边、可能加条件分支，图逻辑与插件数量耦合 |
| **拼装/复合插件** | **自然**：如 campaign_context 在插件内调 methodology/case_library/knowledge_base，对图透明 | 需在图中显式表达「campaign_context 依赖前三者」的边或子图，图更复杂 |
| **可观测性** | LangSmith 只看到「run_analysis」「run_generate」一个节点，插件级需靠日志/span | 每个插件一个节点，LangSmith 可看到每插件耗时与输入输出 |
| **人工介入/条件** | 人工介入在「主图」评估后已实现；脑内按插件中断/分支需求不强 | 若未来需要「某个插件失败则走降级节点」等，用条件边更直观 |
| **结论** | **架构更合理**：编排与能力注册解耦，新增/下架插件不改图，复合插件内聚在插件内 | 图更「细粒度」，但扩展与维护成本更高，适合强需求「每步都要在图里可见/可分支」时再考虑 |

---

## 五、何时考虑子图化

以下情况可**局部**引入子图/节点，而不必全盘替换插件中心：

1. **可观测性优先**：需要 LangSmith 上每个插件单独一步的 trace → 可把「执行所有分析插件」拆成两个节点：`llm_analyze` + `run_analysis_plugins`（仍用 plugin_center），这样至少有两步；或对少数关键插件单独做节点。
2. **脑内人工介入**：若未来要在「某个分析/生成插件执行前」做人工确认，可在该步骤前后加节点与 `interrupt`，此时该步骤适合做成独立节点（仍可调用 plugin_center.get_output）。
3. **按插件条件分支**：例如「若 methodology 缓存未命中则先跑 kb_retrieve 再跑 methodology」，用条件边表达更清晰，此时可把 methodology、kb_retrieve 做成独立节点，其余仍走插件中心。

即使做上述「局部子图化」，也建议**保留插件中心的注册、定时、get_output 与合并逻辑**，仅把「调用谁、何时调」在图里用节点/边表达，避免重复实现定时与缓存。

---

## 六、结论与建议

| 方面 | 更合理选择 | 说明 |
|------|------------|------|
| **性能** | **插件中心** | 少一层图调度与 state 传递，分析脑已并行、生成脑顺序早退，无性能损失 |
| **架构** | **插件中心** | 编排（图）与能力注册（插件中心）解耦，扩展插件只改清单，复合插件内聚 |
| **可观测** | 插件中心为主，**按需**加节点 | 默认保持现状；若需更细 trace，可增加「run_plugins」节点或对关键插件单独节点，仍复用 plugin_center |
| **人工介入/分支** | 主图已支持评估后介入；脑内若需再介入，再对单步做节点 | 不必为所有插件子图化，仅对需要中断或条件分支的步骤做成节点 |

**最终建议**：  
- **各脑的插件继续使用插件中心模式**，不整体改为「每个插件一个子图/节点」。  
- **性能与架构**上，当前插件中心方案更合理；子图化主要带来可观测与可分支，代价是图更复杂、扩展插件需改图。  
- 若后续有强需求（如某几步必须在 LangSmith 可见、或脑内人工确认），再对**少数步骤**做节点级子图化，并继续复用插件中心的注册与 `get_output`，而不是重写一套插件执行与定时逻辑。
