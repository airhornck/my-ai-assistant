# 数据闭环与知识/案例/方法论模块设计

本文档描述：数据接收与闭环、知识库独立模块（含案例目标与复用）、营销策略案例模板与打分、营销方法论独立管理、活动策略调用逻辑优化。设计注重性能与用户体验。

---

## 一、目标与范围

| 序号 | 目标 | 要点 |
|------|------|------|
| 1 | 数据接收与闭环 | 接收用户反馈、平台数据回流，支撑打分与优化 |
| 2 | 知识库模块独立 | 可单独开发维护；生产对接阿里云知识库（百炼 RAG） |
| 3 | 营销策略案例模板与打分 | 模板管理 + 打分（回流数据 / 用户评分 / 系统自动），便于积累优秀策略 |
| 4 | 营销方法论独立管理 | 独立模块，与知识库解耦 |
| 5 | 活动策略调用逻辑优化 | 方法论 + 知识库 + 案例模板 与 用户意图、画像 合理匹配与调用 |

---

## 二、数据接收与闭环（目标 1）

### 2.1 数据来源

- **用户使用反馈**：已有 `FeedbackService` 写 `InteractionHistory.user_rating` / `user_comment`；扩展为「数据闭环」统一入口，可写入反馈事件表供打分与统计。
- **平台数据回流**：曝光、点击、转化等（来自投放/BI 等），通过统一 API 上报，写入平台回流表。

### 2.2 数据模型与存储

- **feedback_events**（可选，若需与交互表解耦）：  
  `id, session_id, user_id, source(enum: user_submit | platform_reflow), rating_or_metric, payload(JSON), created_at`  
  现有反馈可继续写 `InteractionHistory`，同时写入 `feedback_events` 或仅用其一，由实现决定。
- **platform_metrics**（平台回流）：  
  `id, session_id, user_id, metric_type(enum: exposure | click | conversion | ...), value, dimensions(JSON), created_at`

### 2.3 API 与性能

- **POST /api/v1/data/feedback**：接收用户反馈（可复用现有 feedback 或扩展 body）。
- **POST /api/v1/data/platform-metrics**：批量接收平台回流（建议批量接口，减少请求数）。
- 写入采用异步、批量落库或队列消费，避免阻塞主链路；索引仅建查询所需字段（如 `session_id, user_id, created_at`）。

---

## 三、知识库模块独立（目标 2）

### 3.1 定位

- 知识库模块负责：**检索增强（RAG）** 与 **案例检索与复用** 的抽象与实现。
- 与「营销方法论」「案例模板」解耦：方法论、案例模板由各自模块管理，知识库只负责「按 query 检索段落/案例」的接口与实现。

### 3.2 接口（Port）

- 定义在独立包内，例如 `modules/knowledge_base/port.py`：
  - `retrieve(query: str, top_k: int, **kwargs) -> List[str]`  
    返回与 query 相关的文本段落（用于 RAG 注入）。
  - （可选）`retrieve_cases(query: str, scenario: dict, top_k: int) -> List[CaseHit]`  
    用于案例复用场景，由「案例模板模块」调用或与知识库联合实现。
- 生产对接**阿里云百炼知识库（RAG）**：实现类调用 Retrieve API，本地开发使用现有 `RetrievalService` 或文件向量。

### 3.3 实现（Adapter）

- **LocalKnowledgeAdapter**：基于现有 `services/retrieval_service.py` 或迁移后的向量 JSON，用于本地/开发。
- **AliyunKnowledgeAdapter**：封装阿里云百炼知识库 Retrieve API，环境变量配置（如 `ALIYUN_BAILIAN_*`），生产切换到此实现。
- 通过配置/依赖注入选择 Adapter，保证可单独开发、测试、部署知识库模块。

### 3.4 性能

- 本地：已有向量持久化与 SmartCache，检索 key 含 query+top_k。
- 阿里云：使用百炼推荐超时与重试；对相同 query 可在应用层做短 TTL 缓存，减少重复调用。

---

## 四、营销策略案例模板与打分（目标 3）

### 4.1 职责

- **案例模板管理**：创建、更新、列表、详情、删除（或软删）。
- **打分**：支持多来源——回流数据、用户评分、系统自动；无前两者时走系统自动评分，便于筛选「优秀营销策略」并复用于同类场景。

### 4.2 数据模型

- **marketing_case_templates**：  
  `id, title, summary, content(Text), scenario_tags(JSON), industry, goal_type, source_session_id, created_at, updated_at`  
  可选：`status(draft/published)`、`created_by`。
- **case_scores**：  
  `id, case_id(FK), source(enum: platform_reflow | user_review | system_auto), score_value, payload(JSON), created_at`  
  聚合展示时可按 case 维度做加权或取最近 N 次。

### 4.3 打分逻辑

- **用户评分**：用户对某次生成结果评分时，若该结果被标记为「可沉淀为案例」，则写一条 `case_scores(source=user_review)`，并可选自动创建/更新 `marketing_case_templates`。
- **平台回流**：数据接收环节写入 `platform_metrics` 后，由后台任务或事件将转化等指标折算为分数，写入 `case_scores(source=platform_reflow)`，关联到对应 case（通过 session_id / content_id 等）。
- **系统自动**：当既无用户评分也无回流数据时，用规则或轻量模型对内容做质量分（如结构完整性、关键要素覆盖度），写入 `case_scores(source=system_auto)`。
- 列表/详情接口返回「综合分」或「各来源最新分」，便于排序与单独查看、管理。

### 4.4 API 与性能

- **CRUD**：`GET/POST/PUT/DELETE /api/v1/cases`（或 `/api/v1/marketing-cases`），列表支持分页、按行业/目标/标签筛选。
- **打分**：用户评分走现有反馈接口扩展或 `POST /api/v1/data/feedback`；回流写 `platform_metrics`；系统自动评分由定时/异步任务执行。
- 列表查询建索引（industry, goal_type, created_at），分页限制 page_size，避免大结果集。

---

## 五、营销方法论独立管理（目标 4）

### 5.1 职责

- 营销方法论的增删改查、版本管理（可选）、分类/标签。
- 与「知识库」解耦：方法论内容由本模块管理；检索时可由「活动策略编排」先查方法论模块再决定注入哪些内容，或由知识库统一检索（若方法论也写入知识库），取决于实现选择。

### 5.2 实现方式（二选一或并存）

- **方案 A**：继续使用 `knowledge/` 下 Markdown 文件 + 现有向量化，方法论单独子目录（如 `knowledge/methodology/`），由「方法论模块」提供 API 仅做「文件/目录的 CRUD 与元数据」，检索仍走知识库模块。
- **方案 B**：方法论存 DB（如 `methodology_docs` 表），内容字段 Text，本模块 CRUD；检索时由知识库模块从 DB 建索引或同步到知识库，生产可同步到阿里云知识库。

建议先采用**方案 A**（文件 + 元数据 API），后续若有版本/协作需求再迁部分到 DB。

### 5.3 API

- **GET/POST/PUT/DELETE /api/v1/methodology**：列表（分页、按分类筛选）、创建、更新、删除。
- 文件方案下：创建/更新 = 写 `knowledge/methodology/*.md`，删除 = 删文件；并删除向量目录以触发重建，或由后台触发重建。

---

## 六、活动策略调用逻辑优化（目标 5）

### 6.1 原则

- **意图与画像驱动**：根据用户意图（如「做活动方案」「写单篇文案」）和画像（行业、品牌、目标、标签）决定拉取哪些「方法论」「知识库段落」「案例模板」及优先级。
- **合理匹配**：同行业、同目标类型优先匹配案例与对应方法论；避免无关内容注入，控制 prompt 长度，保障体验与性能。

### 6.2 编排流程（建议）

1. **输入**：user_input（含 brand, product, topic, tags）、user_id、session_id。
2. **意图与画像**：从 user_input 或已有 UserProfile 得到 industry、goal_type、tags；若当前仅有「活动策划」一种深度意图，可简化为固定为活动策划。
3. **并行拉取（性能）**：  
   - 方法论：按 industry/ goal_type 从方法论模块取若干条（或由知识库检索 methodology 相关段落）。  
   - 知识库：`retrieve(query=brand+topic+product, top_k=4)`（或由阿里云知识库检索）。  
   - 案例模板：按 scenario_tags/ industry/ goal_type 筛选并取综合分高的 top_k 条，或通过知识库/案例模块的 `retrieve_cases`。  
   以上三路可并行（asyncio.gather），再合并。
4. **合并与去重**：将「方法论」「知识库段落」「案例模板」按约定顺序拼成「行业知识 + 参考案例」块，注入活动策划 prompt；若总长度超限，优先保留案例与高相关方法论。
5. **生成**：现有活动策划 LLM 生成逻辑，保持不变；仅扩大或替换「行业知识」来源。

### 6.3 性能与体验

- **并行**：方法论、知识库、案例三路并行请求；内部已有缓存的继续用 SmartCache。
- **超时与降级**：单路超时或失败时降级为缺省内容（如仅用方法论或仅用知识库），不阻塞整体。
- **缓存**：对「同一 user_input 指纹」的检索结果做短 TTL 缓存（已有 retrieval cache 可复用 key 设计）。

---

## 七、模块依赖关系（简化）

```
[ 数据接收 API ]  →  feedback_events / platform_metrics
       ↓
[ 案例打分 ]  ← 用户评分、回流数据、系统自动
       ↓
[ 案例模板模块 ]  ← 列表/详情/CRUD，供「活动策略编排」检索
       ↑
[ 活动策略编排 ]  ← 意图 + 画像 → 并行拉取 方法论 / 知识库 / 案例
       ↑              ↑              ↑
[ 方法论模块 ]   [ 知识库模块 ]   [ 案例模块 ]
                     ↑
               (生产: 阿里云百炼知识库)
```

---

## 八、实施顺序建议

1. **数据接收**：定义 feedback_events / platform_metrics 表与写入 API；现有用户反馈可双写或迁到新表。
2. **知识库模块独立**：抽 Port + Local/Aliyun Adapter，现有 retrieval 迁入 Local Adapter，配置切换。
3. **案例模板与打分**：建表、CRUD API、打分来源接入（用户评分、回流、系统自动），列表支持按分排序与筛选。
4. **方法论模块**：独立 API 与目录/文件或 DB 管理，与知识库解耦。
5. **活动策略编排**：重构 campaign_planner 或新建 strategy_orchestrator，按意图与画像并行拉取方法论 + 知识库 + 案例，合并后注入 prompt，并做超时与缓存。

以上设计在实现时需注重：索引与分页、批量写入、并行与超时、缓存与降级，以保障性能与用户体验。

---

## 九、实现状态与 API 一览

| 模块 | 状态 | API / 入口 |
|------|------|------------|
| 数据接收 | 已实现 | POST /api/v1/data/feedback，POST /api/v1/data/platform-metrics |
| 知识库独立 | 已实现 | Port + LocalKnowledgeAdapter + AliyunKnowledgeAdapter，工厂 get_knowledge_port() |
| 案例模板与打分 | 已实现 | GET/POST/PUT/DELETE /api/v1/cases，POST /api/v1/cases/{id}/scores |
| 方法论管理 | 已实现 | GET/PUT/DELETE /api/v1/methodology，GET/PUT/DELETE /api/v1/methodology/doc |
| 活动策略编排 | 已实现 | workflows/strategy_orchestrator.run_campaign_with_context，campaign_planner 可注入三端走编排 |

**环境变量（知识库生产）**：`USE_ALIYUN_KNOWLEDGE=1`，`ALIYUN_BAILIAN_WORKSPACE_ID`，`ALIYUN_BAILIAN_INDEX_ID`。未配置时使用本地向量。

---

## 十、两个目标的建议方向与实现状态

### 目标一（立刻可用）

| 建议 | 状态 | 说明 |
|------|------|------|
| 活动策划并入统一入口（方案 A） | ✅ 已实现 | 活动策划由 meta_workflow 内 task_type=campaign_or_copy 时走 strategy_orchestrator（方法论+知识库+案例并行）；`POST /api/v1/campaign/plan` 已下线，前端通过 `frontend/chat` 发起，规划脑输出 task_type 后编排层自动分支。 |
| 在编排中增加 kb_retrieve 步骤 | ✅ 已实现 | 编排层支持步骤名 `kb_retrieve`，与 web_search、memory_query、bilibili_hotspot 并行执行；结果写入 context["kb_context"]，在 analyze 前合并进 preference_ctx（【知识库检索】）。规划提示中已加入 kb_retrieve 说明，策略脑可输出该步骤。 |

### 目标二（案例模板与复用）

| 建议 | 状态 | 说明 |
|------|------|------|
| 内容形态：案例/模板与方法论文档区分 | ✅ 已实现 | 案例存 DB（marketing_case_templates，含 industry、goal_type、scenario_tags）；方法论存 knowledge/ 或 knowledge/methodology/，与案例库分离。 |
| 积累机制：将某次生成方案标记为案例并写入 | ✅ 已实现 | `POST /api/v1/cases/from-session`：入参 session_id、title、industry、goal_type、scenario_tags；按 session_id 取该会话最近一条交互的 ai_output 作为案例 content，写入案例库并记录 source_session_id。 |
| 检索与复用：两路检索 + prompt 显式区分 + 以案例为基础改写 | ✅ 已实现 | 活动策划编排并行拉取方法论、知识库、案例（按 industry/goal_type）；prompt 中区分【营销方法论】【行业知识】【参考案例】；system/user 中已加入「若下方有参考案例，请优先参考其结构与要点，结合本次请求进行改写或填空」及「若上方有参考案例，请以其为基础改写或填空，避免从零堆砌」。 |
