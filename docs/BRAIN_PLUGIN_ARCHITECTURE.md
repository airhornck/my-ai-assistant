# 脑级插件架构

## 定位

插件是对「脑」的**能力补充**，而非编排层的扩展。每个脑拥有统一的插件管理中心，插件只注册在所属脑中。

## 插件类型

| 类型 | 说明 | 示例 |
|------|------|------|
| **定时插件** (scheduled) | 周期刷新，结果缓存，调用时读缓存；每插件单独配置 `schedule_config` | B站热点榜单 |
| **实时插件** (realtime) | 按需执行，每次调用都运行 | 竞品分析 |
| **工作流插件** (workflow) | 多步骤工作流 | （未来扩展） |
| **技能插件** (skill) | 单一能力/工具，通常为实时 | （未来扩展） |

## 已注册插件清单

插件在 `core/brain_plugin_center.py` 中声明，各脑对应清单：

- **ANALYSIS_BRAIN_PLUGINS**：分析脑
  - `plugins.bilibili_hotspot.plugin`

## 分析脑插件中心

- 位置：`ContentAnalyzer.plugin_center`
- 初始化：`SimpleAIService` 创建 `BrainPluginCenter("analysis", config)` 并注入
- 定时任务：插件中心统一调度，启动时刷新 + 按间隔刷新

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
