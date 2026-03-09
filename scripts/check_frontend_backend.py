#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
前端依赖的后端接口检查：用于上传前验证前端可用的 API 均正常。
检查：健康检查、会话初始化、记忆列表、报告下载路径。
使用：先启动后端，再运行 python scripts/check_frontend_backend.py
"""
from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests")
    sys.exit(1)

# 与 frontend/config.py 默认一致
BASE_URL = os.getenv("BACKEND_URL", os.getenv("BASE_URL", "http://localhost:8000")).rstrip("/")
TIMEOUT = 15


def main() -> int:
    print("=" * 60)
    print("前端依赖后端接口检查")
    print("=" * 60)
    print(f"BASE_URL = {BASE_URL}\n")

    errors = []

    # 1. 健康检查
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=TIMEOUT)
        if r.status_code != 200:
            errors.append(f"GET /health -> {r.status_code}")
        else:
            print("[OK] GET /health")
    except Exception as e:
        errors.append(f"GET /health 连接失败: {e}")
        print("[FAIL] GET /health 连接失败，请先启动后端")
        if errors:
            print("\n".join(errors))
        return 1

    # 2. 会话初始化（前端对话入口）
    try:
        r = requests.get(f"{BASE_URL}/api/v1/frontend/session/init", timeout=TIMEOUT)
        if r.status_code != 200:
            errors.append(f"GET /api/v1/frontend/session/init -> {r.status_code}")
        else:
            data = r.json()
            if not data.get("user_id"):
                errors.append("session/init 未返回 user_id")
            else:
                print("[OK] GET /api/v1/frontend/session/init")
    except Exception as e:
        errors.append(f"session/init: {e}")
        print(f"[FAIL] GET /api/v1/frontend/session/init: {e}")

    # 3. 记忆列表（前端记忆 Tab）
    try:
        r = requests.get(
            f"{BASE_URL}/api/v1/memory",
            params={"user_id": "check_frontend_user"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            errors.append(f"GET /api/v1/memory -> {r.status_code}")
        else:
            body = r.json()
            if not body.get("success") and body.get("error"):
                errors.append(f"GET /api/v1/memory: {body.get('error')[:80]}")
            else:
                print("[OK] GET /api/v1/memory?user_id=...")
    except Exception as e:
        errors.append(f"memory: {e}")
        print(f"[FAIL] GET /api/v1/memory: {e}")

    # 4. 报告下载路径存在（接口存在即可，404 为无文件）
    try:
        r = requests.get(f"{BASE_URL}/api/v1/reports/__nonexistent__.docx", timeout=TIMEOUT)
        # 404 表示路由存在、仅文件不存在
        if r.status_code not in (200, 404):
            errors.append(f"GET /api/v1/reports/{{filename}} -> {r.status_code}")
        else:
            print("[OK] GET /api/v1/reports/{filename} 路由可用")
    except Exception as e:
        errors.append(f"reports: {e}")
        print(f"[FAIL] GET /api/v1/reports/{{filename}}: {e}")

    print()
    if errors:
        print("=" * 60)
        for e in errors:
            print(f"  - {e}")
        print("=" * 60)
        return 1
    print("=" * 60)
    print("前端依赖的后端接口检查通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
