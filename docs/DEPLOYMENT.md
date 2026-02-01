# 阿里云 ESC 部署指南

本文档说明如何在阿里云云服务器 ECS 上部署 AI 营销助手。

## 一、前置要求

- 阿里云 ECS 实例（推荐 2 核 4G 及以上）
- 已安装 Docker 与 Docker Compose
- 已准备 `.env.prod` 配置文件

## 二、快速部署

### 1. 上传代码

```bash
# 从 Git 克隆
git clone <your-repo-url> my_ai_assistant
cd my_ai_assistant
```

### 2. 配置环境变量

```bash
# 复制生产环境模板
cp .env.prod.example .env.prod

# 编辑配置，必填项：
# - DASHSCOPE_API_KEY（阿里云通义千问）
# - POSTGRES_PASSWORD
# - DATABASE_URL（密码需与 POSTGRES_PASSWORD 一致）
nano .env.prod
```

### 3. 启动服务

```bash
# 构建并启动（首次需构建镜像）
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

# 查看状态
docker compose -f docker-compose.prod.yml ps
```

### 4. 验证

```bash
# 健康检查
curl http://localhost:8000/health

# API 文档
# 浏览器访问 http://<ECS公网IP>:8000/docs
```

## 三、安全配置

### 1. 防火墙

- 开放 8000（后端）、3000（Grafana，可选）、9090（Prometheus，可选）
- 建议仅内网暴露 5432（PostgreSQL）、6379（Redis）

### 2. 环境变量

- 切勿将 `.env.prod` 提交到 Git
- 生产环境使用强密码

### 3. 域名与 HTTPS（可选）

- 使用 Nginx 反向代理
- 配置 SSL 证书（Let's Encrypt 或阿里云证书）

## 四、前端部署

### 方式 A：同一 ECS 运行 Gradio 前端

```bash
# 安装依赖后运行
pip install -r requirements.txt
python frontend/app_enhanced.py

# 访问 http://<ECS公网IP>:7860
# 需在 frontend/config.py 或环境变量中设置 BACKEND_URL 为后端地址
```

### 方式 B：前端单独部署

- 将 `BACKEND_URL` 指向后端 ECS 公网 IP 或域名
- 确保后端 CORS 允许前端域名

## 五、故障排查

参考 `docs/DOCKER_TROUBLESHOOTING.md`。

## 六、资源与 Key 配置

| 配置项 | 说明 | 获取地址 |
|--------|------|----------|
| DASHSCOPE_API_KEY | 通义千问（必填） | https://dashscope.console.aliyun.com/ |
| DEEPSEEK_API_KEY | DeepSeek（可选） | https://platform.deepseek.com/ |
| BAIDU_SEARCH_API_KEY | 百度搜索（可选，未配置则用 mock） | https://console.bce.baidu.com/qianfan/ |

详见 `docs/ENV_KEYS_REFERENCE.md`。
