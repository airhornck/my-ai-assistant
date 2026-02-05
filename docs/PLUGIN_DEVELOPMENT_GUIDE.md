# 插件开发指南

面向同事：如何扩展分析脑、生成脑能力。**新增插件与开发模板均沿用「插件中心」模式，无需改为子图**；详见 [PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION.md](./PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION.md)。

## 一、架构总览（当前）

```
策略脑（planning_node）→ 输出 plan、analysis_plugins、generation_plugins
         ↓
编排层（router + parallel_retrieval / analyze / generate / evaluate）
         ↓
分析脑（子图单节点 run_analysis）→ ai_svc.analyze() → 插件中心按 analysis_plugins 并行 get_output 并合并
生成脑（子图单节点 run_generate）→ ai_svc.generate() → 插件中心按 generation_plugins 顺序 get_output 取首个 content
```

- **脑级插件**：在 `BrainPluginCenter` 注册，通过 `register(plugin_center, config)` + `get_output(name, context)` 提供能力；**无需改图、无需子图化**。
- **扩展方式**：在对应脑的插件清单（`ANALYSIS_BRAIN_PLUGINS` / `GENERATION_BRAIN_PLUGINS`）登记模块路径即可，脑初始化时自动加载。

---

## 二、脑级插件开发（主流程）

### 2.1 新增插件步骤（通用）

1. **创建插件目录**：在 `plugins/` 下新建目录，如 `plugins/my_analyzer/`。
2. **实现 `register(plugin_center, config)`**：在 `plugin.py` 中向传入的 `plugin_center` 注册插件（类型、`get_output`，定时插件需 `refresh_func`）。
3. **登记到清单**：在 `core/brain_plugin_center.py` 中，将 `("plugins.my_analyzer.plugin", "register")` 加入 `ANALYSIS_BRAIN_PLUGINS` 或 `GENERATION_BRAIN_PLUGINS`。
4. **（可选）规划脑选用**：若需由策略脑按意图选用，在 `workflows/meta_workflow.py` 的 planning 提示中说明该步骤/插件名，规划脑会把插件名加入 `analysis_plugins` / `generation_plugins`。

**模板参考**：无独立 `plugin_template` 目录，可直接复制现有插件作为起点：
- 分析脑实时：`plugins/knowledge_base/`
- 分析脑定时：`plugins/methodology/`、`plugins/bilibili_hotspot/`
- 生成脑：`plugins/text_generator/`、`plugins/campaign_plan_generator/`

---

### 2.2 分析脑插件模板

**实时插件**（每次调用都执行，可自带缓存）：

```python
# plugins/my_analyzer/plugin.py
from __future__ import annotations
import logging
from typing import Any
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        request = context.get("request")
        analysis = context.get("analysis") or {}
        # 使用 config 中的 cache、ai_service 等
        result = {}  # 你的分析结果，如 {"some_key": "value"}
        return {"analysis": {**analysis, **result}}

    plugin_center.register_plugin(
        "my_analyzer",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )
```

**定时插件**（周期刷新写缓存，get_output 只读缓存）：

```python
# 参考 plugins/methodology/plugin.py
def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    cache = config.get("cache")

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        # 只读 cache，不在此处调外部服务
        text = await cache.get("plugin:analysis:my_analyzer:report") or "（暂无）"
        return {"analysis": {**(context.get("analysis") or {}), "my_analyzer": text}}

    async def refresh() -> None:
        # 定时执行：拉数据、写 cache
        report = "..."  # 从 DB/API 拉取并拼装
        await cache.set("plugin:analysis:my_analyzer:report", report, ttl=21600)

    plugin_center.register_plugin(
        "my_analyzer",
        PLUGIN_TYPE_SCHEDULED,
        get_output=get_output,
        refresh_func=refresh,
        schedule_config={"interval_hours": 6},
    )
```

登记：在 `core/brain_plugin_center.py` 的 `ANALYSIS_BRAIN_PLUGINS` 中添加：
`("plugins.my_analyzer.plugin", "register")`。

---

### 2.3 生成脑插件模板

生成脑插件需在 `get_output` 中返回 `{"content": "..."}`，生成脑会按 `generation_plugins` 顺序尝试，取第一个有 `content` 的结果。

```python
# plugins/my_generator/plugin.py
from __future__ import annotations
import logging
from typing import Any
from core.brain_plugin_center import BrainPluginCenter, PLUGIN_TYPE_REALTIME

logger = logging.getLogger(__name__)

def register(plugin_center: BrainPluginCenter, config: dict[str, Any]) -> None:
    models = config.get("models") or {}
    model_cfg = models.get("my_generator") or {}  # 可从 config 读模型配置

    async def get_output(_name: str, context: dict) -> dict[str, Any]:
        analysis = context.get("analysis") or {}
        topic = context.get("topic", "")
        # 调用 LLM 或外部 API 生成内容
        content = "..."  # 生成的文本/图片 URL 等
        return {"content": content}

    plugin_center.register_plugin(
        "my_generator",
        PLUGIN_TYPE_REALTIME,
        get_output=get_output,
    )
```

登记：在 `core/brain_plugin_center.py` 的 `GENERATION_BRAIN_PLUGINS` 中添加：
`("plugins.my_generator.plugin", "register")`。

模型配置可由 `ai_service` 初始化时注入到 `gen_config["models"]["my_generator"]`，见 `services/ai_service.py` 中生成脑 config。

---

### 2.4 插件类型与配置

| 类型 | 常量 | 说明 |
|------|------|------|
| 定时 | `PLUGIN_TYPE_SCHEDULED` | 需提供 `refresh_func`、`schedule_config`（如 `interval_hours`），get_output 只读缓存 |
| 实时 | `PLUGIN_TYPE_REALTIME` | 每次 get_output 都执行，可内部自建缓存 |
| 工作流/技能 | `PLUGIN_TYPE_WORKFLOW` / `PLUGIN_TYPE_SKILL` | 预留，当前用法同 realtime |

---

## 三、State / Context 约定（脑级插件）

插件收到的 `context` 由脑内传入，通常包含：

| 字段 | 说明 |
|------|------|
| request | ContentRequest（分析脑） |
| preference_context | 用户记忆/画像拼接串（分析脑） |
| analysis | 当前已合并的 analysis 字典，插件应返回 `{"analysis": {**existing, **你的键}}` 或 `{"analysis": {...}}` |
| topic, raw_query, session_document_context, memory_context | 生成脑常用 |

分析脑合并规则：插件返回中若存在 `"analysis"` 且为 dict，会与现有 analysis 合并；否则 `result[插件名] = out`。  
生成脑：按 `generation_plugins` 顺序调用，第一个返回非空 `content` 的插件结果被采用。

---

## 四、编排层自定义步骤（可选 / 进阶）

若要在「思维链」中增加**编排层步骤**（而非脑内插件），需改 `workflows/meta_workflow.py`：

1. 在 `_router_next` 中根据 `plan[current_step].step` 增加分支，指向新节点。
2. 实现新节点函数（如 `async def my_step_node(state): ...`），并 `workflow.add_node("my_step", my_step_node)`。
3. 在 `add_conditional_edges("router", _router_next, {..., "my_step": "my_step"})` 中增加映射，并加 `workflow.add_edge("my_step", "router")`。
4. 在 planning 的 system_prompt 中说明新步骤名，供策略脑输出。

此类扩展会改动图结构，一般仅在需要「独立步骤 + 图级可观测」时使用；**多数能力扩展建议用脑级插件完成**。

---

## 五、注册与配置小结

| 项目 | 位置 |
|------|------|
| 分析脑插件清单 | `core/brain_plugin_center.py` → `ANALYSIS_BRAIN_PLUGINS` |
| 生成脑插件清单 | `core/brain_plugin_center.py` → `GENERATION_BRAIN_PLUGINS` |
| 分析脑 config 注入 | `services/ai_service.py` → `analysis_config`（cache、ai_service、methodology_service 等） |
| 生成脑 config 注入 | `services/ai_service.py` → `gen_config`（cache、ai_service、models 等） |
| 规划脑步骤与插件名 | `workflows/meta_workflow.py` → planning_node 的 system_prompt |

---

## 六、测试与调试

1. **单测**：mock `plugin_center` 或 config，直接调用 `get_output(name, context)`。
2. **集成**：启动应用后，通过 `/api/v1/frontend/chat` 或 `/api/v1/analyze-deep/raw` 触发会走分析/生成的请求，观察日志中 `分析脑子图完成` / `生成脑子图完成` 及插件中心日志。
3. **定时插件**：启动后由插件中心执行 `run_initial_refresh()`，之后按 `schedule_config` 周期执行；可在 Redis/缓存中查看对应 key 是否有值。

---

## 七、参考文件

| 类型 | 路径 |
|------|------|
| 脑级插件架构 | `docs/BRAIN_PLUGIN_ARCHITECTURE.md` |
| 插件中心 vs 子图评估 | `docs/PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION.md` |
| 插件中心实现 | `core/brain_plugin_center.py` |
| 分析脑执行 | `domain/content/analyzer.py`（_run_analysis_plugins） |
| 生成脑执行 | `domain/content/generator.py`（generate） |
| 分析脑参考（实时） | `plugins/knowledge_base/plugin.py` |
| 分析脑参考（定时） | `plugins/methodology/plugin.py`、`plugins/bilibili_hotspot/plugin.py` |
| 生成脑参考 | `plugins/text_generator/plugin.py`、`plugins/campaign_plan_generator/plugin.py` |
