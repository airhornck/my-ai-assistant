# 插件模板 (plugin_template)

用于创建可被元工作流（meta_workflow）编排层按 `step_name` 动态调用的**工作流类**插件（LangGraph 子图）。  
与**脑级插件**（分析脑/生成脑）不同：脑级插件仅需「开发 + 在 brain_plugin_center 注册」两步，见 `plugins/capabilities/brain_plugin_template.py`。

---

## 开发流程（两处即可）

1. **开发插件**：复制本目录为你的插件名，在 `workflow.py` 中实现 `build_workflow(config)`，从 **config 参数化获取**所有依赖。
2. **注册插件**：在应用启动处 `get_registry().register_workflow("step_name", build_workflow)`，并执行 `init_plugins(config)`。

**禁止在插件内**直接 `from database import ...`、`import apscheduler` 等；数据库、缓存、记忆、定时任务均通过 **config 注入**。

## 参数化依赖（仅通过 config 获取）

| config 键名        | 说明           |
|--------------------|----------------|
| ai_service         | AI 服务        |
| memory_service     | 记忆服务       |
| cache              | 缓存           |

在 `build_workflow(config)` 内取用并闭包到节点中，例如：

```python
ai_svc = config.get("ai_service") or SimpleAIService()
memory_svc = config.get("memory_service") or MemoryService()
```

## 插件约定

- **`build_workflow(config)`**：返回 LangGraph `CompiledGraph`，支持 `.ainvoke(state)`。
- **State**：入参/出参与 `workflows/types.MetaState` 兼容，节点返回增量更新 `return { **state, "content": new_content, ... }`。

## 输入/输出 State 字段

编排传入的 state 含：`user_input`、`analysis`、`content`、`session_id`、`user_id`、`evaluation`、`need_revision`、`stage_durations`、`analyze_cache_hit`、`used_tags`。节点返回值需包含上述字段，避免合并时丢失。

## 示例

参见 **example_plugin/**，展示从 config 获取 ai_service、memory_service 并遵守 State 约定的最小示例。

## 配置与更多说明

- **config.schema.json**：config 结构校验/文档。
- 脑级插件（分析脑/生成脑）：见 `plugins/capabilities/brain_plugin_template.py` 与 `core/brain_plugin_center.py`。
