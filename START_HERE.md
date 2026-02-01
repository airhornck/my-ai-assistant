# 🚀 快速启动指南

**当前状态**：数据库和 Redis 已启动，后端容器正在启动中。

---

## ✅ 当前服务状态

运行以下命令检查：
```bash
docker ps
```

你应该看到：
- `ai_assistant_postgres_dev` - Up (healthy) ✅
- `ai_assistant_redis_dev` - Up (healthy) ✅  
- `ai_assistant_app_prod` - Up (health: starting) ⏳

**等待 30-60 秒**让后端容器完全启动（health: healthy）。

---

## 🎯 方案选择

### 推荐：方案 A - 使用 Docker 生产容器

**优点**：一键启动，无需配置

**步骤**：

1. **等待后端容器健康**（30-60秒）
   ```bash
   docker ps --filter name=app_prod
   # 等待显示 Up (healthy)
   ```

2. **测试后端**
   ```bash
   # 在浏览器打开
   http://localhost:8000/docs
   
   # 或命令行测试
   curl http://localhost:8000/health
   ```

3. **启动前端**
   ```bash
   python frontend/app_enhanced.py
   ```

4. **访问前端**
   ```
   http://localhost:7860
   ```

---

### 备选：方案 B - 本地开发模式

**优点**：支持代码热重载，方便调试

**步骤**：

1. **停止生产容器**
   ```bash
   docker stop ai_assistant_app_prod
   ```

2. **确保数据库和 Redis 运行**
   ```bash
   docker compose -f docker-compose.dev.yml up -d
   ```

3. **在新终端启动后端**
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   
   **等待看到**：
   ```
   INFO:     Application startup complete.
   INFO:main:✅ 所有服务初始化成功
   ```

4. **在另一个终端启动前端**
   ```bash
   python frontend/app_enhanced.py
   ```

---

## 🔍 验证服务

### 检查后端健康

```bash
# Windows PowerShell
Invoke-WebRequest http://localhost:8000/health

# 或用 Python
python -c "import requests; print(requests.get('http://localhost:8000/health').json())"
```

**期望输出**：
```json
{
  "status": "healthy",
  "services": {
    "database": "healthy",
    "redis": "healthy",
    "workflow": "healthy",
    "ai_service": "healthy"
  }
}
```

### 检查前端 API

```bash
python -c "import requests; print(requests.get('http://localhost:8000/api/v1/frontend/session/init').json())"
```

**期望输出**：
```json
{
  "success": true,
  "user_id": "frontend_user_...",
  "session_id": "...",
  "thread_id": "..."
}
```

---

## ⏱️ 当前建议

**由于生产容器已启动**，我建议：

1. **等待 1 分钟**让容器完全启动
2. **直接启动前端**：
   ```bash
   python frontend/app_enhanced.py
   ```
3. 如果前端仍报 404，检查后端健康状态：
   ```bash
   # 在浏览器打开
   http://localhost:8000/docs
   ```

---

## 🆘 如果仍有问题

请运行以下命令并提供输出：

```bash
# 1. 检查所有容器
docker ps -a

# 2. 检查后端健康
curl http://localhost:8000/health

# 3. 查看后端日志
docker logs ai_assistant_app_prod --tail 50
```

---

**提示**：生产容器启动较慢（需要初始化数据库表、连接 Redis 等），通常需要 30-60 秒才能完全 ready。请耐心等待 `(healthy)` 状态出现。
