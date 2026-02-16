# AI 营销助手

智能内容分析、生成与评估 API，支持用户画像、记忆系统与多插件扩展。

## 功能特性

- **意图识别**：闲聊分类、自定义提取、多轮交叉意图
- **记忆系统**：短期记忆、长期记忆、上下文窗口、标签更新
- **内容生成**：文案创作、短视频脚本、热点分析、诊断评估
- **插件扩展**：热点插件、诊断插件、生成插件

## 技术栈

- **后端**：FastAPI + SQLAlchemy + Redis
- **AI 模型**：阿里云 Qwen3-max（分析/生成）、Dashscope 嵌入
- **数据库**：PostgreSQL + Redis
- **部署**：Docker Compose

## 快速开始

### 1. 配置环境

```bash
# 复制环境配置
copy .env.prod.example .env.prod

# 编辑 .env.prod，设置必要的 API Key
```

### 2. 启动服务

```bash
# 使用 Docker Compose 启动所有服务
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

# 或本地开发
uvicorn main:app --reload --port 8000
```

### 3. API 调用

```bash
# 健康检查
curl http://localhost:8000/health

# 深度分析接口
curl -X POST http://localhost:8000/api/v1/analyze-deep/raw \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test001", "raw_input": "帮我推广华为手机"}'
```

## 测试

```bash
# 运行综合测试（所有场景）
python scripts/test_comprehensive/runner.py

# 只运行意图识别测试
python scripts/test_comprehensive/runner.py --intent
```

## 项目结构

```
├── core/              # 核心模块（意图处理、插件中心）
├── services/         # 服务层（AI、记忆、热点刷新）
├── workflows/        # 工作流（分析、生成）
├── domain/           # 领域模型（内容分析、生成）
├── plugins/          # 插件实现
├── scripts/          # 测试脚本
├── config/           # 配置文件
└── docs/            # 文档
```

## 环境变量

关键环境变量见 `.env.prod`：

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` | 阿里云 API Key |
| `DATABASE_URL` | PostgreSQL 连接地址 |
| `REDIS_URL` | Redis 连接地址 |

## 文档

- [部署指南](./docs/DEPLOYMENT.md)
- [环境变量参考](./docs/ENV_KEYS_REFERENCE.md)
- [测试计划](./docs/TEST_PLAN_MEMORY_INTENT.md)
