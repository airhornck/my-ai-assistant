# 记忆系统优化方案（最终落地方案）

本文档为记忆系统优化的**独立落地方案**，包含方案摘要、详细实现步骤与记忆相关 API 设计。背景与对比分析见 [MEMORY_VS_CHATGPT.md](./MEMORY_VS_CHATGPT.md)。

---

## 一、方案摘要

| 维度 | 选择 |
|------|------|
| **存储** | 新增表 `user_memory_items`，不引入 Milvus/文件存储 |
| **向量** | 复用项目已有 embedding（config/api_config + OpenAI 兼容接口） |
| **召回** | 按当前请求语义 top_k（topic + product_desc + brand_name → embed → 余弦相似度） |
| **Token** | preference_context 总预算（如 500～600 tokens），短画像 + top_k 记忆条 + 近期 2～3 条交互 |
| **可查可看** | GET 列表、**GET 单条内容查看**、DELETE 清空/单条删；写后使该用户记忆缓存失效 |
| **调用方** | `get_memory_for_analyze` 入参/返回值不变，仅记忆模块内部实现变更 |

---

## 二、记忆相关接口（含记忆内容查看）

以下接口均在 `main.py` 中挂载，需传入 `user_id`（如 query 参数或请求头），并做权限/归属校验（仅能操作当前用户）。

| 方法 | 路径 | 说明 |
|------|------|------|
| **GET** | `/api/v1/memory` | **记忆列表/摘要**：返回当前用户的画像摘要 + 记忆条列表（id、content 摘要、source、created_at）+ 近期交互条数 |
| **GET** | `/api/v1/memory/{memory_id}` | **记忆内容查看**：返回单条记忆的**完整内容**（id、content、source、created_at），用于「点击某条记忆查看详情」 |
| **DELETE** | `/api/v1/memory` | **清空当前用户所有记忆条**（不删 UserProfile 与 InteractionHistory），并失效该用户记忆缓存 |
| **DELETE** | `/api/v1/memory/{memory_id}` | **删除单条记忆**，并失效该用户记忆缓存 |

### 2.1 GET /api/v1/memory（列表/摘要）

- **请求**：`GET /api/v1/memory?user_id=xxx`（或从认证上下文取 user_id）。
- **响应示例**：
```json
{
  "profile_summary": {
    "brand_name": "某品牌",
    "industry": "电商",
    "preferred_style": "简洁",
    "tags": ["科技数码", "偏爱短文案"]
  },
  "memory_items": [
    {
      "id": 1,
      "content_preview": "品牌定位为年轻女性美妆…",
      "source": "brand_fact",
      "created_at": "2025-02-15T10:00:00Z"
    }
  ],
  "recent_interaction_count": 5
}
```
- **说明**：`content_preview` 为截断摘要（如前 80 字），用于列表展示；完整内容通过 **GET /api/v1/memory/{id}** 查看。

### 2.2 GET /api/v1/memory/{memory_id}（记忆内容查看）

- **请求**：`GET /api/v1/memory/123?user_id=xxx`。
- **响应示例**：
```json
{
  "id": 123,
  "user_id": "xxx",
  "content": "完整的记忆条正文内容，可能较长…",
  "source": "explicit",
  "created_at": "2025-02-15T10:00:00Z"
}
```
- **说明**：用于用户点击某条记忆时查看**完整内容**；需校验 `memory_id` 属于当前 `user_id`，否则 404。

### 2.3 DELETE /api/v1/memory 与 DELETE /api/v1/memory/{memory_id}

- **DELETE /api/v1/memory**：删除该用户下所有 `user_memory_items` 记录，不删 UserProfile、InteractionHistory；写后对该 user 的记忆缓存做 delete。
- **DELETE /api/v1/memory/{memory_id}**：删除指定 id 的记忆条（需校验归属）；写后对该 user 的记忆缓存做 delete。

---

## 三、详细实现步骤

### 步骤 1：数据库新增表与模型

1. 在 `database.py` 中新增模型 `UserMemoryItem`：
   - 表名：`user_memory_items`
   - 字段：
     - `id`：主键，自增
     - `user_id`：String(64)，外键关联 `user_profiles.user_id`（或仅索引），非空
     - `content`：Text，记忆条正文
     - `source`：String(32)，取值如 `explicit` | `brand_fact` | `success_case` | `profile_snapshot`
     - `created_at`：DateTime
     - `embedding_json`：JSON 或 Text，存 list of float，用于余弦检索（若单行过大可拆为单独表 `user_memory_embeddings(memory_id, embedding_json)`）
2. 编写迁移脚本或 Alembic migration：创建 `user_memory_items` 表（及可选 `user_memory_embeddings`）。
3. 在 `database.py` 中导出 `UserMemoryItem`，供 MemoryService 使用。

### 步骤 2：记忆模块内 Embedding 封装

1. 在 `services/` 下（或 memory 子包内）新增可复用函数或小模块：根据 `config.api_config.get_embedding_config()` 创建 OpenAI 兼容客户端，对外提供 `get_embedding(text: str) -> list[float] | None`，实现与 `retrieval_service._get_embedding` 一致，避免循环依赖。
2. 若希望完全复用 retrieval_service，可在 MemoryService 内通过延迟导入调用其 _get_embedding；否则在 memory 侧单独封装一次即可。

### 步骤 3：记忆条 CRUD 与写后缓存失效

1. 在 `MemoryService` 中新增：
   - `add_memory(user_id: str, content: str, source: str)`：写入一条记录，调用 embedding 接口得到向量，落库 `user_memory_items`（含 `embedding_json`）；写后调用**缓存失效**（见步骤 4）。
   - `list_memories(user_id: str)`：返回该用户的画像摘要（来自 UserProfile）+ 记忆条列表（id、content 摘要如前 80 字、source、created_at）+ 近期交互条数（count）。
   - `get_memory_content(user_id: str, memory_id: int)`：按 id 查询单条，校验 user_id 归属后返回完整 content、source、created_at；否则返回 None。
   - `delete_memory(user_id: str, memory_id: int | None)`：memory_id 为 None 时删除该用户全部记忆条；否则删除指定 id（需校验归属）；写后缓存失效。
   - `clear_memories(user_id: str)`：等同于 `delete_memory(user_id, None)`。
2. 上述写操作（add_memory、delete_memory/clear_memories）完成后，对该 user 的「记忆缓存」做 delete：若 SmartCache 按 user 或按请求指纹缓存 get_memory_for_analyze，则删除该 user 相关 key（例如 build_fingerprint_key 的 prefix 为 `memory:{user_id}` 或遍历删除含该 user_id 的 key，视当前缓存键设计而定）。

### 步骤 4：get_memory_for_analyze 写后缓存失效约定

1. 确定当前 `get_memory_for_analyze` 的缓存键规则（如 `build_fingerprint_key("memory:", {user_id, brand_name, ...})`）。
2. 在 MemoryService 内提供内部方法 `_invalidate_memory_cache_for_user(user_id: str)`：若使用了 SmartCache，则删除所有与该 user_id 相关的 memory 缓存键（若键中带 user_id，可用 Redis 的 SCAN + 匹配 prefix 删除，或维护一份 user_id -> [keys] 的映射在写时删除）。
3. 在 `add_memory`、`delete_memory`、`clear_memories` 成功执行后调用 `_invalidate_memory_cache_for_user(user_id)`。

### 步骤 5：_get_memory_for_analyze_impl 改为语义 top_k + token 预算

1. 在 `_get_memory_for_analyze_impl` 中：
   - 从 UserProfile 取**短画像**：1～2 行（品牌、行业、风格、tags），拼成一段固定短文本。
   - 用 `topic + product_desc + brand_name` 拼成 query 文本；若为空则用 "用户偏好" 等默认短句。
   - 调用 embedding 得到 query 向量；从 DB 读取该 user 下所有 `user_memory_items`（仅 id、content、embedding_json），用 numpy 计算与 query 的余弦相似度，取 **top_k**（如 4～5 条）。
   - 取**近期 2～3 条** InteractionHistory（按 created_at 倒序），格式化为简短一行一条。
   - 按顺序拼装：短画像 + 语义 top_k 记忆条（每条 content 截断到约 80 字或 1 句）+ 近期交互；总字符或 token 数不超过预算（如 600 tokens），超出部分从尾部截断。
   - 返回值仍为 `{"preference_context": str, "context_fingerprint": dict, "effective_tags": list}`，保证 `get_memory_for_analyze` 的入参与返回值**不变**。
2. 若该 user 无任何记忆条，则语义召回部分为空，仅保留短画像 + 近期交互，行为与「无记忆条」一致。

### 步骤 6：为品牌事实 / 成功案例与「记住 X」提供写入口

1. **品牌事实 / 成功案例**：在合适的调用点（如 `_persist_user_profile_for_ltm` 扩展、或诊断/分析报告完成回调）中，将「品牌事实」「成功案例」的文本（或结构化转成一段话）调用 `MemoryService.add_memory(user_id, content, source="brand_fact" | "success_case")`。若当前已有从会话中解析的 brand_name/industry，可同时写一条 `profile_snapshot` 类记忆（如 "品牌：X，行业：Y"），便于语义召回。
2. **「用户说记住 X」**：在意图/NLU 中识别用户显式要求记住的内容（如「记住：我主要做美妆」），解析出待存储文本后调用 `add_memory(user_id, content, source="explicit")`。意图识别与调用点可在 main 或意图处理流程中接一次即可。

### 步骤 7：挂载记忆列表、记忆内容查看与删除 API

1. 在 `main.py` 中：
   - **GET /api/v1/memory**：从 query 或上下文取 `user_id`，调 `memory_svc.list_memories(user_id)`，返回 2.1 节格式的 JSON。
   - **GET /api/v1/memory/{memory_id}**：取 `user_id` 与 path 参数 `memory_id`，调 `memory_svc.get_memory_content(user_id, int(memory_id))`；若为 None 则 404，否则返回 2.2 节格式的 JSON。
   - **DELETE /api/v1/memory**：取 `user_id`，调 `memory_svc.clear_memories(user_id)`，返回 204 或简单成功 JSON。
   - **DELETE /api/v1/memory/{memory_id}**：取 `user_id` 与 `memory_id`，调 `memory_svc.delete_memory(user_id, int(memory_id))`（需在 delete_memory 内校验归属），返回 204 或简单成功 JSON。
2. 上述接口需确保 **user_id 与当前请求身份一致**（若项目有鉴权，则从 token/session 取 user_id，避免越权）。

### 步骤 8：可选——记忆开关

1. 在调用 `get_memory_for_analyze` 的上层（如 meta_workflow 的 memory_query 或 main 中组装的 state）中，若请求带 `use_memory=false`（或会话级设置），则**不调用** get_memory_for_analyze，直接使用空的 preference_context / effective_tags，实现「本轮不用长期记忆」。

### 步骤 9：测试与回归

1. 单元或集成测试：新增表 CRUD、embedding 写入与 top_k 召回、token 预算截断、缓存失效。
2. 回归：确认 meta_workflow、basic_workflow、campaign_planner 等仍按原方式调用 `get_memory_for_analyze`，且返回结构不变；确认 GET/DELETE 记忆接口的权限与归属校验。

---

## 四、实现步骤一览表

| 序号 | 步骤 | 产出 |
|------|------|------|
| 1 | 数据库新增表与模型 | UserMemoryItem 模型与 migration |
| 2 | 记忆模块内 Embedding 封装 | get_embedding(text) 可用 |
| 3 | 记忆条 CRUD 与写后缓存失效 | add_memory, list_memories, get_memory_content, delete_memory, clear_memories |
| 4 | get_memory_for_analyze 写后缓存失效约定 | _invalidate_memory_cache_for_user 及写后调用 |
| 5 | _get_memory_for_analyze_impl 语义 top_k + token 预算 | 新召回与拼装逻辑，对外接口不变 |
| 6 | 品牌事实/成功案例/「记住 X」写入口 | 若干调用 add_memory 的接入点 |
| 7 | 挂载 GET/DELETE 记忆 API（含记忆内容查看） | GET /api/v1/memory、GET /api/v1/memory/{id}、DELETE /api/v1/memory、DELETE /api/v1/memory/{id} |
| 8 | 可选记忆开关 | use_memory=false 时跳过长期记忆 |
| 9 | 测试与回归 | 测试通过、工作流与调用方无破坏 |

---

## 五、参考

- 记忆能力对比与最终综合结论：[MEMORY_VS_CHATGPT.md](./MEMORY_VS_CHATGPT.md)（第〇～八节）
- 现有记忆服务实现：`services/memory_service.py`
- 现有 embedding 与检索：`config/api_config.py`（get_embedding_config）、`services/retrieval_service.py`（_get_embedding、余弦相似度）
