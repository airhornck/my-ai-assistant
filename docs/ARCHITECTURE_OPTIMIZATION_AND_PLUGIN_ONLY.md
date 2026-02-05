# 主体架构性能优化与「只加插件」说明

## 一、主体架构上还可做的性能优化（已做 / 可选）

### 1. 已实现的优化

| 优化项 | 位置 | 说明 |
|--------|------|------|
| **任务→插件注册表** | `core/task_plugin_registry.py` | 规划脑不再写死 if/else，由 `get_plugins_for_task(task_type, step_names)` 查表得到 analysis_plugins / generation_plugins。新增任务类型只需在注册表加一项。 |
| **带插件的分析也走缓存** | `services/ai_service.py` + `cache/smart_cache.py` | 当 `analysis_plugins` 非空时同样走 `get_or_set`，TTL 使用 `TTL_ANALYSIS_WITH_PLUGINS`（5 分钟），缓存键包含 `analysis_plugins`，同请求+同插件列表可命中，减轻重复请求的分析与插件调用。 |
| **分析缓存键含 analysis_plugins** | `cache/smart_cache.py` 的 `build_analyze_cache_key` | `context_fingerprint` 中传入的 `analysis_plugins` 参与缓存键，避免不同插件组合互相覆盖。 |

### 2. 可选的进一步优化（未实现）

| 优化项 | 说明 |
|--------|------|
| **规划结果短 TTL 缓存** | 对 (user_input 指纹) 缓存 (plan, task_type, analysis_plugins, generation_plugins)，TTL 1–2 分钟，相同/相似请求可少一次规划 LLM 调用。需权衡「用户期望每次都是新规划」的体验。 |
| **编排步内更多并行** | 当前 web_search、memory_query、bilibili_hotspot、kb_retrieve 已并行；若后续增加其他无依赖步骤，可一并纳入 `PARALLEL_STEPS` 并行执行。 |
| **生成结果可选缓存** | 生成脑插件已有按需缓存（如 campaign_plan_generator）；可在插件契约中统一约定 context 中提供 `cache` + `fingerprint`，方便各插件自选短 TTL 缓存。 |
| **插件懒加载** | 首次 `get_output(插件名)` 时再加载该插件模块，降低启动时间；当前为启动时全量加载。 |

---

## 二、「后续只加不同脑的插件」的操作流程

主体架构已收敛为：**规划脑只查注册表 → 编排按步骤与插件列表执行 → 各脑只跑插件中心**。后续新增能力时，只需加插件与注册表项（及必要时扩展规划 prompt 的 task_type），无需改规划/编排分支逻辑。

### 2.1 新增「分析脑」能力（例如 IP 诊断上下文）

1. **在分析脑增加插件**  
   - 在 `core/brain_plugin_center.py` 的 `ANALYSIS_BRAIN_PLUGINS` 中增加一条，例如：  
     `("plugins.ip_diagnosis_context.plugin", "register")`  
   - 实现 `plugins/ip_diagnosis_context/plugin.py`，实现 `register(plugin_center, config)` 与 `get_output`（拼装逻辑在插件内或再调其它分析插件）。

2. **在任务→插件注册表中挂到任务类型**  
   - 在 `core/task_plugin_registry.py` 的 `TASK_PLUGIN_MAP` 中增加一项，例如：  
     `"ip_diagnosis": { "analysis_plugins": ["ip_diagnosis_context"], "generation_plugins": ["ip_diagnosis_report"] }`  
   - 若该任务不需要生成，`generation_plugins` 可设为 `[]` 或省略（由 `_default` 兜底时不会乱加生成插件，因为只有 plan 含 `generate` 才会用生成插件）。

3. **（若为新 task_type）扩展规划脑 prompt**  
   - 在 `workflows/meta_workflow.py` 的 planning 系统提示中，在「先判断任务类型 task_type」处增加新类型说明（如 `ip_diagnosis`），并给出示例 JSON。

**无需改**：`planning_node` 的推导逻辑（已改为只调 `get_plugins_for_task`）、编排层步骤执行、analyze/generate 的调用方式。

### 2.2 新增「生成脑」能力（例如 IP 诊断报告）

1. **在生成脑增加插件**  
   - 在 `core/brain_plugin_center.py` 的 `GENERATION_BRAIN_PLUGINS` 中增加一条，例如：  
     `("plugins.ip_diagnosis_report.plugin", "register")`  
   - 实现 `plugins/ip_diagnosis_report/plugin.py`，从 `config["models"]` 读本插件所用模型（若需）；在 `services/ai_service.py` 的 `gen_config["models"]` 中为该插件名配上对应模型配置即可。

2. **在任务→插件注册表中挂到任务类型**  
   - 同上，在 `TASK_PLUGIN_MAP` 中该任务类型的 `generation_plugins` 里加入 `"ip_diagnosis_report"`。

3. **（若为新 task_type）扩展规划脑 prompt**  
   - 同上，在 planning 的 task_type 说明与示例中增加 `ip_diagnosis`。

**无需改**：`planning_node` 的 if/else、编排层、ContentAnalyzer/ContentGenerator 的通用逻辑。

### 2.3 小结：你只需要做的事

- **新分析能力**：写分析脑插件 → 在 `ANALYSIS_BRAIN_PLUGINS` 登记 → 在 `TASK_PLUGIN_MAP` 中为对应 task_type 填 `analysis_plugins`。  
- **新生成能力**：写生成脑插件 → 在 `GENERATION_BRAIN_PLUGINS` 登记 → 在 `TASK_PLUGIN_MAP` 中为对应 task_type 填 `generation_plugins`。  
- **新任务类型**：在 `TASK_PLUGIN_MAP` 增加一条 task_type → 在 planning 的 prompt 中增加该 task_type 的说明与示例。  

规划脑与编排层**不再**为具体任务写分支，只依赖「步骤名 + 任务类型 → 注册表 → 插件列表」。

---

## 三、相关文件速查

| 用途 | 文件 |
|------|------|
| 任务类型 → 插件列表 | `core/task_plugin_registry.py`（`TASK_PLUGIN_MAP`、`get_plugins_for_task`） |
| 分析/生成脑插件清单 | `core/brain_plugin_center.py`（`ANALYSIS_BRAIN_PLUGINS`、`GENERATION_BRAIN_PLUGINS`） |
| 规划脑使用注册表 | `workflows/meta_workflow.py`（`planning_node` 内调用 `get_plugins_for_task`） |
| 分析缓存（含带插件） | `services/ai_service.py`、`cache/smart_cache.py`（`TTL_ANALYSIS_WITH_PLUGINS`、`build_analyze_cache_key`） |
