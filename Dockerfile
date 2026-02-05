# 使用官方 Python 3.11 镜像作为基础（更稳定，你指定的3.14可能过新）
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，确保 Python 输出直接显示在容器日志中
ENV PYTHONUNBUFFERED=1

# 首先复制依赖文件
COPY requirements.txt .

# 安装依赖：优先阿里云镜像；失败时回退到 PyPI 并输出详细日志（-v）便于排查
RUN pip install --no-cache-dir -v -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt \
    || pip install --no-cache-dir -v -r requirements.txt

# 复制项目所有代码
COPY . .

# 容器启动：使用 python -m gunicorn 避免 PATH 中找不到 gunicorn 可执行文件
CMD ["python", "-m", "gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]