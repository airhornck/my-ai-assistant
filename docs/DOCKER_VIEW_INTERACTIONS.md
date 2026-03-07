# 在 Docker 环境中查看用户交互记录

用户每条对话（用户输入 + AI 回复）会写入 **PostgreSQL** 表 `interaction_histories`；会话/线程元数据在 **Redis**。数据在数据库容器内，不在 app 镜像里。下面说明如何进容器查看。

---

## 一、交互记录在哪儿

| 内容           | 存储位置        | 说明 |
|----------------|-----------------|------|
| 每条用户消息与 AI 回复 | PostgreSQL 表 `interaction_histories` | 主要查询对象 |
| 会话/线程元数据     | Redis 键 `session:*`、`user:*:threads`、`thread:*:sessions` | 可选，用于排查会话链 |

表 `interaction_histories` 字段：`id`, `user_id`, `session_id`, `user_input`, `ai_output`, `created_at`, `user_rating`, `user_comment`。

---

## 二、进 Postgres 容器查每条交互（推荐）

生产 Compose 里 Postgres 容器名为 `ai_assistant_postgres_prod`，数据库名一般为 `ai_assistant`，用户为 `postgres`（密码来自 `.env.prod` 的 `POSTGRES_PASSWORD`）。

**1. 进入 Postgres 容器的 psql：**

```bash
docker exec -it ai_assistant_postgres_prod psql -U postgres -d ai_assistant
```

**2. 在 psql 里查最近 20 条交互（摘要）：**

```sql
SELECT id, user_id, session_id,
       left(user_input, 80) AS user_input,
       left(ai_output, 80) AS ai_output,
       created_at
FROM interaction_histories
ORDER BY created_at DESC
LIMIT 20;
```

**3. 按用户查：**

```sql
SELECT id, session_id, user_input, ai_output, created_at
FROM interaction_histories
WHERE user_id = '你的user_id'
ORDER BY created_at DESC
LIMIT 50;
```

**4. 按会话查：**

```sql
SELECT id, user_input, ai_output, created_at
FROM interaction_histories
WHERE session_id = '你的session_id'
ORDER BY created_at ASC;
```

**5. 一条命令不进入交互式 psql（在主机执行）：**

```bash
docker exec ai_assistant_postgres_prod psql -U postgres -d ai_assistant -c "SELECT id, user_id, session_id, left(user_input, 50) AS user_input, left(ai_output, 50) AS ai_output, created_at FROM interaction_histories ORDER BY created_at DESC LIMIT 20;"
```

若使用开发 Compose，容器名可能不同（如 `ai_assistant_postgres`），把上面命令里的 `ai_assistant_postgres_prod` 换成实际容器名即可。

---

## 三、进 Redis 容器看会话/线程键（可选）

Redis 容器名为 `ai_assistant_redis_prod`。

**1. 进入 redis-cli：**

```bash
docker exec -it ai_assistant_redis_prod redis-cli
```

**2. 查看所有 session 键：**

```bash
KEYS session:*
```

**3. 查看某用户的对话链列表：**

```bash
KEYS user:*:threads
LRANGE user:某个user_id:threads 0 -1
```

**4. 查看某 thread 下的 session 列表：**

```bash
LRANGE thread:某个thread_id:sessions 0 -1
```

**5. 查看某条 session 内容（若为 Hash/String）：**

```bash
HGETALL session:某个session_id
# 或
GET session:某个session_id
```

---

## 四、从 App 容器内用 Python 查（可选）

若不想进 Postgres 容器，可在 **app 容器**内用项目已有的数据库连接查（需容器内能解析 `DATABASE_URL`，Compose 下一般为 `postgres:5432`）。

```bash
docker exec -it ai_assistant_app_prod python3 -c "
import asyncio
from sqlalchemy import text
from database import engine

async def run():
    async with engine.connect() as conn:
        r = await conn.execute(text('''
            SELECT id, user_id, session_id, user_input, ai_output, created_at
            FROM interaction_histories
            ORDER BY created_at DESC
            LIMIT 20
        '''))
        for row in r:
            print(row)

asyncio.run(run())
"
```

---

## 五、容器名速查

| 环境     | Postgres 容器名              | Redis 容器名                 | App 容器名                 |
|----------|-----------------------------|------------------------------|----------------------------|
| 生产 Compose | `ai_assistant_postgres_prod` | `ai_assistant_redis_prod`    | `ai_assistant_app_prod`    |
| 开发 Compose | 见 `docker-compose.dev.yml` 中 service 名，多为 `postgres` / `redis`，容器名可能带项目前缀 | 同上 | 见 `docker-compose.dev.yml` |

不确定容器名时，在主机执行：

```bash
docker ps --format "table {{.Names}}\t{{.Image}}"
```

找到 postgres/redis/app 对应名称后，把上面命令里的容器名替换即可。
