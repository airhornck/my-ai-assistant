# Docker 热重载模式使用指南

本文档介绍如何使用热重载模式进行开发，实现**代码修改后自动生效，无需重新构建镜像**。

## 🎯 两种模式对比

| 特性 | 生产模式 (`docker-compose.prod.yml`) | 热重载模式 (`docker-compose.hotreload.yml`) |
|------|--------------------------------------|---------------------------------------------|
| **代码位置** | 打包在镜像内 | 通过 Volume 挂载 |
| **修改代码后** | 需要重新 `docker compose build` | 保存即生效，自动热重载 |
| **启动方式** | `gunicorn` 多进程 | `uvicorn --reload` 单进程 |
| **性能** | 高（适合生产） | 中等（适合开发） |
| **适用场景** | 生产部署、高并发 | 开发调试、快速迭代 |
| **构建时间** | 每次修改代码后需重新构建 | 仅需构建一次 |

## 🚀 快速开始

### 1. 确保环境配置文件存在

```bash
# Linux/macOS
cp .env.prod.example .env.prod

# Windows PowerShell
Copy-Item .env.prod.example .env.prod
```

编辑 `.env.prod`，至少配置 `DASHSCOPE_API_KEY`。

### 2. 启动热重载模式

**使用脚本（推荐）：**

```bash
# Linux/macOS
./scripts/hotreload.sh up

# Windows PowerShell
.\scripts\hotreload.ps1 up
```

**或使用原始命令：**

```bash
docker compose --env-file .env.prod -f docker-compose.hotreload.yml up -d
```

首次启动会自动构建镜像，这可能需要几分钟。

### 3. 验证服务

- 应用: http://localhost:8000
- API文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 4. 体验热重载

1. 修改任意 `.py` 文件（例如添加一个打印语句）
2. 保存文件
3. 查看日志，你会看到类似以下的输出：
   ```
   INFO:     Will watch for changes in these directories: ['/app']
   INFO:     Uvicorn running on http://0.0.0.0:8000
   INFO:     Reloading process...
   ```
4. 刷新浏览器，修改已生效！

## 📋 常用命令

### Linux/macOS (使用脚本)

```bash
# 启动服务
./scripts/hotreload.sh up

# 停止服务
./scripts/hotreload.sh down

# 查看日志（带热重载提示）
./scripts/hotreload.sh logs

# 重新构建镜像（依赖变化时使用）
./scripts/hotreload.sh build

# 重启服务
./scripts/hotreload.sh restart

# 进入容器调试
./scripts/hotreload.sh shell

# 查看状态
./scripts/hotreload.sh status
```

### Windows PowerShell (使用脚本)

```powershell
# 启动服务
.\scripts\hotreload.ps1 up

# 停止服务
.\scripts\hotreload.ps1 down

# 查看日志
.\scripts\hotreload.ps1 logs

# 重新构建镜像
.\scripts\hotreload.ps1 build

# 重启服务
.\scripts\hotreload.ps1 restart

# 进入容器调试
.\scripts\hotreload.ps1 shell

# 查看状态
.\scripts\hotreload.ps1 status
```

### 原始 Docker Compose 命令

```bash
# 启动
docker compose --env-file .env.prod -f docker-compose.hotreload.yml up -d

# 停止
docker compose -f docker-compose.hotreload.yml down

# 查看日志
docker compose -f docker-compose.hotreload.yml logs -f app

# 重新构建
docker compose --env-file .env.prod -f docker-compose.hotreload.yml build --no-cache

# 重启
docker compose -f docker-compose.hotreload.yml restart
```

## 🔧 工作原理

### 代码挂载

热重载模式通过 Docker Volume 将宿主机的代码目录挂载到容器中：

```yaml
volumes:
  - .:/app           # 挂载项目根目录
  - /app/__pycache__ # 排除缓存目录
  - /app/.git        # 排除 Git 目录
  # ... 其他排除项
```

### 热重载机制

使用 `uvicorn` 的 `--reload` 选项监控文件变化：

```dockerfile
CMD ["uvicorn", "main:app", "--reload", "--reload-dir", "/app", ...]
```

当 `.py` 文件被修改并保存时，uvicorn 会自动重启应用，加载最新代码。

## ⚠️ 注意事项

### 1. 性能考虑
- 热重载模式使用单进程，不适合高并发场景
- 生产环境请使用 `docker-compose.prod.yml`（gunicorn 多进程）

### 2. 依赖变更
- 如果 `requirements.txt` 有变更，需要重新构建镜像：
  ```bash
  ./scripts/hotreload.sh build
  ```

### 3. 排除目录
- 以下目录不会被挂载到宿主机，使用容器内的版本：
  - `__pycache__`
  - `.git`
  - `.idea`
  - `data/knowledge_vectors`
  - `data/reports`
  - `venv` / `.venv`

### 4. 端口冲突
- 热重载模式使用与生产模式相同的端口（8000, 6379, 5432, 9090, 3000）
- 如果生产模式正在运行，需要先停止：
  ```bash
  docker compose -f docker-compose.prod.yml down
  ```

### 5. 数据库数据
- 热重载模式使用独立的数据卷（`postgres_data_hot`, `redis_data_hot`）
- 与生产模式的数据是隔离的

## 🐛 故障排查

### 问题：热重载不工作

**检查方法：**
1. 查看日志是否有 "Will watch for changes" 字样
2. 确认修改的是 `.py` 文件
3. 检查文件是否保存成功

**解决：**
```bash
# 重启服务
./scripts/hotreload.sh restart

# 或查看详细日志
./scripts/hotreload.sh logs
```

### 问题：依赖安装失败

**解决：**
```bash
# 重新构建镜像
./scripts/hotreload.sh build
```

### 问题：端口被占用

**解决：**
```bash
# 停止所有相关容器
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.hotreload.yml down

# 查看占用端口的进程
# Linux/macOS:
lsof -i :8000

# Windows:
netstat -ano | findstr :8000
```

## 📚 相关文件

| 文件 | 说明 |
|------|------|
| `docker-compose.hotreload.yml` | 热重载模式 Compose 配置 |
| `Dockerfile.hotreload` | 热重载模式 Dockerfile |
| `scripts/hotreload.sh` | Linux/macOS 管理脚本 |
| `scripts/hotreload.ps1` | Windows PowerShell 管理脚本 |
| `docker-compose.prod.yml` | 生产模式配置（高性能） |

## 💡 最佳实践

1. **开发阶段**：使用热重载模式，快速迭代
2. **测试阶段**：可以先使用热重载模式验证，再切换到生产模式测试性能
3. **生产部署**：使用 `docker-compose.prod.yml`，确保高并发性能
4. **团队协作**：热重载模式适合个人开发，提交代码前确保在生产模式下测试

---

如有问题，请参考 `TROUBLESHOOTING.md` 或查看容器日志。
