# 快速开始

## 前置要求

- Docker Desktop
- Python 3.11+
- Git

## 1. 克隆项目

```bash
git clone <repo-url>
cd my-ai-assistant
```

## 2. 配置环境

```bash
# 复制环境配置
copy .env.prod.example .env.prod

# 编辑配置，填入 API Key
notepad .env.prod
```

必需的配置：
- `DASHSCOPE_API_KEY`：阿里云 API Key
- `POSTGRES_PASSWORD`：数据库密码

## 3. 启动服务

```bash
# 使用 Docker 启动所有服务
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

等待服务启动完成（约 30 秒）。

## 4. 验证部署

```bash
# 检查 API 是否正常
curl http://localhost:8000/health
```

返回 `{"status":"ok"}` 表示成功。

## 5. 首次调用

```bash
curl -X POST http://localhost:8000/api/v1/analyze-deep/raw \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test001", "raw_input": "你好"}'
```

## 6. 运行测试

```bash
# 运行综合测试
python scripts/test_comprehensive/runner.py
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
