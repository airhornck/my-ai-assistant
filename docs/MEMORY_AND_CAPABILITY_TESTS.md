# 记忆模块与四能力接口测试说明

## 一、记忆模块全面回归测试

### 1.1 覆盖范围

| 步骤 | 脚本 | 内容 |
|------|------|------|
| 步骤1 | `test_memory_optimization_step1.py` | UserMemoryItem 模型、表名/字段、create_tables、插入查询 |
| 步骤2 | `test_memory_optimization_step2.py` | memory_embedding 封装、get_embedding 可调用与返回值 |
| 步骤3 | `test_memory_optimization_step3.py` | MemoryService CRUD：list_memories、add_memory、get_memory_content、delete_memory、clear_memories |
| 步骤5 | `test_memory_optimization_step5.py` | get_memory_for_analyze 返回结构、token 预算 |
| 步骤7 | `test_memory_optimization_step7.py` | GET/DELETE 记忆 API：列表、单条内容、404、清空 |

### 1.2 运行方式

```bash
# 一键运行全部记忆回归（内部调用 pytest）
python scripts/run_memory_regression.py
```

**环境要求**：

- **REDIS_URL**、**DATABASE_URL** 已配置且可用时：步骤1/3/5/7 中依赖数据库的用例会执行；若数据库/Redis 未启动会报连接错误，其余用例仍会执行。
- 不配置上述变量时：仅运行不依赖 DB/Redis 的用例（如模型存在性、get_embedding、get_memory_for_analyze 结构、步骤7 的 TestClient API 调用）。

### 1.3 本次执行结果摘要

- **通过**：9 个用例（步骤1 模型与表结构、步骤2 全部、步骤5 全部、步骤7 的 3 个 API 测试）。
- **失败**：4 个用例，均为「数据库连接被拒绝」（本地未启动 PostgreSQL），属环境问题而非代码问题。
- 结论：记忆模块逻辑与 HTTP API 行为在现有环境下回归通过；需在具备可用 DATABASE_URL 的环境下再跑一遍以验证完整 CRUD 与 list_memories。

---

## 二、四能力接口全面测试与产出内容

### 2.1 四个能力接口

| 能力 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 内容方向榜单 | GET | `/api/v1/capabilities/content-direction-ranking` | 已过滤的内容方向（适配度/热度/风险/角度/标题）；可选 platform、user_id |
| 定位决策案例库 | GET | `/api/v1/capabilities/case-library` | 案例列表，与 /api/v1/cases 数据源一致；支持 industry、goal_type、scenario_tag、分页 |
| 内容定位矩阵 | GET | `/api/v1/capabilities/content-positioning-matrix` | 3×4 矩阵及每格说明；可选 user_id、brand_name、product_desc、industry |
| 每周决策快照 | GET | `/api/v1/capabilities/weekly-decision-snapshot` | 当前阶段、最大风险、优先级、禁区、本周重点、历史；可选 user_id |

### 2.2 查看「访问时产出的内容」

需要**先启动后端服务**，再运行下面任一方式查看响应内容。

**方式一：HTTP 请求并打印内容（推荐）**

```bash
uvicorn main:app --reload --port 8000
# 另开终端
python scripts/run_capability_apis_content.py
```

- 会请求上述 4 个接口并打印：HTTP 状态、success/source、items/案例数/matrix 格子数、首几条示例内容等。
- 环境变量 **SKIP_SLOW=1** 可跳过「内容方向榜单」和「每周决策快照」（避免长时间等待 LLM）。

**方式二：结构校验脚本（同样需服务已启动）**

```bash
python scripts/verify_capability_apis.py
```

- 校验 4 个接口的响应结构（如 data.items、data.matrix、data.priorities/forbidden 等），并做简单质量检查；同样支持 SKIP_SLOW=1。

**方式三：pytest 集成测试（需 REDIS_URL、DATABASE_URL，可选 DASHSCOPE_API_KEY）**

```bash
pytest scripts/test_capability_apis.py -v -s
```

- 使用 async_client 在应用 lifespan 内请求 4 个接口，断言结构与部分字段；可看到断言失败时的响应内容。
- 内容方向榜单、每周决策快照的用例在无 DASHSCOPE_API_KEY 时会跳过。

### 2.3 产出内容说明（访问时返回什么）

- **内容方向榜单**：`data.items` 为列表，每项含标题建议、核心角度、适配度/风险/角度等；来源为 `content_direction_ranking` 或回退到 `topic_selection`。
- **案例库**：`data.items`（或 `data.list`）为案例列表，含 title、industry、goal_type 等；来自 CaseTemplateService。
- **内容定位矩阵**：`data.matrix` 为 12 格（3×4）或 9 格（3×3，视实现），每格含 priority、stage、boundary、suggestion、example；`data.persona` 为画像摘要。
- **每周决策快照**：`data` 含 stage、max_risk、priorities、forbidden、weekly_focus、history；会先拉取 account_diagnosis 与 content_positioning 再聚合。

在本地未启动服务或未配置 DB/Redis/AI 时，运行 `run_capability_apis_content.py` 会报「连接失败」；运行 `run_capability_apis_with_testclient.py` 可能报 500（如 case-library 连库失败、content-positioning 依赖 AI 未初始化）。**要完整查看产出内容，请先启动 uvicorn 并保证依赖服务可用，再执行 `run_capability_apis_content.py`。**

---

## 三、脚本索引

| 脚本 | 用途 |
|------|------|
| `scripts/run_memory_regression.py` | 记忆模块全面回归（pytest step1/2/3/5/7） |
| `scripts/run_capability_apis_content.py` | 四能力接口请求并打印产出内容（需服务已启动） |
| `scripts/verify_capability_apis.py` | 四能力接口结构校验（需服务已启动） |
| `scripts/test_capability_apis.py` | 四能力接口 pytest（需集成环境） |

更多脚本说明见 `scripts/README.md`。
