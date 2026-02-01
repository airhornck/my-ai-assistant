# Docker 故障排查

## 一、构建阶段

### 错误：parent snapshot does not exist / failed to prepare extraction snapshot

**原因**：Docker 构建缓存损坏，层引用失效。

**处理步骤**：
```powershell
docker builder prune -af
docker compose --env-file .env.prod -f docker-compose.prod.yml build --no-cache
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

### 警告：git was not found in the system

**原因**：BuildKit 尝试采集 git 信息，主机未安装 git 或未加入 PATH。

**方案**：可忽略；或安装 [Git for Windows](https://git-scm.com/download/win)；或临时禁用 BuildKit：
```powershell
$env:DOCKER_BUILDKIT=0
docker compose --env-file .env.prod -f docker-compose.prod.yml build --no-cache
```

---

## 二、运行阶段：app 容器 unhealthy

### 1. 查看应用日志

```bash
docker logs ai_assistant_app_prod
# 或
docker compose -f docker-compose.prod.yml logs app
```

### 2. 常见原因与处理

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 数据库连接失败 | POSTGRES_PASSWORD 与 DATABASE_URL 密码不一致 | 确保 .env.prod 中两者密码相同 |
| 数据库认证失败 | 数据卷首次创建时的密码与当前 .env.prod 不同 | 使用相同密码，或 `docker compose down -v` 后重建 |
| Redis 连接失败 | REDIS_URL 配置错误 | 生产环境使用 `redis://redis:6379/0`（服务名 redis） |
| DASHSCOPE_API_KEY 未配置 | Key 未填写或未传入容器 | 在 .env.prod 中正确配置 |

### 3. 密码一致性

- `POSTGRES_PASSWORD` 与 `DATABASE_URL` 中的密码**必须相同**
- 若数据卷已存在且曾用 `MyDbPass123` 初始化，后续修改密码会导致连接失败
- 处理：在 .env.prod 中统一密码，或 `docker compose down -v` 清空卷后重新初始化

### 4. 容器数量

- **6 个容器**：postgres, redis, app, memory-optimizer, prometheus, grafana
- app 失败时，依赖 app 的 prometheus 可能显示异常，属正常
