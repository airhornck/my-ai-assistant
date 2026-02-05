# 性能优化说明

## 0. 与通义/豆包/DeepSeek 的差距与优化方向

**行业参考（同类「推广文案」请求）**：
- **豆包**：平均首包约 95ms，流式处理优势明显，适合实时文案
- **通义千问**：首包约 110ms，token 速度 50–90 tokens/s（turbo 更快）
- **DeepSeek**：首包约 120ms，原生 v3 推理较慢（约 7.7 tokens/s）

**本系统现状**：创作链路为「规划 → 检索 → 分析 → 生成 → 评估 → 汇总」，多轮 LLM 串行，总耗时 70–80s 属预期范围；与「单次调用、流式首包」的直达 API 不可直接对比，但可通过以下手段缩短体感与总时长。

**已做/建议**：
1. **思维链叙述用 qwen-turbo**：汇总阶段思维链叙述使用独立接口 `thinking_narrative`（默认 **qwen-turbo**），相比此前用策略脑 qwen-max 可明显缩短该步耗时；日志见 `思维链叙述(thinking_narrative) 耗时 X.XXs`。
2. **流式 SSE**：后端每节点完成后立即发送 SSE（含 keepalive），前端按节点逐步展示「思考中…」与步骤，避免长时间无反馈。
3. **可选简单叙述**：设 `USE_SIMPLE_THINKING_NARRATIVE=1` 可关闭 LLM 叙述、改为步骤拼接，**节省约 10–25s**。
4. **后续可做**：生成阶段改为 token 级流式；规划/分析可考虑轻量模型或合并调用以进一步压缩时间。

### 思维链叙述：qwen-turbo vs qwen-max 对比

| 项目 | qwen-turbo（当前默认） | qwen-max（此前策略脑复用） |
|------|------------------------|-----------------------------|
| 定位 | 轻量、低延迟 | 能力更强、延迟更高 |
| 思维链叙述单步耗时 | 通常约 3–8s（视输入长度） | 通常约 10–25s |
| 如何对比 | 默认即 qwen-turbo，看日志 `思维链叙述(thinking_narrative) 耗时` | 临时设 `MODEL_THINKING_NARRATIVE=qwen-max`，同请求再跑一次，对比同一行日志 |

**建议**：保持 `thinking_narrative` 使用 qwen-turbo，在保证叙述可读性的前提下缩短汇总阶段耗时；若需更强叙述质量可临时改为 qwen-max 做 A/B 对比。

---

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
