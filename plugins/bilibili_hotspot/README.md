# B站热点榜单插件

## 归属

**分析脑** 的 **定时插件**。插件只注册在分析脑的插件中心。

## 功能

策略调用时**只读** Redis 中的预生成报告，无网络/LLM 调用，响应极快。
报告由分析脑插件中心的定时任务刷新，聚焦：热点 IP 打造、内容结构与创作风格。

## 执行流程

1. **定时任务**（分析脑插件中心管理）：应用启动 + 每 6 小时执行 `refresh_bilibili_hotspot_report()` → 写入 Redis
2. **策略调用**：通过分析脑插件中心 `get_output("bilibili_hotspot", context)` 只读缓存；未命中则返回静态兜底

## 手动刷新

```bash
python scripts/refresh_bilibili_hotspot.py
```

## 触发条件

策略脑在规划时，当用户**明确指定 B站/小破站/bilibili 平台**生成文案时，会在 analyze 之前加入 `bilibili_hotspot` 步骤。
