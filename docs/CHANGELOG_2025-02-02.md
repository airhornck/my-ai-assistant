# 近期更新记录（2025-02-01 / 2025-02-02）

> Git 上传前整理：昨日与今日的变更汇总。

---

## 一、昨日（2025-02-01）相关

- **插件中心 vs 子图评估**：结论为保持插件中心模式，文档见 `PLUGIN_CENTER_VS_SUBGRAPH_EVALUATION.md`。
- **插件开发指南**：`PLUGIN_DEVELOPMENT_GUIDE.md` 更新为以脑级插件中心为主扩展方式，修正模板引用与分析/生成插件模板说明。
- **脑插件架构**：`BRAIN_PLUGIN_ARCHITECTURE.md` 补充「插件应保持在插件中心模式」的说明。

---

## 二、今日（2025-02-02）变更

### 2.1 前端（`frontend/app_enhanced.py`）

| 变更 | 说明 |
|------|------|
| 修复未定义 `_stream_send` | 发送逻辑改为统一走 `send_message_with_stream_option`，流式/非流式均单次返回或通过生成器 yield，去掉对不存在的 `_stream_send` 的调用。 |
| 闲聊 + 流式报错「流式响应无有效数据」 | 后端闲聊返回 JSON 而非 SSE。新增 `_normalize_backend_data`，`_request_stream_and_collect` 根据 `Content-Type` 区分：`application/json` 时解析 JSON 并规范化 `response`→`content`、`thinking_process`→`thinking_logs`；`text/event-stream` 时仍按 SSE 消费。 |
| 真实流式输出 | 新增 `_stream_send_generator`：流式时对每条 SSE 或单次 JSON 结果 yield 一次，界面按节点/结果逐步更新；发送事件恢复 `demo.queue()` 与 `queue=True`。 |
| 无正文时展示进度 | 收到 state 但 `content` 为空时，展示「思考中…」+ 当前步骤名（来自 `thinking_logs`），避免长时间无反馈。 |

### 2.2 后端

| 文件 | 变更 |
|------|------|
| **main.py** | 流式 SSE：每条 state 前先发 `: keepalive\n`，并加 `Connection: keep-alive`，促使代理/客户端尽早刷新，避免长时间一次性才收到。 |
| **workflows/meta_workflow.py** | ① 恢复默认使用 LLM 思维链叙述：`USE_SIMPLE_THINKING_NARRATIVE` 默认为 `0`，仅当设为 `1`/`true`/`yes` 时才用步骤拼接。② 思维链叙述步骤增加耗时日志：`思维链叙述(thinking_narrative) 耗时 X.XXs`。 |
| **workflows/thinking_narrative.py** | 思维链叙述改为使用独立接口 `thinking_narrative`（默认 qwen-turbo）：从 `config.api_config.get_model_config("thinking_narrative")` 创建 `ChatOpenAI` 并 `ainvoke`，不再使用传入的 `llm_client`；保留 `llm_client` 参数以兼容调用方。 |
| **config/api_config.py** | 新增 LLM 接口 `thinking_narrative`：默认 `qwen-turbo`，可覆盖 `MODEL_THINKING_NARRATIVE`、`MODEL_THINKING_NARRATIVE_PROVIDER` 等。 |

### 2.3 文档

| 文件 | 变更 |
|------|------|
| **docs/PERFORMANCE_OPTIMIZATION.md** | ① 与通义/豆包/DeepSeek 的差距与优化方向。② 思维链叙述使用 qwen-turbo、可选简单叙述、流式 SSE 说明。③ 新增「思维链叙述：qwen-turbo vs qwen-max 对比」及如何通过日志对比耗时。 |
| **docs/ENV_KEYS_REFERENCE.md** | ① LLM 用途列表增加 `thinking_narrative`。② 性能与体验一节：更新 `USE_SIMPLE_THINKING_NARRATIVE` 默认说明，新增 `MODEL_THINKING_NARRATIVE`、`MODEL_THINKING_NARRATIVE_PROVIDER`。 |

---

## 三、涉及文件清单（今日可提交）

```
config/api_config.py
frontend/app_enhanced.py
main.py
workflows/meta_workflow.py
workflows/thinking_narrative.py
docs/ENV_KEYS_REFERENCE.md
docs/PERFORMANCE_OPTIMIZATION.md
docs/CHANGELOG_2025-02-02.md   # 本文件
docs/GIT_UPLOAD_SUMMARY.md     # 已更新
```

---

## 四、建议提交信息（示例）

```
fix(frontend): 流式与闲聊兼容 + 真实流式展示

- 修复 _stream_send 未定义，统一走 send_message_with_stream_option / _stream_send_generator
- 闲聊+stream 时识别 JSON 响应并规范化字段，避免「流式响应无有效数据」
- 流式时按 SSE 逐条 yield 更新界面，无 content 时展示「思考中…」+ 步骤名
- 后端 SSE 增加 keepalive 与 Connection: keep-alive，便于尽早刷新

feat(thinking_narrative): 思维链叙述改用 qwen-turbo 并恢复默认 LLM 叙述

- 新增 config.thinking_narrative 接口，默认 qwen-turbo
- thinking_narrative 模块使用该接口，不再复用策略脑 llm_client
- 默认恢复 LLM 思维链叙述；USE_SIMPLE_THINKING_NARRATIVE=1 可改为步骤拼接
- compilation_node 增加思维链叙述耗时日志，便于与 qwen-max 对比

docs: 性能对比与 env 说明更新

- PERFORMANCE_OPTIMIZATION：通义/豆包/DeepSeek 对比、qwen-turbo vs qwen-max
- ENV_KEYS_REFERENCE：thinking_narrative、MODEL_THINKING_NARRATIVE
- CHANGELOG_2025-02-02、GIT_UPLOAD_SUMMARY 更新
```

---

## 五、提交前自检

```bash
python scripts/check_syntax.py
# 可选：python check_backend.py（需 PostgreSQL、Redis、.env）
```
