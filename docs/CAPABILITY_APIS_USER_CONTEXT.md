# 能力接口：Chat 模式 + 先补全信息再出定制内容

四个能力接口（content-direction-ranking、case-library、content-positioning-matrix、weekly-decision-snapshot）以 **chat 模式**与用户交互：根据插件能力所需，先询问用户补充信息；信息齐全后再调用插件，生成**用户账号的定制内容**，而非通用内容。

---

## 1. Chat 模式流程

1. **用户发起能力请求**（如「我要看内容方向榜单」）→ 前端调用对应能力 API（可带 `user_id`、`platform`、`industry` 等）。
2. **后端检查是否具备「账号定制」所需信息**：
   - 若**不足**：返回 `need_clarification: true`，并带上 `message`（向用户提问的文案）、`missing_fields`，前端在对话中展示该 `message`，引导用户补充。
3. **用户回复**（如「小红书，美妆品牌」）→ 前端再次请求同一 API，并带上用户补充的参数（如 `platform=xiaohongshu`、`industry=美妆` 或从自然语言解析出的字段）。
4. **信息齐全后**：后端调用插件，返回 `need_clarification: false` 和定制化 `data`。

响应中 `need_clarification` 为 `true` 时，表示当前为「询问补充」回合，不包含业务数据；为 `false` 时表示已产出账号定制内容。

---

## 2. 各能力所需信息与澄清话术

| 能力 | 所需信息（满足其一或组合即可） | 缺失时返回的 message 示例 |
|------|--------------------------------|----------------------------|
| **content_direction_ranking** | 平台 +（品牌/行业 或 已绑定 user_id 画像） | 为生成您的专属内容方向榜单，请补充：① 要投放的平台；② 品牌名称或所在行业。您也可以先绑定账号。 |
| **case_library** | 行业 或 目标类型 或 已绑定 user_id 画像 | 为推荐与您最相关的定位决策案例，请补充：您的行业或目标类型。 |
| **content_positioning_matrix** | 品牌 或 行业 或 已绑定 user_id 画像 | 为生成您的专属内容定位矩阵与人设分析，请补充：品牌名称或所在行业。 |
| **weekly_decision_snapshot** | user_id（已绑定账号）或 品牌+行业 | 每周决策快照需要关联您的账号或品牌信息。请先绑定账号，或补充品牌名称与行业。 |

配置与判断逻辑在 `routers/capability_api.py` 的 `CLARIFICATION_CONFIG` 与 `_need_clarification()` 中维护。

---

## 3. 实现要点

### 3.1 用户上下文加载 `_load_user_context`

- 根据 `user_id` 和请求参数，组装「用户画像 + 偏好/记忆」；
- 若有 `user_id`：从 DB 拉取/创建 `UserProfile`，并用 `MemoryService` 得到 `preference_context`；
- 请求参数与画像合并，请求参数优先。

### 3.2 澄清判断 `_need_clarification`

- 入参：能力名、`profile_dict`（来自 `_load_user_context`）、以及当前请求的 `platform`、`industry`、`brand_name` 等；
- 若已有「账号定制」所需信息（含从画像补全）：返回 `(False, "", [])`，接口继续调插件；
- 若不足：返回 `(True, message, missing_fields)`，接口返回 `_clarification_response`，不调插件。

### 3.3 统一澄清响应 `_clarification_response`

- `success: true`、`need_clarification: true`、`capability`、`message`、`missing_fields`、`hint`，`data: null`；
- 前端用 `message` 在对话中向用户提问，用户补充后带齐参数再次请求同一能力接口。

### 3.4 成功产出时的响应

- `success: true`、`need_clarification: false`、`data: { ... }`（插件产出的账号定制内容）。

---

## 4. 依赖注入

- **MemoryService**：`get_memory_service_for_router`；在 main lifespan 中通过 `set_memory_service` 注入。
- **AI 服务**：`get_ai_service_for_router`，用于插件中心与缓存。

---

## 5. 文件改动摘要

- `routers/capability_api.py`：  
  - 新增 `CLARIFICATION_CONFIG`、`_need_clarification()`、`_clarification_response()`；  
  - 四个能力接口先 `_load_user_context`，再 `_need_clarification`，不足则直接返回澄清响应，否则调插件并返回 `need_clarification: false` 与定制 `data`。  
- `core/deps.py`：MemoryService 的引用与注入。  
- `main.py`：lifespan 中设置 `MemoryService`。

这样，四个能力接口在 chat 模式下会先根据插件能力询问用户补充信息，再生成账号定制内容，避免输出通用内容。
