# 测试配置
import os
import sys
from pathlib import Path

# 加载 .env（在导入项目模块前）
_root = Path(__file__).resolve().parent.parent
for _f in (".env", ".env.dev", ".env.prod"):
    _p = _root / _f
    if _p.exists():
        from dotenv import load_dotenv
        load_dotenv(_p, override=True)
        break

# API 配置（默认 127.0.0.1 避免 localhost IPv6 解析问题）
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
API_TIMEOUT = 120.0  # 秒

# 用户前缀定义
USER_PREFIXES = {
    "short_term": "mem_st_",     # 短期记忆
    "long_term": "mem_lt_",      # 长期记忆
    "context": "mem_ctx_",       # 上下文窗口
    "tag": "mem_tag_",           # 标签更新
    "casual": "mem_cas_",        # 闲聊分类
    "extract": "mem_ext_",       # 自定义提取
    "cross": "mem_int_",         # 交叉意图
    "full": "mem_full_",         # 完整创作
    "clarify": "mem_clar_",      # 澄清流程
    "hotspot": "mem_hot_",       # 热点插件
    "diagnosis": "mem_diag_",    # 诊断插件
    "generator": "mem_gen_",     # 生成插件
}

# 并发配置
CONCURRENT_USERS = 5  # 每批并发用户数
REQUEST_INTERVAL_MS = 500  # 请求间隔（毫秒）
REQUEST_INTERVAL_JITTER = 300  # 随机抖动

# Token 预算
MAX_TOTAL_TOKENS = 100000

# 重试配置
MAX_RETRIES = 2
RETRY_DELAY_SEC = 3

# 启动前检查：需要运行中的 Docker 容器（prod 环境）
REQUIRED_SERVICES = [
    "ai_assistant_postgres_prod",
    "ai_assistant_redis_prod",
    "ai_assistant_app_prod",
]
