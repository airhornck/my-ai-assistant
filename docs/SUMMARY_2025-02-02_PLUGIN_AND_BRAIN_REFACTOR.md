# 今日修改与设计总结（2025-02-02）

## 一、设计目标与原则

1. **拼装逻辑在各脑的插件中心**  
   拼装不放在规划脑与编排层；规划脑只输出「要执行哪些插件」的列表。

2. **插件列表只登记「拼装后」或「无需拼装」的插件**  
   供规划脑/编排层使用的列表里只有最终插件名（如 `campaign_context`），不暴露子插件（如 methodology、case_library、knowledge_base）。

3. **文本/图片/视频/PPT 等均以插件方式在生成脑**  
   生成脑通过插件中心按 `generation_plugins` 调用；文本生成仍用 qwen3-max，模型配置由各脑的插件中心 config 管理。

4. **模型配置由各脑插件中心管理**  
   生成脑插件从 `config["models"][插件名]` 读模型；配置来源为 `config/api_config.py`（含 `generation_text`）与 `.env` 中的 Key。

---

## 二、今日具体修改内容

| 修改项 | 位置 | 说明 |
|--------|------|------|
| **任务→插件注册表** | `core/task_plugin_registry.py`（新增） | 规划脑由 if/else 改为查表：`get_plugins_for_task(task_type, step_names)` 返回 analysis_plugins / generation_plugins；后续新增任务只需在注册表加一项。 |
| **规划脑用注册表** | `workflows/meta_workflow.py` | planning_node 中改为调用 `get_plugins_for_task(task_type, step_names)`，不再写死 campaign_or_copy 分支。 |
| **带插件的分析也走缓存** | `services/ai_service.py`、`cache/smart_cache.py` | 当 analysis_plugins 非空时同样走 get_or_set，TTL 用 TTL_ANALYSIS_WITH_PLUGINS（5 分钟）；build_analyze_cache_key 中 context_fingerprint 的 analysis_plugins 参与缓存键。 |
| 文档：规划脑插件列表表述 | `docs/CAMPAIGN_PLUGINS_PLAN.md` | 将「analysis_plugins = [knowledge_base, methodology, case_library]」改为「analysis_plugins = [campaign_context]」，并明确插件列表只登记拼装后或无需拼装的插件。 |
| 文档：实现顺序中的规划脑描述 | `docs/CAMPAIGN_PLUGINS_PLAN.md` | 规划脑设置 analysis_plugins/generation_plugins 的示例改为 campaign_context、campaign_plan_generator/text_generator。 |
| 生成脑插件清单注释 | `core/brain_plugin_center.py` | 在 GENERATION_BRAIN_PLUGINS 注释中说明文本/图片/视频/PPT 以插件登记、模型由插件中心管理，并增加未来 ppt_generator 的注释。 |

说明：此前已完成分析脑拼装插件、生成脑插件化及插件中心模型配置；本次增加了**任务→插件注册表**与**带插件的分析缓存**，并撰写 [主体架构性能优化与「只加插件」说明](ARCHITECTURE_OPTIMIZATION_AND_PLUGIN_ONLY.md)。

---

## 三、所涉及/设计的文件清单与职责

### 3.1 核心配置与插件中心

| 文件 | 职责 |
|------|------|
| `config/api_config.py` | 统一接口配置：PROVIDERS（Key/Base URL）、LLM_INTERFACES（含 generation_text）。生成脑所用模型接口与 Key 在此配置，Key 实际值在 .env。 |
| `core/brain_plugin_center.py` | 脑级插件中心：ANALYSIS_BRAIN_PLUGINS / GENERATION_BRAIN_PLUGINS 清单，BrainPluginCenter 的注册、get_output、定时任务。 |
| `core/task_plugin_registry.py` | 任务类型→插件列表注册表：TASK_PLUGIN_MAP、get_plugins_for_task；规划脑据此推导 analysis_plugins / generation_plugins，后续新增任务只加注册表项。 |

### 3.2 分析脑插件

| 文件 | 职责 |
|------|------|
| `plugins/methodology/plugin.py` | 定时插件：refresh 写缓存/报告，get_output 只读。 |
| `plugins/case_library/plugin.py` | 定时插件：同上。 |
| `plugins/knowledge_base/plugin.py` | 实时+缓存：get_output 先查缓存，未命中再检索并回写。 |
| `plugins/campaign_context/plugin.py` | **拼装插件**：get_output 内通过插件中心依次调 methodology、case_library、knowledge_base，拼成 campaign_context。 |
| `plugins/bilibili_hotspot/plugin.py` | 实时插件：B 站热点，由编排层按 step 调用。 |

### 3.3 生成脑插件

| 文件 | 职责 |
|------|------|
| `plugins/text_generator/plugin.py` | 文本生成，从 config["models"]["text_generator"] 或 get_model_config("generation_text") 读模型（默认 qwen3-max）。 |
| `plugins/campaign_plan_generator/plugin.py` | 活动方案生成，从 config["models"]["campaign_plan_generator"] 读模型。 |
| `plugins/image_generator/plugin.py` | 图片生成占位。 |
| `plugins/video_generator/plugin.py` | 视频生成占位。 |

### 3.4 脑门面与编排

| 文件 | 职责 |
|------|------|
| `domain/content/analyzer.py` | 分析脑：支持 analysis_plugins，并行执行插件并合并结果；无拼装逻辑。 |
| `domain/content/generator.py` | 生成脑：仅通过 plugin_center 按 generation_plugins（或 output_type 默认列表）调用插件。 |
| `services/ai_service.py` | 构建分析/生成脑插件中心 config，将 get_model_config("generation_text") 注入 gen_config["models"]，挂载到 ContentAnalyzer/ContentGenerator。 |
| `workflows/meta_workflow.py` | 规划脑 planning_node：通过 get_plugins_for_task(task_type, step_names) 查注册表得到 analysis_plugins / generation_plugins；编排层只传这两列表给 analyze/generate，无 task_type 分支拼装。 |
| `workflows/types.py` | MetaState 含 analysis_plugins、generation_plugins。 |

### 3.5 应用入口

| 文件 | 职责 |
|------|------|
| `main.py` | 创建 SimpleAIService 时注入 methodology_service、case_service、knowledge_port 及可选插件配置；无独立 /campaign/plan 端点。 |

### 3.6 文档

| 文件 | 职责 |
|------|------|
| `docs/CAMPAIGN_PLUGINS_PLAN.md` | 活动策划插件化方案；今日修正规划脑插件列表表述。 |
| `docs/ENV_KEYS_REFERENCE.md` | 环境变量 Key 说明（如 DASHSCOPE_API_KEY）。 |
| `docs/LLM_CONFIG_GUIDE.md` | 统一接口配置与生成脑所用 generation_text 的配置方式。 |

---

## 四、配置入口速查（生成脑模型与 Key）

- **接口定义**：`config/api_config.py` → `LLM_INTERFACES["generation_text"]`（可被环境变量 MODEL_GENERATION_TEXT_PROVIDER、MODEL_GENERATION_TEXT 等覆盖）。
- **API Key / Base URL**：由 provider 决定，在 `PROVIDERS` 中写死环境变量名；实际值在项目根目录 `.env`（或 `.env.dev` / `.env.prod`）中配置，例如：
  - 默认 dashscope：`DASHSCOPE_API_KEY`、可选 `DASHSCOPE_BASE_URL`
  - 若改为 DeepSeek：`MODEL_GENERATION_TEXT_PROVIDER=deepseek`、`MODEL_GENERATION_TEXT=deepseek-chat`，并配置 `DEEPSEEK_API_KEY`。

---

## 五、数据流简图

```
规划脑(planning_node)
  → 输出 plan、task_type；analysis_plugins / generation_plugins 由 get_plugins_for_task(task_type, step_names) 查注册表得到
编排层(orchestration_node)
  → 执行 plan 中的步骤；analyze 时传 analysis_plugins，generate 时传 generation_plugins
分析脑(ContentAnalyzer)
  → 若 analysis_plugins 含 campaign_context，调用 plugin_center.get_output("campaign_context", context)
  → campaign_context 插件内部再调 methodology / case_library / knowledge_base，拼成 campaign_context
生成脑(ContentGenerator)
  → 按 generation_plugins 依次 plugin_center.get_output(插件名, context)；插件从 config["models"][插件名] 读模型
```

以上为今日修改内容与所设计/涉及文件的总结。  
主体架构性能优化与「后续只加插件」的详细说明见 [ARCHITECTURE_OPTIMIZATION_AND_PLUGIN_ONLY.md](ARCHITECTURE_OPTIMIZATION_AND_PLUGIN_ONLY.md)。
