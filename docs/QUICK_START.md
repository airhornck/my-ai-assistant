# 快速开始

## 前置要求

- Docker Desktop（用于 Postgres + Redis）
- Python 3.11+
- Git

## 1. 克隆项目

```bash
git clone <repo-url>
cd my_ai_assistant
```

## 2. 配置环境

**生产/一键部署**（Docker 跑全部服务）：

```bash
copy .env.prod.example .env.prod
# 编辑 .env.prod，填入 DASHSCOPE_API_KEY、POSTGRES_PASSWORD
```

**本地开发**（Docker 仅跑数据库与 Redis）：

```bash
copy .env.dev.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY
```

## 3. 启动服务

**方式 A：Docker 一键部署**

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

等待约 30 秒。

**方式 B：本地开发**

```bash
docker compose -f docker-compose.dev.yml up -d
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## 4. 验证部署

```bash
curl http://localhost:8000/health
```

返回中含 `"status":"healthy"` 表示成功。可访问 http://localhost:8000/docs 查看 Swagger。

## 5. 首次调用

```bash
# 深度分析
curl -X POST http://localhost:8000/api/v1/analyze-deep/raw \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test001", "raw_input": "你好"}'

# Lumina 四模块能力接口（GET）
curl "http://localhost:8000/api/v1/capabilities/content-direction-ranking?platform=xiaohongshu"
```

## 6. 测试与验证

```bash
# 综合测试
python scripts/test_comprehensive/runner.py

# 四模块能力接口验证（需先启动服务）
python scripts/verify_capability_apis.py
```

## 常见问题

### 服务启动失败

```bash
# 查看日志
docker logs ai_assistant_app_prod

# 重启服务
docker compose --env-file .env.prod -f docker-compose.prod.yml restart
```

### API 请求超时

检查 `DASHSCOPE_API_KEY` 是否正确配置。

### 数据库连接失败

确保 PostgreSQL 容器正常运行：
```bash
docker ps | grep postgres
```

### 本地开发端口被占用

若 8000 被占用，可先停止 prod 应用容器：`docker stop ai_assistant_app_prod`，再启动 uvicorn。
