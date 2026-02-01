# 插件模板 (plugin_template)

用于创建可被元工作流（meta_workflow）编排层按 `step_name` 动态调用的子工作流插件。  
适用于：分析脑扩展（热点榜单、竞品分析等）、生成脑辅助步骤，或任意可插入思维链的自定义步骤。

## 插件功能

- 提供 **`build_workflow(config)`**：接收配置字典，返回符合 LangGraph 的 **CompiledGraph**（支持 `.ainvoke(state)`）。
- 输入/输出 **state** 必须与 `workflows/types.MetaState` 兼容，以便编排层正确合并结果。

## 输入 State 格式（编排传入的 sub_state）

由 meta_workflow 的 orchestration_node 传入，包含以下字段（与 State 一致）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_input` | string | 用户输入（常为 JSON 字符串，含 brand_name、product_desc、topic 等） |
| `analysis` | string / dict | 分析结果 |
| `content` | string | 当前内容 |
| `session_id` | string | 会话 ID |
| `user_id` | string | 用户 ID |
| `evaluation` | object | 评估结果 |
| `need_revision` | boolean | 是否需要修订 |
| `stage_durations` | object | 各阶段耗时（秒） |
| `analyze_cache_hit` | boolean | 分析阶段是否命中缓存 |
| `used_tags` | array | 本次使用的标签列表 |

## 输出 State 格式（节点返回值）

节点必须返回**至少包含上述字段**的字典，推荐使用增量更新：

```python
return {
    **state,
    "content": new_content,   # 你更新的字段
    "analysis": state.get("analysis", ""),
    "evaluation": state.get("evaluation", {}),
    # ... 其余保持或按需更新
}
```

缺失字段可能导致元工作流合并时丢失数据。

## 如何访问共享服务

- **config** 由应用启动时 `init_plugins(config)` 传入，通常包含：
  - **`config["ai_service"]`**：`SimpleAIService` 实例（带缓存），用于调用 `analyze()`、`generate()` 等。
  - **`config.get("memory_service")`**：可选 `MemoryService` 实例；若未传入，可在插件内 `MemoryService()` 自建。

在 `build_workflow(config)` 内取出服务并闭包到节点中，例如：

```python
ai_svc = config.get("ai_service") or SimpleAIService()
memory_svc = config.get("memory_service") or MemoryService()
```

## 配置 JSON Schema

见 **config.schema.json**，用于校验或文档化插件可接受的 config 结构。

## 使用步骤

1. 复制本目录并重命名为你的插件名（如 `my_plugin`）。
2. 在 `workflow.py` 中实现真实节点逻辑，从 `config` 获取 `ai_service` / `memory_service`。
3. 在应用启动处注册（如 main.py lifespan 或插件发现逻辑）：
   - `get_registry().register_workflow("your_step_name", your_build_workflow)`
   - 与主流程一起执行 `init_plugins(config)`。
4. 若在 meta_workflow 编排中使用：策略脑规划的 `plan` 中 `step` 与注册的 `name` 一致时，编排层将自动获取并执行该插件。

## 示例

参见 **example_plugin/** 目录，展示了一个使用 MemoryService、AIService 并遵守 State 约定的简单插件。

## 更多说明

详见 **docs/PLUGIN_DEVELOPMENT_GUIDE.md**（分析脑、生成脑扩展及编排插件完整指南）。
