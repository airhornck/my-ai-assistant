# 示例插件 (example_plugin)

基于 **plugin_template** 的简单示例：展示如何从 config 获取 MemoryService、AIService，并遵守 State/MetaState 数据格式约定。

## 插件功能

- 从 `config` 读取共享的 `ai_service` 与可选的 `memory_service`。
- 解析 `state["user_input"]` 中的 brand_name、product_desc、topic。
- 调用 `memory_svc.get_memory_for_analyze(...)` 获取用户记忆。
- 调用 `ai_svc.client.ainvoke(messages)` 生成一句简短小结。
- 返回与 **State** 兼容的增量 state（含 content、used_tags、stage_durations 等）。

## 输入 / 输出 State

- **输入**：与 `workflows/basic_workflow.State` 一致，由 meta_workflow 编排传入（含 user_input、user_id、session_id 等）。
- **输出**：节点返回 `{ **state, "content": new_content, "used_tags": effective_tags, "stage_durations": {...}, ... }`，保证所有 State 约定字段存在。

## 如何注册

在 main.py lifespan 或插件发现逻辑中：

```python
from core.plugin_registry import get_registry
from plugin_template.example_plugin.workflow import build_workflow

registry = get_registry()
registry.register_workflow("示例步骤", build_workflow)
# 随后与主流程一起执行 init_plugins({"ai_service": ai_service, "memory_service": memory_service})
```

若规划步骤名与注册名（如 "示例步骤"）一致，元工作流将按 step_name 动态拉取并执行本插件。
