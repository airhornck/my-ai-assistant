# AI 营销助手 - 项目总结（ESC 部署版）

## 一、项目概述

**定位**：面向 C 端 / B 端的营销 IP 创作智能体，帮助用户打造营销内容（文案、策略等）。

**核心能力**：
- 意图驱动：自动区分【闲聊】与【创作】，统一路由
- 深度思考：策略脑规划思维链，调用分析脑、生成脑、搜索、脑级插件
- 三脑协同：分析 → 生成 → 评估，形成质量反馈环
- 记忆系统：用户画像、会话意图、品牌事实
- 会话级文档：支持 PDF/TXT/DOCX/PPTX/MD/图片、链接，作为参考材料

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│  API 层 (main.py)                                                    │
│  - /api/v1/frontend/chat（统一聊天）                                 │
│  - /api/v1/frontend/session/init                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  意图理解 (InputProcessor) → 自动路由                                 │
│  - casual_chat → 快捷回复                                            │
│  - 创作意图 → MetaWorkflow（策略脑 + 编排）                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  策略脑 (meta_workflow)                                               │
│  - 规划思维链：web_search | memory_query | bilibili_hotspot |        │
│    analyze | generate | evaluate | ...                               │
│  - 编排层并行执行独立步骤，串行执行依赖步骤                            │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────────┐
│ 分析脑       │  │ 生成脑       │  │ 脑级插件（分析脑）                 │
│ ContentAnalyzer│ │ ContentGenerator│ │ BrainPluginCenter               │
│ + plugin_center│ │ 文本/图片/视频 │ │ - bilibili_hotspot（定时）       │
└──────────────┘  └──────────────┘  └──────────────────────────────────┘
```

---

## 三、目录结构（精简）

```
my_ai_assistant/
├── main.py                 # FastAPI 入口
├── config/                 # api_config（LLM/搜索统一配置）、media_specs
├── core/                   # 公共能力
│   ├── ai/                 # ILLMClient、DashScope 实现
│   ├── brain_plugin_center.py  # 脑级插件管理
│   ├── document/           # 文档存储、解析、会话绑定
│   ├── intent/             # 意图识别
│   ├── link/               # 链接解析
│   ├── reference/          # 参考材料提取
│   └── search/             # WebSearcher（百度/mock）
├── domain/                 # 业务域
│   ├── content/            # analyzer、generator、evaluator、generators
│   └── memory/             # MemoryService
├── services/               # ai_service、input_service、document_service 等
├── workflows/              # basic_workflow、meta_workflow、evaluation_node
├── plugins/                # bilibili_hotspot 等
├── frontend/               # Gradio（app_enhanced.py 主用）
├── cache/                  # SmartCache（Redis）
├── memory/                 # SessionManager
├── monitoring/             # Prometheus、Grafana
├── docs/                   # 文档
└── scripts/                # 诊断、刷新、测试脚本
```

---

## 四、解耦与扩展

| 层级 | 说明 |
|------|------|
| **core/** | 公共能力，可独立替换（LLM、文档、搜索） |
| **domain/** | 业务域，可 mock 单测 |
| **plugins/** | 脑级插件，按类型注册（定时/实时/工作流/技能） |
| **config/api_config.py** | 统一管理 LLM、搜索接口，便于切换供应商 |

---

## 五、部署清单

### 环境变量（.env.prod）

| 变量 | 必填 | 说明 |
|------|------|------|
| DASHSCOPE_API_KEY | ✅ | 通义千问 |
| POSTGRES_PASSWORD | ✅ | 数据库密码 |
| DATABASE_URL | ✅ | 需与 POSTGRES_PASSWORD 一致 |
| REDIS_URL | ✅ | 生产用 `redis://redis:6379/0` |
| BAIDU_SEARCH_API_KEY | 否 | 未配置则搜索用 mock |

### 启动命令

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

### 服务端口

| 服务 | 端口 |
|------|------|
| 后端 API | 8000 |
| Grafana | 3000 |
| Prometheus | 9090 |

---

## 六、文档索引

| 文档 | 用途 |
|------|------|
| README.md | 项目简介 |
| docs/QUICK_START.md | 本地快速启动 |
| docs/DEPLOYMENT.md | ESC 部署 |
| docs/ENV_KEYS_REFERENCE.md | 环境变量 |
| docs/PROJECT_SUMMARY.md | 设计需求与能力 |
| docs/BRAIN_PLUGIN_ARCHITECTURE.md | 脑级插件架构 |
| docs/PLUGIN_DEVELOPMENT_GUIDE.md | 插件开发 |
| docs/DOCKER_TROUBLESHOOTING.md | Docker 排错 |
| TROUBLESHOOTING.md | 通用排错 |

---

## 七、本次清理

- 合并 `DOCKER_BUILD_TROUBLESHOOTING` 到 `DOCKER_TROUBLESHOOTING`
- 删除 `GRADIO_PYTHON314_FIX`、`OPTIMIZATION_2025`、`REFACTORING_SUMMARY`
- 更新 `diagnose_chat.py` 移除已废弃的 mode 参数
- 新增 `DEPLOYMENT.md`、`PROJECT_FINAL_SUMMARY.md`

---

**最后更新**：2026-01-26
