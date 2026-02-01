# 性能优化说明

## 1. B站热点榜单改为定时任务

**问题**：原先策略调用 B站热点插件时，每次都执行搜索 + LLM 分析，耗时长。

**方案**：
- 定时任务（应用启动 + 每 6 小时）执行 `refresh_bilibili_hotspot_report()` 写入 Redis
- 策略调用时插件只读 Redis 缓存，命中即返回；未命中返回静态兜底

**效果**：B站热点步骤从约 10–20 秒降至 < 100ms。

## 2. 编排层并行执行

**问题**：web_search、memory_query、bilibili_hotspot 无依赖却串行执行。

**方案**：将上述步骤改为 `asyncio.gather` 并行执行，再顺序执行 analyze、generate、evaluate。

**效果**：并行步骤总耗时约等于其中最慢的一个，显著缩短整体耗时。

## 3. 其他优化

- **web_search**：`num_results` 从 5 调整为 3，减少搜索耗时
- **SmartCache**：analyze、memory 已使用缓存，命中时跳过 LLM 调用

## 4. 手动刷新 B站热点

```bash
python scripts/refresh_bilibili_hotspot.py
```

可用于 cron 或启动前预热，确保首次请求即有缓存。
