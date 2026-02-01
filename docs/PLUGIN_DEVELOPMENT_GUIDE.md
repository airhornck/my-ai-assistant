# 插件开发指南

面向同事：如何扩展分析脑、生成脑及编排层工作流。

## 一、架构总览

```
策略脑（planning_node）
    ↓ 规划步骤（plan）
编排层（orchestration_node）
    ├─ 内置步骤：web_search | memory_query | analyze | generate | evaluate
    └─ 自定义步骤：从 PluginRegistry 按 step_name 获取并执行
```

- **分析脑**：`domain/content/analyzer.py` + 扩展分析模块（可注册为编排步骤）
- **生成脑**：`domain/content/generator.py` + `domain/content/generators/`（text/image/video）
- **编排插件**：注册到 `PluginRegistry`，策略脑规划时写 `step: "your_plugin_name"` 即可被调用

---

## 二、编排层插件（新增步骤）

### 2.1 适用场景

- 热点榜单、竞品分析、行业知识库等分析类步骤
- 或任意可在「思维链」中插入的自定义步骤

### 2.2 开发步骤

1. **复制模板**：`cp -r plugin_template/example_plugin plugins/my_hotspot_ranking`（`plugins/` 为插件根目录）
2. **实现 `build_workflow(config)`**：在 `workflow.py` 中实现逻辑，从 config 获取 `ai_service`、`memory_service`
3. **注册**：在 `main.py` lifespan 中（或插件加载逻辑中）：
   ```python
   from plugins.my_hotspot_ranking.workflow import build_workflow
   registry.register_workflow("hotspot_ranking", build_workflow)
   ```
4. **策略脑规划**：在 `workflows/meta_workflow.py` 的 planning 提示中已说明可用自定义步骤；或在后续迭代中让 LLM 知晓「hotspot_ranking」等名称，规划时即可加入该步骤

### 2.3 State 约定

插件接收的 `state` 与返回的 `state` 必须与 `MetaState` 兼容：

| 字段 | 类型 | 说明 |
|------|------|------|
| user_input | str | JSON 字符串，含 brand_name、product_desc、topic、raw_query 等 |
| analysis | str/dict | 分析结果，可由插件读取或更新 |
| content | str | 生成内容，可由插件读取或更新 |
| session_id | str | 会话 ID |
| user_id | str | 用户 ID |
| evaluation | dict | 评估结果 |
| need_revision | bool | 是否需修订 |
| stage_durations | dict | 各阶段耗时 |
| analyze_cache_hit | bool | 分析缓存命中 |
| used_tags | list | 使用的标签 |

**返回**：使用增量更新 `return {**state, "analysis": new_analysis, ...}`，勿缺失上述字段。

### 2.4 示例（分析类插件）

```python
# plugins/hotspot_ranking/workflow.py
async def _hotspot_node(state: dict) -> dict:
    data = json.loads(state.get("user_input") or "{}")
    brand = data.get("brand_name", "")
    topic = data.get("topic", "")
    # 调用 ai_svc 或外部 API 获取热点
    result = await ai_svc.router.route("analysis", "medium").ainvoke(...)
    # 更新 analysis，供后续 generate 使用
    existing = state.get("analysis") or {}
    if isinstance(existing, dict):
        existing["hotspot_data"] = result
    return {**state, "analysis": existing}
```

---

## 三、分析脑扩展

### 3.1 方式 A：扩展现有 ContentAnalyzer

在 `domain/content/analyzer.py` 中增加新的分析方法，例如：

```python
async def analyze_hotspot(self, request: ContentRequest, ...) -> dict[str, Any]:
    """热点榜单分析。"""
```

然后在 `services/ai_service.py` 中暴露新方法，供编排或插件调用。

### 3.2 方式 B：独立分析插件（推荐）

将热点榜单、竞品分析等做成编排层插件（见第二节），策略脑规划时加入 `{"step": "hotspot_ranking", ...}`。插件内可调用 `ai_svc.analyze()` 或自定义 LLM 调用。

### 3.3 配置入口

分析相关模型配置在 `config/api_config.py` 的 `analysis` 接口，可新增专用接口（如 `analysis_hotspot`）并在插件中使用 `get_model_config("analysis_hotspot")`。

---

## 四、生成脑扩展

### 4.1 新增输出类型（如图片、视频）

1. **在 `domain/content/generators/` 下新增**：如 `banner_generator.py`
2. **在 `config/api_config.py` 的 LLM_INTERFACES 中新增**：如 `generation_banner`
3. **在 `domain/content/generator.py` 中**：增加 `OUTPUT_TYPE_BANNER`，并在 `generate()` 中路由到新模块

### 4.2 新增文本风格（如小红书、B 站）

在 `config/media_specs.py` 的 `MEDIA_SPECS` 中新增 `MediaSpec`，`resolve_media_spec()` 会根据 `topic`、`raw_query` 自动匹配。

### 4.3 生成器模块模板

```python
# domain/content/generators/banner_generator.py
from config.api_config import get_model_config

class BannerGenerator:
    def __init__(self, config: dict | None = None):
        cfg = config or get_model_config("generation_image")  # 或专用接口
        # 初始化客户端...

    async def generate(self, prompt: str = "", analysis: dict = None, ...) -> str:
        # 返回图片 URL 或 base64
        pass
```

---

## 五、注册与配置

### 5.1 插件注册位置

`main.py` 的 `lifespan` 中，在 `registry.init_plugins(...)` 之前：

```python
from plugins.my_plugin.workflow import build_workflow
registry.register_workflow("my_step_name", build_workflow)
registry.init_plugins({"ai_service": ai_service, "memory_service": memory_svc})
```

### 5.2 策略脑规划扩展

若希望策略脑自动规划新步骤，需在 `workflows/meta_workflow.py` 的 `planning_node` 的 system_prompt 中补充说明，例如：

```
- hotspot_ranking: 热点榜单分析（需先注册插件）
- competitor_analysis: 竞品分析（需先注册插件）
```

---

## 六、测试与调试

1. **单测**：在 `scripts/` 或 `tests/` 中编写用例，mock `ai_service`、`memory_service`
2. **集成**：启动应用后，通过前端或 `/api/v1/frontend/chat` 发送会触发策略脑规划的请求，观察日志中是否有 `已执行插件步骤: xxx`
3. **日志**：`logger.info("编排层执行步骤 %d/%d: %s", ...)` 会输出步骤名

---

## 七、参考文件

| 类型 | 路径 |
|------|------|
| 插件模板 | `plugin_template/example_plugin/` |
| 编排逻辑 | `workflows/meta_workflow.py`（orchestration_node） |
| 插件注册 | `core/plugin_registry.py`、`main.py` lifespan |
| 分析脑 | `domain/content/analyzer.py`、`services/ai_service.py` |
| 生成脑 | `domain/content/generator.py`、`domain/content/generators/` |
| 接口配置 | `config/api_config.py` |
