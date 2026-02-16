# 部署指南

## 环境要求

- Docker & Docker Compose
- Python 3.11+（本地开发）
- PostgreSQL 15+
- Redis 7+

## Docker 部署

### 1. 配置环境变量

```bash
# 复制生产环境配置
copy .env.prod.example .env.prod

# 编辑 .env.prod，设置必要的 API Key
```

### 2. 启动服务

```bash
# 启动所有服务
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

# 查看服务状态
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

### 3. 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| app | 8000 | 主 API 服务 |
| postgres | 5432 | 数据库 |
| redis | 6379 | 缓存 |
| prometheus | 9090 | 监控 |
| grafana | 3000 | 可视化 |

### 4. 验证部署

```bash
# 检查 API 健康
curl http://localhost:8000/health

# 查看日志
docker logs ai_assistant_app_prod
```

## 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 PostgreSQL 和 Redis
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:15
docker run -d -p 6379:6379 redis:7

# 启动应用
uvicorn main:app --reload --port 8000
```

## 常用命令

```bash
# 重启服务
docker compose --env-file .env.prod -f docker-compose.prod.yml restart

# 停止服务
docker compose --env-file .env.prod -f docker-compose.prod.yml down

# 查看日志
docker logs -f ai_assistant_app_prod
```
