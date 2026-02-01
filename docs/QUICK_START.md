# 快速启动指南

本文档说明如何在本地开发环境快速启动 AI 营销助手项目。

---

## 前置要求

- ✅ Python 3.11+ （推荐 3.13，支持 3.14 但有限制）
- ✅ Docker Desktop（用于运行数据库和 Redis）
- ✅ 通义千问 API Key（从[阿里云控制台](https://dashscope.console.aliyun.com/)获取）

---

## 方式一：本地开发（推荐）

### 1. 启动数据库和 Redis（Docker）

```bash
# 启动 PostgreSQL + Redis
docker compose -f docker-compose.dev.yml up -d

# 查看状态（等待 healthy）
docker compose -f docker-compose.dev.yml ps

# 查看日志
docker compose -f docker-compose.dev.yml logs -f
```

**预期输出**：
```
NAME                           STATUS          PORTS
ai_assistant_postgres_dev      Up (healthy)    0.0.0.0:5432->5432/tcp
ai_assistant_redis_dev         Up (healthy)    0.0.0.0:6379->6379/tcp
```

### 2. 配置环境变量

```bash
# 复制开发环境配置模板
cp .env.dev .env

# 编辑 .env 文件，填写你的 API Key
# Windows: notepad .env
# Mac/Linux: nano .env
```

**必须修改的配置**：
```bash
DASHSCOPE_API_KEY=your_actual_api_key_here  # ⚠️ 必填
```

### 3. 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

**Python 3.14 用户注意**：
- Gradio 可能有兼容性问题，已修复（失去默认主题）
- 如遇其他问题，建议使用 Python 3.13

### 4. 启动后端

```bash
# 开发模式（自动重载）
uvicorn main:app --reload --port 8000

# 或直接运行
python -m uvicorn main:app --reload
```

**预期输出**：
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
INFO:main:应用启动完成
```

**访问**：
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 5. 启动前端（可选）

**新开一个终端**：

```bash
# 激活虚拟环境
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux

# 启动增强版前端（推荐）
python frontend/app_enhanced.py

# 或启动基础版
python frontend/app.py
```

**访问**：http://localhost:7860

---

## 方式二：完整 Docker 部署

### 1. 准备环境文件

```bash
# 复制生产环境配置模板
cp .env.prod .env.prod

# 编辑配置
notepad .env.prod  # Windows
# nano .env.prod    # Mac/Linux
```

**必须修改**：
```bash
DASHSCOPE_API_KEY=your_actual_api_key_here
POSTGRES_PASSWORD=strong_password_here  # 生产环境请设置强密码
```

### 2. 启动所有服务

```bash
# 构建并启动（首次需要构建镜像）
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build

# 查看状态
docker compose -f docker-compose.prod.yml ps

# 查看日志
docker compose -f docker-compose.prod.yml logs -f app
```

### 3. 访问服务

- API：http://localhost:8000
- Prometheus 指标：http://localhost:8000/metrics

---

## 常见问题

### Q1: 数据库连接失败（10061 错误）

**错误信息**：
```
[Errno 10061] Connect call failed ('127.0.0.1', 5432)
```

**原因**：PostgreSQL 未启动

**解决**：
```bash
# 检查 Docker 容器状态
docker compose -f docker-compose.dev.yml ps

# 如果未启动
docker compose -f docker-compose.dev.yml up -d

# 查看容器日志
docker compose -f docker-compose.dev.yml logs postgres
```

### Q2: Redis 连接失败

**错误信息**：
```
redis.exceptions.ConnectionError: Error connecting to Redis
```

**解决**：
```bash
# 启动 Redis
docker compose -f docker-compose.dev.yml up -d redis

# 测试连接
docker exec -it ai_assistant_redis_dev redis-cli ping
# 应该返回: PONG
```

### Q3: Pydantic V1 警告（LangChain）

**警告信息**：
```
UserWarning: Core Pydantic V1 functionality isn't compatible with Python 3.14
```

**说明**：
- 这是 LangChain 的已知问题（依赖 Pydantic V1 兼容层）
- **不影响功能**，可以忽略
- LangChain 团队正在迁移到 Pydantic V2

**临时解决**（可选）：
- 使用 Python 3.13（完全兼容）
- 或等待 LangChain 更新

### Q4: API Key 未配置

**错误信息**：
```
dashscope.common.error.AuthenticationError: Invalid API-key
```

**解决**：
1. 检查 `.env` 文件中的 `DASHSCOPE_API_KEY`
2. 确保 API Key 有效（在[阿里云控制台](https://dashscope.console.aliyun.com/)查看）
3. 重启后端服务

### Q5: Gradio 启动失败（Python 3.14）

**错误信息**：
```
TypeError: BlockContext.__init__() got an unexpected keyword argument 'theme'
```

**解决**：
- 已在代码中修复
- 如仍有问题，参考根目录 `PYTHON314_COMPATIBILITY.md`

---

## 测试验证

### 1. 测试后端 API

```bash
# 健康检查
curl http://localhost:8000/health

# 会话初始化
curl http://localhost:8000/api/v1/frontend/session/init

# Chat 模式测试
curl -X POST http://localhost:8000/api/v1/frontend/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好",
    "user_id": "test_user",
    "mode": "chat"
  }'
```

### 2. 自动化测试

```bash
# 运行测试脚本
python scripts/test_frontend_api.py
```

---

## 停止服务

### 本地开发模式

```bash
# 停止后端（在运行 uvicorn 的终端按 Ctrl+C）

# 停止前端（在运行 gradio 的终端按 Ctrl+C）

# 停止 Docker 容器
docker compose -f docker-compose.dev.yml down

# 停止并删除数据卷（⚠️ 会删除数据库数据）
docker compose -f docker-compose.dev.yml down -v
```

### Docker 部署模式

```bash
# 停止所有服务
docker compose -f docker-compose.prod.yml down

# 停止并删除数据卷
docker compose -f docker-compose.prod.yml down -v
```

---

## 开发建议

### 推荐开发流程

1. **启动基础服务**：`docker-compose.dev.yml`（数据库 + Redis）
2. **本地运行后端**：`uvicorn main:app --reload`（方便调试、查看日志）
3. **本地运行前端**：`python frontend/app_enhanced.py`（方便修改界面）

### 优点

- ✅ 后端自动重载（修改代码即时生效）
- ✅ 可以使用 IDE 断点调试
- ✅ 日志输出清晰
- ✅ 数据库隔离（容器化）

### 目录结构

```
my_ai_assistant/
├── main.py                    # 后端入口
├── frontend/
│   ├── app.py                # 基础前端
│   └── app_enhanced.py       # 增强前端（推荐）
├── .env                      # 本地环境配置（从 .env.dev 复制）
├── .env.dev                  # 开发环境配置模板
├── .env.prod                 # 生产环境配置模板
├── docker-compose.dev.yml    # 开发环境 Docker
└── docker-compose.prod.yml   # 生产环境 Docker
```

---

## 下一步

- 📖 阅读 [API 文档](FRONTEND_API.md)
- 🎨 自定义 Gradio 界面（修改 `frontend/app_enhanced.py`）
- 🧪 运行测试：`python scripts/test_frontend_api.py`
- 🚀 部署到生产：参考 `docker-compose.prod.yml`

---

**最后更新**：2026-01-26  
**问题反馈**：请在项目 Issues 中提交
