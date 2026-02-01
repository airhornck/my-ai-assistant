# 使用生产数据库运行本地 uvicorn

当使用 `docker-compose.prod.yml` 启动生产环境后，若需在本地运行 `uvicorn main:app --reload` 进行调试，请按以下步骤操作。

## 前提

- 已执行：`docker compose --env-file .env.prod -f docker-compose.prod.yml up -d`
- 生产 compose 已为 postgres 和 redis 配置端口映射（5432、6379 暴露到主机）

## 步骤

### 1. 重新创建容器（应用端口修改后）

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

若修改了端口等配置，可能需要加 `--force-recreate`：

```powershell
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate
```

### 2. 使用开发用 .env（连接 localhost）

本地 uvicorn 需要连接 `localhost:5432` 和 `localhost:6379`，不能使用 `.env.prod` 中的 `postgres:5432`、`redis:6379`。

确保 `.env` 中包含：

```env
# 必须使用 localhost，不能用 postgres/redis 主机名
DATABASE_URL=postgresql+asyncpg://postgres:MyDbPass123@localhost:5432/ai_assistant
REDIS_URL=redis://localhost:6379/0
```

密码 `MyDbPass123` 需与 `.env.prod` 中的 `POSTGRES_PASSWORD` 一致。

### 3. 停止生产 app 容器（避免端口 8000 冲突）

```powershell
docker stop ai_assistant_app_prod
```

### 4. 启动本地 uvicorn

```powershell
uvicorn main:app --reload
```

应用会通过 localhost 连接生产环境的 postgres 和 redis。

## 常见错误

### OSError: Connect call failed ('127.0.0.1', 5432)

- **原因**：PostgreSQL 未暴露到主机，或容器未运行
- **处理**：
  1. 确认 `docker-compose.prod.yml` 中 postgres 有 `ports: - "5432:5432"`
  2. 执行 `docker ps` 确认 `ai_assistant_postgres_prod` 在运行
  3. 端口 5432 未被其他服务占用

### 密码认证失败 (password authentication failed)

- **原因**：`.env` 中的密码与容器中 PostgreSQL 的密码不一致
- **处理**：统一 `.env` 和 `.env.prod` 中的 `POSTGRES_PASSWORD` / `DATABASE_URL` 密码

### 端口 8000 已被占用

- **原因**：生产 app 容器仍在运行
- **处理**：`docker stop ai_assistant_app_prod`

## 另一种做法：使用开发 compose

若不想修改生产 compose，可单独启动开发用数据库和 Redis：

```powershell
# 先停止生产中的 postgres/redis（如有端口冲突）
docker stop ai_assistant_postgres_prod ai_assistant_redis_prod

# 启动开发 compose（暴露 5432、6379）
docker compose -f docker-compose.dev.yml up -d

# 使用 .env（需与 docker-compose.dev.yml 中的密码一致，默认为 postgres）
uvicorn main:app --reload
```

注意：`docker-compose.dev.yml` 默认密码为 `postgres`，需确保 `.env` 中 `DATABASE_URL` 使用相同密码。
