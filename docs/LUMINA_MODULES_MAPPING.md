# Lumina 四模块与分析脑插件映射

参考 [Lumina 产品](https://lumina-ai.cn/product) 四大核心模块，梳理本项目分析脑插件对应关系及待开发能力。

---

## 一、Lumina 四模块与现有插件对应

| Lumina 模块 | 功能要点 | 现有分析脑插件 | 对应关系 | 状态 |
|-------------|----------|----------------|----------|------|
| **1. 已过滤的内容方向榜单** | 适配度、热度、风险、角度建议、标题模板 | `content_direction_ranking`（新）、`topic_selection`、各热点 | 新插件输出完整榜单，接口优先用新插件 | ✅ 已实现 |
| **2. 定位决策案例库** | 前后对比、关键步骤、决策规则、行业/阶段 | `case_library` | 直接对应，能力接口走 CaseTemplateService | ✅ 已有 |
| **3. 内容定位矩阵** | 3x4 矩阵、优先级、阶段、边界、推荐 | `content_positioning` | 插件已输出 `position_matrix`（3×4） | ✅ 已增强 |
| **4. 每周决策快照** | 阶段判断、风险、优先级、禁区、历史追踪 | `weekly_decision_snapshot`（新） | 新插件聚合诊断+定位，输出快照与历史 | ✅ 已实现 |

---

## 二、现有分析脑插件清单（含 Lumina 四模块相关）

| 序号 | 插件名 | 类型 | 说明 |
|------|--------|------|------|
| 1 | bilibili_hotspot | 定时 | B站热点榜单 |
| 2 | douyin_hotspot | 定时 | 抖音热点 |
| 3 | xiaohongshu_hotspot | 定时 | 小红书热点 |
| 4 | acfun_hotspot | 定时 | A站热点 |
| 5 | methodology | 定时 | 营销方法论 |
| 6 | case_library | 定时 | 案例库 |
| 7 | knowledge_base | 实时+缓存 | 知识库检索 |
| 8 | campaign_context | 实时 | 活动策划上下文拼装 |
| 9 | topic_selection | 定时 | 选题推荐 |
| 10 | **content_direction_ranking** | 实时 | **内容方向榜单（适配度/热度/风险/角度/标题）** |
| 11 | content_positioning | 实时 | 内容定位（人设/四件套/方向 + 3×4 矩阵） |
| 12 | business_positioning | 实时 | 商业定位 |
| 13 | account_diagnosis | 实时 | 账号诊断 |
| 14 | **weekly_decision_snapshot** | 实时 | **每周决策快照（阶段/风险/优先级/禁区/历史）** |
| 15 | video_viral_structure | 实时 | 视频爆款结构拆解 |
| 16 | text_viral_structure | 实时 | 文本爆款结构拆解 |
| 17 | ctr_prediction | 实时 | CTR 预测 |
| 18 | viral_prediction | 实时 | 爆款预测 |
| 19 | rate_limit_diagnosis | 实时 | 限流诊断 |
| 20 | cover_diagnosis | 实时 | 封面诊断 |
| 21 | script_replication | 实时 | 脚本复刻 |

---

## 三、已完成的 Lumina 四模块实现

### 3.1 内容方向榜单（Lumina 模块 1）

- **插件**：`plugins/content_direction_ranking.py`（`content_direction_ranking`）
- **输出**：基于画像与热点，AI 生成榜单，每项含：`adaptation_score`、`heat_trend`、`risk_level`、`angles`、`title_templates`、`risk_warning`。
- **能力接口**：`GET /api/v1/capabilities/content-direction-ranking` 优先调用该插件，无结果时回退 `topic_selection`。

### 3.2 内容定位矩阵（Lumina 模块 3）

- **增强**：`content_positioning_plugin` 在返回中增加 `position_matrix`（3×4：优先级 × 阶段 + 边界与禁区），每格含 `boundary`、`suggestion`、`example`。
- **能力接口**：`GET /api/v1/capabilities/content-positioning-matrix` 直接透传插件输出的 `position_matrix`。

### 3.3 每周决策快照（Lumina 模块 4）

- **插件**：`plugins/weekly_decision_snapshot.py`（`weekly_decision_snapshot`）
- **输出**：聚合 `context.analysis` 中的 `account_diagnosis`、`content_positioning`，生成 `stage`、`max_risk`、`priorities`、`forbidden`、`weekly_focus`、`history`；历史写入缓存。
- **能力接口**：`GET /api/v1/capabilities/weekly-decision-snapshot` 先拉取 account_diagnosis 与 content_positioning，再调用本插件。

---

## 四、统一能力接口与四模块

对外暴露的四模块能力接口（见 `docs/API_REFERENCE.md`）：

| 能力 | 接口路径 | 说明 |
|------|----------|------|
| 内容方向榜单 | `GET /api/v1/capabilities/content-direction-ranking` | 已过滤的内容方向列表（适配度/热度/风险/角度/标题） |
| 定位决策案例库 | `GET /api/v1/capabilities/case-library` | 案例列表与详情（前后对比、步骤、规则、行业/阶段） |
| 内容定位矩阵 | `GET /api/v1/capabilities/content-positioning-matrix` | 3x4 矩阵与每格说明 |
| 每周决策快照 | `GET /api/v1/capabilities/weekly-decision-snapshot` | 当前快照及历史列表 |

上述接口由统一能力路由 `routers/capability_api.py` 提供，内部调用对应分析脑插件或聚合逻辑。
