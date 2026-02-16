# 环境变量参考

## 必需变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `DASHSCOPE_API_KEY` | 阿里云 API Key | `sk-xxxx` |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 | `MyDbPass123` |
| `DATABASE_URL` | 数据库连接串 | 见下方 |
| `REDIS_URL` | Redis 连接串 | `redis://redis:6379/0` |

## 数据库配置

```bash
# 生产环境（Docker 内）
DATABASE_URL=postgresql+asyncpg://postgres:MyDbPass123@postgres:5432/ai_assistant

# 本地开发
DATABASE_URL=postgresql+asyncpg://postgres:MyDbPass123@localhost:5432/ai_assistant
```

## Redis 配置

```bash
# 生产环境
REDIS_URL=redis://redis:6379/0

# 本地开发
REDIS_URL=redis://localhost:6379/0
```

## 可选变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `API_BASE_URL` | API 基础地址 | `http://127.0.0.1:8000` |
| `API_TIMEOUT` | API 超时时间 | `120` 秒 |
| `DATABASE_POOL_SIZE` | 数据库连接池大小 | `5` |
| `DATABASE_MAX_OVERFLOW` | 最大溢出连接 | `10` |

## 搜索配置

```bash
SEARCH_PROVIDER=baidu
BAIDU_SEARCH_API_KEY=your-api-key
```
