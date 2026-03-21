# 插件开发说明

插件开发仅需**两处**：开发插件逻辑 + 注册插件。数据库、定时任务、缓存、记忆等均通过 **config 参数化注入**，插件内禁止直接 `import database`、`import apscheduler` 等。

---

## 一、脑级插件（分析脑 / 生成脑）

适用于：分析脑扩展（热点、诊断、内容方向等）、生成脑扩展（文案、图片、视频等）。

### 两步流程

1. **开发插件**  
   复制 `plugins/capabilities/brain_plugin_template.py` 到 `plugins/你的插件名/plugin.py`，实现：
   - `register(plugin_center: BrainPluginCenter, config: dict) -> None`
   - 在 `register` 内从 **config** 获取依赖，实现 `get_output(name, context)`（及可选 `refresh_func`），最后调用 `plugin_center.register_plugin(...)`。

2. **注册插件**  
   在 `core/brain_plugin_center.py` 的 `ANALYSIS_BRAIN_PLUGINS` 或 `GENERATION_BRAIN_PLUGINS` 中添加一行：
   ```python
   ("plugins.你的插件名.plugin", "register"),
   ```

### 参数化依赖（仅从 config 获取）

| config 键名           | 说明                 |
|-----------------------|----------------------|
| ai_service            | AI 服务              |
| cache / smart_cache   | 缓存                 |
| memory_service        | 记忆服务             |
| db_session_factory    | 数据库会话工厂，需写 DB 时：`async with config["db_session_factory"]() as session` |
| plugin_bus            | 事件总线（发布 DiagnosisCompletedEvent、WebSearchEvent 等） | `config.get("plugin_bus") or get_plugin_bus()` |
| 定时任务              | 不直接使用 scheduler | 将刷新逻辑写成 `async def refresh(): ...`，通过 `register_plugin(..., refresh_func=refresh, schedule_config={"interval_hours": 6})` 注册，由插件中心统一调度 |

应用启动时会在 `SimpleAIService` 中构建上述 config 并传给各插件的 `register`，插件内**禁止**直接导入 `database`、`apscheduler`。

### 模板位置

- `plugins/capabilities/brain_plugin_template.py`：脑级插件模板与说明。

---

## 二、工作流类插件（LangGraph 子图）

适用于：可被 meta_workflow 按 `step_name` 调用的子工作流（如自定义多步编排）。

### 两步流程

1. **开发插件**  
   复制 `plugin_template/` 为你的插件目录，在 `workflow.py` 中实现 `build_workflow(config)`，从 **config** 获取 ai_service、memory_service、cache 等，返回 LangGraph `CompiledGraph`。

2. **注册插件**  
   在应用启动处（如 lifespan）调用：
   - `get_registry().register_workflow("step_name", your_build_workflow)`
   - `init_plugins(config)`（config 含 ai_service、memory_service、cache 等）。

### 参数化依赖

仅通过 `config` 获取 ai_service、memory_service、cache；禁止在插件内 `from database import ...`。

### 模板位置

- `plugin_template/README.md`、`plugin_template/workflow.py`
- `plugin_template/example_plugin/`：最小示例。

---

## 三、小结

| 类型       | 开发内容           | 注册位置                         |
|------------|--------------------|----------------------------------|
| 脑级插件   | `register` + `get_output`（+ 可选 `refresh_func`） | `core/brain_plugin_center.py` 的 ANALYSIS_BRAIN_PLUGINS / GENERATION_BRAIN_PLUGINS |
| 工作流插件 | `build_workflow(config)` 返回 CompiledGraph | `get_registry().register_workflow(...)` + `init_plugins(config)` |

所有依赖（数据库、缓存、记忆、定时任务）均通过 **config 或 register 参数**注入，插件内不直接引用 database、scheduler。
