# 项目 API 接口统计与对接说明

本文档汇总当前项目所有 HTTP 接口，便于外部系统对接。接口基础路径为 `/api/v1`（除根路径、健康检查、文档、静态资源外）。

**约定**：`BASE_URL` 为部署后的服务根地址（如 `https://your-host`），Swagger 文档为 `{BASE_URL}/docs`，ReDoc 为 `{BASE_URL}/redoc`。

---

## 一、概览表

| 分类       | 方法   | 路径 | 说明 |
|------------|--------|------|------|
| 系统       | GET    | `/` | 服务状态与端点列表 |
| 系统       | GET    | `/health` | 健康检查（DB/Redis/工作流/AI/缓存） |
| 系统       | GET    | `/metrics` | Prometheus 指标 |
| 内容       | POST   | `/api/v1/create` | 创建内容（结构化入参，走工作流） |
| 内容       | POST   | `/api/v1/analyze-deep` | 深度分析（元工作流，结构化入参） |
| 内容       | POST   | `/api/v1/analyze-deep/raw` | 深度分析（原始输入，意图识别后入元工作流） |
| 会话       | POST   | `/api/v1/chat/new` | 新建对话（返回 thread_id、session_id） |
| 会话       | POST   | `/api/v1/chat/resume` | 人工介入恢复（评估后 revise/skip） |
| 前端       | GET    | `/api/v1/frontend/session/init` | 前端会话初始化（返回 user_id、session_id） |
| 前端       | GET    | `/api/v1/frontend/user-context` | 按 user_id 查交互记录 |
| 前端       | POST   | `/api/v1/frontend/chat` | 前端聊天统一入口（意图路由） |
| 调试       | GET    | `/api/v1/debug/cache-reports` | 获取插件缓存报告内容 |
| 反馈       | POST   | `/api/v1/feedback` | 提交会话反馈（评分与评论） |
| 文档       | POST   | `/api/v1/documents/upload` | 上传文档并绑定会话 |
| 文档       | GET    | `/api/v1/documents` | 按 session_id 或 user_id 列文档 |
| 报告       | GET    | `/api/v1/reports/{filename}` | 下载 Word 报告文件 |
| 会话       | GET    | `/api/v1/session/{session_id}` | 获取会话详情（调试/记忆验证） |
| 记忆       | GET    | `/api/v1/memory` | 记忆列表/摘要（画像+记忆条+近期交互条数） |
| 记忆       | GET    | `/api/v1/memory/{memory_id}` | 单条记忆内容查看 |
| 记忆       | DELETE | `/api/v1/memory` | 清空当前用户所有记忆条 |
| 记忆       | DELETE | `/api/v1/memory/{memory_id}` | 删除单条记忆 |
| 数据闭环   | POST   | `/api/v1/data/feedback` | 数据闭环：用户反馈事件 |
| 数据闭环   | POST   | `/api/v1/data/platform-metrics` | 数据闭环：平台回流指标批量 |
| 案例       | GET    | `/api/v1/cases` | 案例列表（筛选、分页） |
| 案例       | GET    | `/api/v1/cases/{case_id}` | 案例详情 |
| 案例       | POST   | `/api/v1/cases` | 创建案例 |
| 案例       | POST   | `/api/v1/cases/from-session` | 将会话生成结果沉淀为案例 |
| 案例       | POST   | `/api/v1/cases/{case_id}/scores` | 为案例添加打分 |
| 案例       | PUT    | `/api/v1/cases/{case_id}` | 更新案例 |
| 案例       | DELETE | `/api/v1/cases/{case_id}` | 删除案例 |
| 方法论     | GET    | `/api/v1/methodology` | 方法论文档列表 |
| 方法论     | GET    | `/api/v1/methodology/doc` | 读取方法论文档（query: path） |
| 方法论     | PUT    | `/api/v1/methodology/doc` | 创建/更新方法论文档 |
| 方法论     | DELETE | `/api/v1/methodology/doc` | 删除方法论文档（query: path） |
| 能力       | GET    | `/api/v1/capabilities/content-direction-ranking` | 内容方向榜单 |
| 能力       | GET    | `/api/v1/capabilities/case-library` | 定位决策案例库 |
| 能力       | GET    | `/api/v1/capabilities/content-positioning-matrix` | 内容定位矩阵 |
| 能力       | GET    | `/api/v1/capabilities/weekly-decision-snapshot` | 每周决策快照 |

---

## 二、按模块说明

### 2.1 系统与运维

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/` | 服务状态与端点列表 | 无 | `{ "service", "status", "version", "endpoints": {...} }` |
| GET | `/health` | 健康检查 | 无 | `{ "status", "services": { "database", "redis", "workflow", "ai_service", "smart_cache" } }` |
| GET | `/metrics` | Prometheus 指标 | 无 | text/plain，Prometheus 格式 |

### 2.2 内容与创作

| 方法 | 路径 | 说明 | 请求体 | 响应/备注 |
|------|------|------|--------|-----------|
| POST | `/api/v1/create` | 创建内容（结构化） | `ContentRequest`: user_id, brand_name, product_desc, topic, tags? | 200: session_id, content, analysis, evaluation, used_tags, stage_durations 等；后端自动创建 session |
| POST | `/api/v1/analyze-deep` | 深度分析（结构化） | 同上 `ContentRequest` | 200: data(内容), thinking_process, content_sections, session_id；超时 300s；可能返回 200+__interrupt__ 需调 resume |
| POST | `/api/v1/analyze-deep/raw` | 深度分析（原始输入） | `RawAnalyzeRequest`: user_id, raw_input, session_id?, history?, tags? | 同上；意图识别后进元工作流；支持文档增强 |

### 2.3 会话与前端

| 方法 | 路径 | 说明 | 请求 | 响应/备注 |
|------|------|------|------|-----------|
| POST | `/api/v1/chat/new` | 新建对话 | `NewChatRequest`: user_id | 200: thread_id, session_id |
| POST | `/api/v1/chat/resume` | 评估后恢复 | `ChatResumeRequest`: session_id, human_decision(revise\|skip) | 200: response, thinking_process, status |
| GET | `/api/v1/frontend/session/init` | 前端会话初始化 | 无 | 200: user_id, session_id, thread_id（演示用生成 user_id） |
| GET | `/api/v1/frontend/user-context` | 用户交互记录 | Query: user_id, limit? (默认100) | 200: data[], count |
| POST | `/api/v1/frontend/chat` | 前端聊天统一入口 | `FrontendChatRequest`: message, session_id?, user_id；Query: stream? | 200: response, thinking_process 等；会话过期可返回 440 |

### 2.4 记忆（可查可看可删）

| 方法 | 路径 | 说明 | 请求 | 响应/备注 |
|------|------|------|------|-----------|
| GET | `/api/v1/memory` | 记忆列表/摘要 | Query: **user_id**（必填） | 200: profile_summary, memory_items\[{id, content_preview, source, created_at}\], recent_interaction_count |
| GET | `/api/v1/memory/{memory_id}` | 单条记忆完整内容 | Path: memory_id；Query: **user_id** | 200: id, user_id, content, source, created_at；归属校验失败 404 |
| DELETE | `/api/v1/memory` | 清空当前用户所有记忆条 | Query: **user_id** | 200: success, cleared；不删 UserProfile/InteractionHistory |
| DELETE | `/api/v1/memory/{memory_id}` | 删除单条记忆 | Path: memory_id；Query: **user_id** | 200: success, deleted；归属校验失败 404 |

### 2.5 反馈与文档

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/api/v1/feedback` | 提交反馈 | session_id, rating(1-5), comment? | 200: success, data |
| POST | `/api/v1/documents/upload` | 上传文档 | Form: file, user_id, session_id | 200: data(文档元信息)；每会话最多 5 个 |
| GET | `/api/v1/documents` | 列文档 | Query: session_id? 或 user_id? | 200: data[] |
| GET | `/api/v1/reports/{filename}` | 下载报告 | path: filename | 200: Word 文件；404 不存在 |

### 2.6 调试与会话查询

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/api/v1/debug/cache-reports` | 插件缓存报告 | Query: report_type?（空则返回类型列表） | 200: report_type, cache_key, report；类型: bilibili_hotspot, douyin_hotspot, xiaohongshu_hotspot, acfun_hotspot, case_library, methodology |
| GET | `/api/v1/session/{session_id}` | 会话详情 | path: session_id | 200: content, analysis, evaluation, tags 等；404 不存在 |

### 2.7 数据与知识（routers/data_and_knowledge，前缀 /api/v1）

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/api/v1/data/feedback` | 数据闭环-用户反馈 | session_id?, user_id?, rating?, comment?, payload? | 201: ok, id |
| POST | `/api/v1/data/platform-metrics` | 数据闭环-平台指标 | items: [{ metric_type, session_id?, user_id?, value?, dimensions? }] | 202: ok, count |
| GET | `/api/v1/cases` | 案例列表 | industry?, goal_type?, scenario_tag?, status?, order_by_score?, page?, page_size? | 列表+分页 |
| GET | `/api/v1/cases/{case_id}` | 案例详情 | path: case_id | 200 或 404 |
| POST | `/api/v1/cases` | 创建案例 | title, content, summary?, scenario_tags?, industry?, goal_type?, source_session_id?, status? | 201: ok, id |
| POST | `/api/v1/cases/from-session` | 会话沉淀为案例 | session_id, title, industry?, goal_type?, scenario_tags? | 201: ok, id |
| POST | `/api/v1/cases/{case_id}/scores` | 案例打分 | source(platform_reflow\|user_review\|system_auto), score_value, payload? | 201: ok |
| PUT | `/api/v1/cases/{case_id}` | 更新案例 | body: 部分字段 | 200: ok |
| DELETE | `/api/v1/cases/{case_id}` | 删除案例 | - | 200: ok 或 404 |
| GET | `/api/v1/methodology` | 方法论文档列表 | - | 200: items[] |
| GET | `/api/v1/methodology/doc` | 读方法论文档 | Query: path（相对 knowledge 路径） | 200: path, content 或 404 |
| PUT | `/api/v1/methodology/doc` | 写方法论文档 | path, content | 200: ok, path |
| DELETE | `/api/v1/methodology/doc` | 删方法论文档 | Query: path | 200: ok 或 404 |

### 2.8 能力接口（Lumina 四模块，routers/capability_api，前缀 /api/v1）

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| GET | `/api/v1/capabilities/content-direction-ranking` | 内容方向榜单 | Query: user_id?, platform?(xiaohongshu/douyin/bilibili/acfun) | 200: success, data.items, data.platform, source |
| GET | `/api/v1/capabilities/case-library` | 定位决策案例库 | Query: industry?, goal_type?, scenario_tag?, status?, order_by_score?, page?, page_size? | 200: success, data（与 /api/v1/cases 数据源一致） |
| GET | `/api/v1/capabilities/content-positioning-matrix` | 内容定位矩阵 | Query: user_id?, brand_name?, product_desc?, industry? | 200: success, data.matrix, data.persona, data.raw_directions |
| GET | `/api/v1/capabilities/weekly-decision-snapshot` | 每周决策快照 | Query: user_id? | 200: success, data（聚合 account_diagnosis、content_positioning 与快照） |

---

## 三、静态与文档

- **Swagger UI**：`GET {BASE_URL}/docs`
- **ReDoc**：`GET {BASE_URL}/redoc`
- **开放 API JSON**：由 FastAPI 自动提供（见 /docs 页链接）
- **报告静态目录**：`/data/reports` 挂载为静态文件（若配置）

---

## 四、对接建议

1. **认证**：当前接口未在文档中要求统一鉴权；生产环境建议在网关或应用层加 API Key / JWT。
2. **超时**：`/api/v1/analyze-deep`、`/api/v1/analyze-deep/raw`、`/api/v1/frontend/chat` 可能较长（如 300s），客户端需设置足够超时。
3. **会话**：创作类接口依赖 `session_id`（或由后端创建）；前端建议先调 `GET /api/v1/frontend/session/init` 或 `POST /api/v1/chat/new` 取得 session_id 再发聊天/分析请求。
4. **中断与恢复**：深度分析/前端聊天在评估节点可能返回 `__interrupt__`，需调用 `POST /api/v1/chat/resume` 传入 `human_decision`（revise | skip）继续。
5. **错误格式**：业务错误多为 `{ "success": false, "error": "...", "stage"?: "..." }`，HTTP 状态码 4xx/5xx。

---

## 五、统计汇总

| 分类 | 数量 |
|------|------|
| 系统/运维 | 3 |
| 内容与创作 | 3 |
| 会话与前端 | 5 |
| 反馈与文档 | 4 |
| 调试与会话 | 2 |
| 数据闭环 | 2 |
| 案例 CRUD + 沉淀 | 7 |
| 方法论 | 4 |
| 能力（Lumina 四模块） | 4 |
| **合计** | **34** |

*（若按「路径+方法」去重统计，则与上表一致；根路径、health、metrics 未计入 34。）*
