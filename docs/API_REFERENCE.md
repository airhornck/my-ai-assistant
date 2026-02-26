# 对外 API 统一参考

本文档汇总所有对外 HTTP 接口，便于前端/第三方集成与统一管理。  
Lumina 四模块能力接口见「能力接口（Lumina 四模块）」一节。

---

## 一、约定

- **基础路径**：无统一前缀；部分接口为 `/api/v1/...`，数据与知识类为 `/api/v1/...`（与 router prefix 一致）。
- **认证**：当前未强制；生产环境建议在网关或中间件加鉴权。
- **错误**：业务错误通常返回 `{ "success": false, "error": "..." }`，HTTP 状态码 4xx/5xx；校验失败为 422。

---

## 二、接口清单

### 2.1 根与健康

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务状态与端点列表 |
| GET | `/health` | 健康检查（数据库、Redis、工作流） |
| GET | `/docs` | Swagger UI |
| GET | `/metrics` | Prometheus 指标 |

### 2.2 内容与分析

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/create` | 创建内容（品牌/产品/话题等） |
| POST | `/api/v1/analyze-deep` | 深度分析（元工作流，含规划与报告） |
| POST | `/api/v1/analyze-deep/raw` | 深度分析（原始输入 → 意图识别 → 元工作流） |

### 2.3 会话与前端

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/new` | 新建对话（新 session_id / thread_id） |
| GET | `/api/v1/frontend/session/init` | 前端会话初始化（演示用 user_id + session） |
| POST | `/api/v1/frontend/chat` | 前端聊天统一入口（意图路由：闲聊/创作） |
| POST | `/api/v1/chat/resume` | 人工介入后从断点恢复 |
| GET | `/api/v1/session/{session_id}` | 查询会话状态（含 thread_id 等） |

### 2.4 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/documents/upload` | 上传文档（绑定到会话，每会话最多 5 个） |
| GET | `/api/v1/documents` | 列出文档（按 session_id 或 user_id） |

### 2.5 反馈与报告

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/feedback` | 提交反馈（评分、评论，高分会触发画像优化） |
| GET | `/api/v1/reports/{filename}` | 下载生成的 Word 报告 |

### 2.6 数据与知识（data_and_knowledge 路由，前缀 `/api/v1`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/data/feedback` | 数据闭环：用户反馈事件 |
| POST | `/api/v1/data/platform-metrics` | 数据闭环：平台回流批量 |
| GET | `/api/v1/cases` | 案例模板列表（行业/目标/标签筛选、分页） |
| GET | `/api/v1/cases/{case_id}` | 案例详情 |
| POST | `/api/v1/cases/from-session` | 将会话生成结果沉淀为案例 |
| POST | `/api/v1/cases` | 创建案例模板 |
| POST | `/api/v1/cases/{case_id}/scores` | 案例打分 |
| PUT | `/api/v1/cases/{case_id}` | 更新案例 |
| DELETE | `/api/v1/cases/{case_id}` | 删除案例 |
| GET | `/api/v1/methodology` | 方法论文档列表 |
| GET | `/api/v1/methodology/doc` | 读取方法论文档（query: path） |
| PUT | `/api/v1/methodology/doc` | 创建/更新方法论文档 |
| DELETE | `/api/v1/methodology/doc` | 删除方法论文档（query: path） |

---

## 三、能力接口（Lumina 四模块）

以下为统一能力路由提供的四个模块接口，对应 [Lumina 产品](https://lumina-ai.cn/product) 的四大核心能力。  
实现上会调用分析脑插件或聚合逻辑，详见 `docs/LUMINA_MODULES_MAPPING.md`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/capabilities/content-direction-ranking` | **已过滤的内容方向榜单**：适配度、热度、风险、角度建议、标题模板（可选 user_id / session_id 做画像） |
| GET | `/api/v1/capabilities/case-library` | **定位决策案例库**：案例列表与详情，支持行业/阶段等筛选（与 `/api/v1/cases` 能力对齐，可扩展前后对比、决策规则字段） |
| GET | `/api/v1/capabilities/content-positioning-matrix` | **内容定位矩阵**：3x4 矩阵（优先级×阶段），每格含边界、建议、示例（可选 user_id 做人设匹配） |
| GET | `/api/v1/capabilities/weekly-decision-snapshot` | **每周决策快照**：当前阶段、最大风险、优先级建议、禁区、历史快照列表（可选 user_id） |

- **请求**：以上 GET 接口支持 query 参数（如 `user_id`、`session_id`、`platform`、`page`、`page_size` 等），具体以实现为准。
- **响应**：统一为 JSON；列表类含 `items` 或 `data`，单资源为对象；错误时 `success: false` + `error`。

---

## 四、错误码与响应格式

- **200**：成功。
- **400**：参数错误（如缺少必填、业务校验失败）。
- **404**：资源不存在。
- **422**：请求体验证失败（如 Pydantic 校验）。
- **500**：服务器内部错误（不暴露细节）。
- **504**：网关超时（如 analyze-deep / 恢复执行超时）。

通用错误体示例：

```json
{
  "success": false,
  "error": "错误说明",
  "stage": "可选，阶段标识",
  "details": "可选，校验详情"
}
```

---

## 五、与分析脑插件的关系

- 深度分析、前端聊天等会按任务类型调用分析脑插件（见 `core/task_plugin_registry.py`、`docs/ANALYSIS_PLUGINS_SPEC.md`）。
- 能力接口中的「内容方向榜单」「案例库」「内容定位矩阵」「每周决策快照」分别对应或聚合：选题/热点、案例库、内容定位、每周快照（含账号诊断/风险等），插件映射见 `docs/LUMINA_MODULES_MAPPING.md`。

---

## 六、验证四模块能力接口

1. **前置**：配置 `REDIS_URL`、`DATABASE_URL`，可选 `DASHSCOPE_API_KEY`（用于内容方向榜单、每周决策快照的 AI 输出）。
2. **启动服务**：`uvicorn main:app --reload --port 8000`
3. **运行验证脚本**：
   - 完整验证（含调用 AI 的接口）：`python scripts/verify_capability_apis.py`
   - 仅验证案例库与内容定位矩阵（不调 AI）：`SKIP_SLOW=1 python scripts/verify_capability_apis.py`
4. **预期**：四个接口均返回 `success: true`，且：
   - 内容方向榜单：`data.items` 为数组，首条含 `title_suggestion`/`adaptation_score`/`angles` 等；
   - 案例库：`data` 含 `items` 或 `list`；
   - 内容定位矩阵：`data.matrix` 长度为 12（3×4），每格含 `priority`、`stage`、`boundary`、`suggestion`、`example`；
   - 每周决策快照：`data` 含 `stage`、`max_risk`、`priorities`、`forbidden`、`weekly_focus`、`history`。
5. **pytest**（需集成环境）：`pytest scripts/test_capability_apis.py -v -s`
