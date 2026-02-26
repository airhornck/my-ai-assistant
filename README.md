# AI 营销助手

智能内容分析、生成与评估 API，支持用户画像、记忆系统与多插件扩展；提供 Lumina 风格四模块能力接口（内容方向榜单、案例库、内容定位矩阵、每周决策快照）。

## 功能特性

- **意图识别**：闲聊分类、自定义提取、多轮交叉意图
- **记忆系统**：短期记忆、长期记忆、上下文窗口、标签更新
- **内容生成**：文案创作、短视频脚本、热点分析、诊断评估
- **插件扩展**：热点插件、诊断插件、生成插件、Lumina 四模块相关插件
- **能力接口**：内容方向榜单、定位决策案例库、内容定位矩阵、每周决策快照（[Lumina 产品](https://lumina-ai.cn/product) 对应能力）

## 技术栈

- **后端**：FastAPI + SQLAlchemy + Redis
- **AI 模型**：阿里云 Qwen3-max（分析/生成）、DashScope 嵌入
- **数据库**：PostgreSQL + Redis
- **部署**：Docker Compose

## 快速开始

### 方式一：Docker 一键部署（生产/演示）

```bash
# 1. 复制环境配置并编辑（填入 DASHSCOPE_API_KEY 等）
copy .env.prod.example .env.prod

# 2. 启动所有服务（API + Postgres + Redis）
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

# 3. 健康检查
curl http://localhost:8000/health
```

### 方式二：本地开发（Docker 仅跑数据库与 Redis）

```bash
# 1. 启动 Redis 与 PostgreSQL
docker compose -f docker-compose.dev.yml up -d

# 2. 配置环境（复制 .env.dev.example 为 .env，填入 API Key）
copy .env.dev.example .env

# 3. 安装依赖并启动应用
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### API 调用示例

```bash
# 健康检查
curl http://localhost:8000/health

# 深度分析
curl -X POST http://localhost:8000/api/v1/analyze-deep/raw \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test001", "raw_input": "帮我推广华为手机"}'

# Lumina 四模块能力接口（GET）
curl "http://localhost:8000/api/v1/capabilities/content-direction-ranking?platform=xiaohongshu"
curl "http://localhost:8000/api/v1/capabilities/case-library?page=1&page_size=10"
curl "http://localhost:8000/api/v1/capabilities/content-positioning-matrix"
curl "http://localhost:8000/api/v1/capabilities/weekly-decision-snapshot"
```

## 测试与验证

```bash
# 综合测试（意图、记忆、全流程、插件）
python scripts/test_comprehensive/runner.py

# 四模块能力接口验证（需先启动服务）
python scripts/verify_capability_apis.py
# 仅验证案例库与矩阵（不调 AI）：SKIP_SLOW=1 python scripts/verify_capability_apis.py
```

## 项目结构

```
├── core/              # 核心（意图、插件中心、能力依赖）
├── services/         # 服务层（AI、记忆、热点刷新）
├── workflows/        # 工作流（元工作流、分析/生成编排）
├── domain/           # 领域模型（内容分析、生成）
├── plugins/          # 插件（热点、诊断、Lumina 四模块等）
├── routers/          # API 路由（数据与知识、能力接口）
├── scripts/          # 测试与验证脚本
├── config/           # 配置文件
└── docs/             # 文档
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key（必需） |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `REDIS_URL` | Redis 连接串 |
| `BAIDU_SEARCH_API_KEY` | 百度搜索（可选，用于网络检索） |

详见 [环境变量参考](./docs/ENV_KEYS_REFERENCE.md)。请勿将 `.env`、`.env.dev`、`.env.prod` 提交到仓库（已列入 `.gitignore`）。

## 文档

| 文档 | 说明 |
|------|------|
| [快速开始](./docs/QUICK_START.md) | 克隆、配置、启动、验证 |
| [部署指南](./docs/DEPLOYMENT.md) | Docker 部署与本地开发 |
| [对外 API 参考](./docs/API_REFERENCE.md) | 接口清单与 Lumina 四模块能力接口 |
| [Lumina 四模块映射](./docs/LUMINA_MODULES_MAPPING.md) | 四模块与分析脑插件对应关系 |
| [环境变量参考](./docs/ENV_KEYS_REFERENCE.md) | 环境变量说明 |
| [Git 上传准备](./docs/GIT_UPLOAD.md) | 提交信息与上传步骤 |

## License

见仓库根目录 LICENSE 文件（如有）。
