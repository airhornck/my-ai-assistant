# 使用官方 Python 3.11 镜像作为基础（更稳定，你指定的3.14可能过新）
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，确保 Python 输出直接显示在容器日志中
ENV PYTHONUNBUFFERED=1

# 首先复制依赖文件
COPY requirements.txt .

# 安装依赖，使用国内镜像加速（阿里云）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 复制项目所有代码
COPY . .

# 容器启动时运行的命令（与 docker-compose 中的 command 一致）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]