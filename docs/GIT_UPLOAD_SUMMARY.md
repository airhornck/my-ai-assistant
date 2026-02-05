# Git 上传前总结

> 用于提交前快速确认：架构、语法、连通性、可用性。详细报告见 [PROJECT_CHECK_REPORT.md](./PROJECT_CHECK_REPORT.md)。  
> **近期更新（昨日/今日）** 见 [CHANGELOG_2025-02-02.md](./CHANGELOG_2025-02-02.md)。

## 一、检查结论

| 项 | 结果 |
|----|------|
| **语法** | ✅ `python scripts/check_syntax.py` 通过 |
| **main 导入** | ✅ 无循环依赖 |
| **路由** | ✅ 无重复 |
| **架构** | ✅ 规划脑 → 编排层（router + 子图）→ 分析脑/生成脑子图 + 插件中心 |
| **模块连通** | ✅ main → workflows → services → domain → core → config；plugins 经 BrainPluginCenter 加载 |
| **可用性** | ✅ 需 PostgreSQL、Redis、.env；入口 /api/v1/frontend/chat、/api/v1/chat/resume、/api/v1/analyze-deep/raw |

## 二、当前架构要点

- **主图**：planning → router → parallel_retrieval | analyze（子图）| generate（子图）| evaluate | human_decision | compilation；Checkpointer=MemorySaver。
- **流式**：`POST /api/v1/frontend/chat?stream=true` → SSE 推送每步 state。
- **人工介入**：evaluate 后 need_revision → interrupt → `POST /api/v1/chat/resume` 传 human_decision。
- **多轮**：config `thread_id=session_id`，状态按会话持久化。
- **插件**：分析脑/生成脑内为插件中心模式，规划脑只输出步骤 + analysis_plugins / generation_plugins。

## 三、建议提交信息（示例）

**本次（2025-02-02）可拆为两条或合并为一条：**

```
fix(frontend): 流式与闲聊兼容 + 真实流式展示

- 修复 _stream_send 未定义；闲聊+stream 识别 JSON 并规范化，避免「流式响应无有效数据」
- 流式时按 SSE 逐条 yield 更新界面；无 content 时展示「思考中…」+ 步骤
- 后端 SSE 增加 keepalive、Connection: keep-alive

feat(thinking_narrative): 思维链叙述改用 qwen-turbo 并恢复默认 LLM 叙述

- 新增 config.thinking_narrative（默认 qwen-turbo）；compilation 增加叙述耗时日志
- 文档：PERFORMANCE_OPTIMIZATION、ENV_KEYS_REFERENCE、CHANGELOG_2025-02-02
```

**历史（LangGraph 多脑协同）：**

```
feat: LangGraph 多脑协同 + 流式/人工介入/多轮

- 元工作流：planning → router → 并行检索/分析子图/生成子图/评估/人工决策/汇总，MemorySaver
- 分析脑、生成脑以子图接入；脑内插件保持插件中心模式
- 流式：frontend/chat?stream=true，SSE 推送 state
- 人工介入：interrupt + /api/v1/chat/resume
- 多轮：thread_id=session_id 持久化
```

## 四、提交前自检命令

```bash
python scripts/check_syntax.py
python check_backend.py   # 需已启动 PostgreSQL、Redis 并配置 .env
```
