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

## 搜索配置（Web Search）

网络检索（竞品、热点、爆款文案等）由 `core/search/web_searcher.py` 实现。**未配置时使用 mock 搜索（返回占位内容，非真实检索）**。要启用真实网络搜索，需同时设置：

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SEARCH_PROVIDER` | 供应商：`mock`（占位）或 `baidu`（百度千帆） | `mock` |
| `BAIDU_SEARCH_API_KEY` | 百度千帆 API Key（千帆控制台获取） | 未设置则强制使用 mock |

```bash
# 启用百度千帆 Web Search（真实检索）
SEARCH_PROVIDER=baidu
BAIDU_SEARCH_API_KEY=your-qianfan-api-key
```

未设置 `BAIDU_SEARCH_API_KEY` 时，系统会自动降级为 mock，并在日志中提示。
