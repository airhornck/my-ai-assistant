# 故障排除指南

本文档记录常见问题及解决方案。

---

## 问题 1：前端报错 404 "session/init not found"

### 错误信息
```
初始化会话失败: HTTP 404:404 Client Error: Not Found for url: http://localhost:8000/api/v1/frontend/session/init
```

### 原因
1. **后端服务未启动**
2. **数据库认证失败**（最常见）
3. **端口被占用**（Docker 生产容器已运行）

### 解决步骤

#### 1. 检查后端健康状态

```bash
# 在浏览器或命令行访问
curl http://localhost:8000/health

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

#### 2. 如果数据库 unhealthy（密码错误）

**症状**：
```json
"database": "unhealthy: password authentication failed for user 'postgres'"
```

**解决**：
```bash
# 1. 停止并删除所有容器和数据卷
docker compose -f docker-compose.dev.yml down -v

# 2. 重新启动（会创建新的数据库）
docker compose -f docker-compose.dev.yml up -d

# 3. 等待 10 秒让 PostgreSQL 完全启动
# 然后检查状态
docker compose -f docker-compose.dev.yml ps
```

**检查结果**：
```
NAME                        STATUS
ai_assistant_postgres_dev   Up (healthy)
ai_assistant_redis_dev      Up (healthy)
```

#### 3. 如果端口被占用

**症状**：
- `uvicorn` 启动失败："Address already in use"
- 或者后端是生产容器（`ai_assistant_app_prod`）

**检查**：
```bash
docker ps | findstr 8000
```

**解决方案 A**：停止生产容器，使用本地开发
```bash
# 停止生产容器
docker stop ai_assistant_app_prod

# 启动本地后端
uvicorn main:app --reload
```

**解决方案 B**：直接使用生产容器
```bash
# 生产容器已包含后端，无需启动 uvicorn
# 直接启动前端即可
python frontend/app_enhanced.py
```

#### 4. 重启后端服务

如果你在运行 `uvicorn main:app --reload`：

```bash
# 在运行 uvicorn 的终端按 Ctrl+C 停止
# 然后重新启动
uvicorn main:app --reload
```

**预期输出**（成功）：
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:main:✅ 所有服务初始化成功
INFO:     Application startup complete.
```

---

## 问题 2：Gradio 启动报错（Python 3.14）

### 错误信息
```
TypeError: BlockContext.__init__() got an unexpected keyword argument 'theme'
TypeError: Chatbot.__init__() got an unexpected keyword argument 'type'
```

### 原因
Gradio 6.0.x 在 Python 3.14 上的兼容性问题。

### 解决方案
✅ **代码已修复**，移除了不兼容的参数。

如果仍有问题：
1. 确保使用最新代码（`git pull`）
2. 或参考 [PYTHON314_COMPATIBILITY.md](PYTHON314_COMPATIBILITY.md)

---

## 问题 3：LangChain Pydantic V1 警告

### 警告信息
```
UserWarning: Core Pydantic V1 functionality isn't compatible with Python 3.14
```

### 说明
- 这是 LangChain 的已知问题
- **不影响任何功能**
- 可以安全忽略

### 消除方法（可选）
使用 Python 3.13：
```bash
pyenv install 3.13.1
pyenv local 3.13.1
pip install -r requirements.txt
```

---

## 问题 4：Docker 容器无法启动

### 症状
```bash
docker compose -f docker-compose.dev.yml ps
# 显示 Exited 或 Unhealthy
```

### 解决步骤

#### 1. 查看容器日志
```bash
# PostgreSQL 日志
docker compose -f docker-compose.dev.yml logs postgres

# Redis 日志
docker compose -f docker-compose.dev.yml logs redis
```

#### 2. 常见问题

**端口冲突**：
```bash
# 检查是否有其他服务占用 5432（PostgreSQL）或 6379（Redis）
netstat -ano | findstr :5432
netstat -ano | findstr :6379

# 如果有，停止占用的服务或修改 docker-compose.dev.yml 端口
```

**权限问题**：
```bash
# 确保 Docker Desktop 正在运行
# 确保你有管理员权限
```

#### 3. 完全重置
```bash
# 停止所有容器
docker compose -f docker-compose.dev.yml down -v

# 删除孤立容器
docker compose -f docker-compose.dev.yml down --remove-orphans

# 重新启动
docker compose -f docker-compose.dev.yml up -d
```

---

## 问题 5：API Key 错误

### 错误信息
```
dashscope.common.error.AuthenticationError: Invalid API-key
```

### 解决步骤

#### 1. 检查 .env 文件
```bash
# 查看当前配置
type .env | findstr DASHSCOPE
```

#### 2. 更新 API Key
```bash
# 编辑 .env 文件
notepad .env

# 修改为你的真实 API Key
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

#### 3. 重启后端
```bash
# 如果是 uvicorn（按 Ctrl+C 后）
uvicorn main:app --reload

# 如果是 Docker
docker compose -f docker-compose.prod.yml restart app
```

---

## 诊断工具

### 快速健康检查
```bash
# 后端健康
curl http://localhost:8000/health

# 前端 API
curl http://localhost:8000/api/v1/frontend/session/init

# 容器状态
docker compose -f docker-compose.dev.yml ps
```

### 完整诊断
```bash
# 运行诊断脚本（修复编码问题后）
python check_backend.py
```

---

## 最佳实践

### 开发环境启动顺序

1. **启动数据库和 Redis**：
   ```bash
   docker compose -f docker-compose.dev.yml up -d
   ```

2. **检查容器健康**：
   ```bash
   docker compose -f docker-compose.dev.yml ps
   # 等待显示 (healthy)
   ```

3. **配置环境变量**：
   ```bash
   copy .env.dev .env  # 首次
   notepad .env        # 填写 DASHSCOPE_API_KEY
   ```

4. **启动后端**：
   ```bash
   uvicorn main:app --reload
   ```

5. **启动前端**（新终端）：
   ```bash
   python frontend/app_enhanced.py
   ```

### 停止服务

```bash
# 1. 停止前端（在前端终端按 Ctrl+C）

# 2. 停止后端（在后端终端按 Ctrl+C）

# 3. 停止 Docker 容器
docker compose -f docker-compose.dev.yml down

# 如需删除数据（⚠️ 会丢失数据库内容）
docker compose -f docker-compose.dev.yml down -v
```

---

## 常用命令速查

| 任务 | 命令 |
|------|------|
| 启动开发环境 | `docker compose -f docker-compose.dev.yml up -d` |
| 查看容器状态 | `docker compose -f docker-compose.dev.yml ps` |
| 查看容器日志 | `docker compose -f docker-compose.dev.yml logs -f` |
| 停止容器 | `docker compose -f docker-compose.dev.yml down` |
| 重置容器 | `docker compose -f docker-compose.dev.yml down -v` |
| 启动后端 | `uvicorn main:app --reload` |
| 启动前端 | `python frontend/app_enhanced.py` |
| 检查健康 | `curl http://localhost:8000/health` |
| 测试前端 API | `python scripts/test_frontend_api.py` |

---

## 获取帮助

如果问题仍未解决：

1. **查看完整日志**：
   ```bash
   # 后端日志（如果用 uvicorn）
   # 直接在终端查看

   # Docker 容器日志
   docker compose -f docker-compose.dev.yml logs -f
   ```

2. **检查版本**：
   ```bash
   python --version
   docker --version
   docker compose version
   ```

3. **查看相关文档**：
   - [快速启动指南](docs/QUICK_START.md)
   - [Python 3.14 兼容性](PYTHON314_COMPATIBILITY.md)
   - [前端 API 文档](docs/FRONTEND_API.md)

---

**最后更新**：2026-01-30  
**维护者**：AI 营销助手团队
