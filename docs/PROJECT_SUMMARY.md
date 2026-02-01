# 项目总结：AI 营销助手

## 一、设计需求达成情况

### 1. 架构协同：闭环三脑协同 ✅

**需求**：分析 → 生成 → **评估**，形成初级质量反馈环，具备内部质检与反馈能力。

**现状**：
- **basic_workflow**：`analyze` → `generate` → `format` → `evaluate` 四节点闭环
- **evaluation_node**：对生成内容做多维度评估（consistency、creativity、safety、platform_fit），输出 `overall_score` 与 `suggestions`
- **need_revision**：评分 < 6 时标记需修订，供后续策略优化
- **meta_workflow**：规划 → 编排 → 汇总，调用 content 子工作流（含评估）

---

### 2. 记忆系统 ✅

**需求**：SessionManager、MemoryService 就位，支持多轮对话和用户特征记忆，可被查询、用于支撑个性化服务。

**现状**：
- **SessionManager**（`memory/session_manager.py`）：session_id / thread_id 双层级，Redis 存储
- **MemoryService**（`services/memory_service.py`）：三层记忆
  - 第一层：品牌事实库、成功案例库
  - 第二层：用户画像（tags、preferred_style、industry）
  - 第三层：近期交互（InteractionHistory）
- **MemoryOptimizer**：后台异步更新用户画像，支持反馈触发优先处理
- 工作流中 `get_memory_for_analyze` 为分析节点提供偏好上下文

---

### 3. 数据闭环 ✅

**需求**：反馈服务、缓存服务，用户反馈可影响数据，高频请求加速。

**现状**：
- **FeedbackService**：记录 user_rating、user_comment，rating≥4 时触发 `trigger_optimization` 入队
- **SmartCache**：Redis 缓存 AI 分析、记忆查询等，请求指纹去重，TTL 可配置
- **InteractionHistory**：持久化交互与反馈，供 MemoryOptimizer 消费

---

### 4. 核心功能：可评估的内容生成 ✅

**需求**：产出内容附带质量评分与改进建议，价值透明。

**现状**：
- `evaluation_node` 输出 `scores`、`overall`、`suggestions`
- 前端 / API 可返回 `thinking_process` 含评估结果
- 支持 `need_revision` 标记

---

## 二、新增能力（相对原始设计）

| 能力 | 说明 |
|------|------|
| **意图理解** | 五类意图（casual_chat、structured_request、free_discussion、document_query、command），支持澄清流程 |
| **会话级文档** | 文档绑定到会话，理解对话时引用，类似 OpenAI 附加文件 |
| **统一路由** | 根据意图自动在【闲聊】与【创作】间切换，支持深度思考开关 |
| **深度思考（CoT）** | 策略脑构建思维链，动态调用搜索、分析、生成、评估、脑级插件等模块 |
| **网络搜索** | core/search 模块，检索竞品、热点、行业数据 |
| **多平台媒体规范** | B站、小红书、抖音、微博等可配置生成规范（config/media_specs） |
| **插件总线** | DocumentQueryEvent、IntentRecognizedEvent 等事件驱动扩展 |
| **Gradio 前端** | 三列布局、双模式、文件上传、思考过程展示 |
| **Prometheus 监控** | 阶段耗时、请求数等指标 |
| **Docker 编排** | dev/prod 双环境，PostgreSQL + Redis |

---

## 三、公共能力 vs 业务能力（解耦建议）

### 公共能力（已解耦，可独立维护）

| 能力 | 位置 | 说明 |
|------|------|------|
| **AI 调用** | `core/ai/` | ILLMClient 协议 + DashScopeLLMClient，可替换供应商 |
| **意图理解** | `core/intent/` | InputProcessor、意图常量 |
| **文档能力** | `core/document/` | storage、parser、session_binding |
| **插件总线** | `core/plugin_bus.py` | 事件驱动扩展 |
| **插件注册** | `core/plugin_registry.py` | 工作流注册 |

### 业务域（可单独开发与测试）

| 能力 | 位置 | 说明 |
|------|------|------|
| **分析脑** | `domain/content/analyzer.py` | 依赖 ILLMClient，可 mock 单测 |
| **生成脑** | `domain/content/generator.py` | 同上 |
| **评估脑** | `domain/content/evaluator.py` | 同上 |
| **记忆** | `domain/memory/` | MemoryService，用户画像、品牌事实 |
| **AI 门面** | `services/ai_service.py` | 组合 domain + cache，对外 API |
| **工作流** | `workflows/` | basic、meta、strategy、evaluation |
| **媒体规范** | `config/media_specs.py` | 营销平台相关配置 |

---

## 四、文件结构概览

```
├── core/               # 公共能力
│   ├── ai/             # LLM 调用抽象（ILLMClient + DashScope 实现）
│   ├── document/       # 文档存储、解析、会话绑定
│   ├── intent/         # 意图识别
│   ├── plugin_bus.py
│   └── plugin_registry.py
├── domain/             # 业务域
│   ├── content/        # 分析脑、生成脑、评估脑
│   └── memory/         # 记忆服务
├── cache/              # 智能缓存
├── memory/             # 会话管理
├── config/             # 媒体规范等配置
├── models/             # 数据模型
├── services/           # 业务服务
├── workflows/          # 工作流
├── frontend/           # Gradio 前端（app.py 基础版，app_enhanced.py 增强版）
├── docs/               # 文档
└── scripts/            # 脚本与测试
```

---

## 五、脑级插件架构

- **分析脑**：`BrainPluginCenter` 管理定时/实时/工作流/技能插件
- **B站热点**：分析脑定时插件，每 6 小时刷新，结果缓存供策略脑调用
- 详见 `docs/BRAIN_PLUGIN_ARCHITECTURE.md`

## 六、部署

- **本地开发**：`docs/QUICK_START.md`
- **生产 / ESC**：`docs/DEPLOYMENT.md`
- **Docker 排错**：`docs/DOCKER_TROUBLESHOOTING.md`

## 七、文件清理记录

- **已删除**：`frontend/app_enhanced - 副本.py`、`docs/GRADIO_PYTHON314_FIX.md`、`docs/OPTIMIZATION_2025.md`、`docs/REFACTORING_SUMMARY.md`、`docs/DOCKER_BUILD_TROUBLESHOOTING.md`（已合并到 DOCKER_TROUBLESHOOTING.md）
