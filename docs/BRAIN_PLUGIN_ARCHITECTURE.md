# 脑级插件架构

## 定位

插件是对「脑」的**能力补充**，而非编排层的扩展。每个脑拥有统一的插件管理中心，插件只注册在所属脑中。规划脑根据意图输出**步骤**（供前端思考过程展示）与**分析/生成插件列表**（供编排执行）；编排层调用分析脑/生成脑时传入对应插件列表，脑内按列表并行执行插件并合并结果。

## 插件类型

| 类型 | 说明 | 示例 |
|------|------|------|
| **定时插件** (scheduled) | 周期刷新，结果缓存，调用时读缓存；每插件单独配置 `schedule_config` | B站热点榜单 |
| **实时插件** (realtime) | 按需执行，每次调用都运行 | 竞品分析 |
| **工作流插件** (workflow) | 多步骤工作流 | （未来扩展） |
| **技能插件** (skill) | 单一能力/工具，通常为实时 | （未来扩展） |

## 已注册插件清单

插件在 `core/brain_plugin_center.py` 中声明，各脑对应清单。**规划脑只登记拼装后或无需拼装的插件**；拼装逻辑在插件中心内完成。

- **ANALYSIS_BRAIN_PLUGINS**：分析脑
  - `plugins.bilibili_hotspot.plugin`（无需拼装）
  - `plugins.methodology.plugin`、`plugins.case_library.plugin`、`plugins.knowledge_base.plugin`（供 campaign_context 调用）
  - `plugins.campaign_context.plugin`（拼装插件，规划脑登记此项即可）
- **GENERATION_BRAIN_PLUGINS**：生成脑（文本/图片/视频/PPT 等均以插件方式登记，模型由插件中心 config 管理）
  - `plugins.text_generator.plugin`、`plugins.campaign_plan_generator.plugin`
  - `plugins.image_generator.plugin`、`plugins.video_generator.plugin`（占位，待实现）

## 分析脑插件中心

- 位置：`ContentAnalyzer.plugin_center`
- 初始化：`SimpleAIService` 创建 `BrainPluginCenter("analysis", config)` 并注入
- 定时任务：插件中心统一调度，启动时刷新 + 按间隔刷新
- **按列表执行**：编排层调用 `ai_svc.analyze(..., analysis_plugins=[...])` 时，分析脑按 `analysis_plugins` 并行执行对应插件（单插件超时 5s），结果合并进 analysis；插件列表由规划脑从 plan 推导，见 `workflows/meta_workflow.py`、`docs/FINAL_IMPLEMENTATION_PLAN.md`

## B站热点榜单（分析脑定时插件）

- 归属：分析脑
- 类型：定时插件
- 注册：`plugins.bilibili_hotspot.plugin.register(plugin_center, config)`
- 刷新：由插件中心每 6 小时调用 `refresh_bilibili_hotspot_report`
- 调用：编排层通过 `ai_svc._analyzer.plugin_center.get_output("bilibili_hotspot", context)` 获取

## 新增插件流程

1. 创建插件模块，实现 `register(plugin_center, config)`
2. 在 `core/brain_plugin_center.py` 中对应脑的清单（如 `ANALYSIS_BRAIN_PLUGINS`）添加 `(模块路径, "register")`
3. 插件会在脑初始化时自动加载
4. 若需由规划脑按意图选用：在规划脑推导逻辑中把对应插件名加入 `analysis_plugins` / `generation_plugins`（当前由 plan 步骤推导，见 `meta_workflow.py` planning_node）

**新增插件与开发模板无需改为子图**：各脑内插件继续使用插件中心模式（注册 + `get_output`），无需在 LangGraph 中为每个插件建节点或子图。模板与流程保持不变；详见 [PLUGIN_DEVELOPMENT_GUIDE.md](./PLUGIN_DEVELOPMENT_GUIDE.md) 与 [PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION.md](./PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION.md)。

## 与独立模块的关系

插件可调用独立模块（数据闭环、知识库、营销方法论、案例模板），见 `docs/MODULE_ARCHITECTURE.md`、`docs/IP_PLUGIN_ARCHITECTURE_ANALYSIS.md`。
