#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
记忆模块全面回归测试：依次执行步骤1/2/3/5/7 的测试用例。
需 REDIS_URL、DATABASE_URL；步骤2 部分用例可选 DASHSCOPE_API_KEY。
使用：python scripts/run_memory_regression.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Windows 控制台 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

MEMORY_TEST_FILES = [
    "scripts/test_memory_optimization_step1.py",
    "scripts/test_memory_optimization_step2.py",
    "scripts/test_memory_optimization_step3.py",
    "scripts/test_memory_optimization_step5.py",
    "scripts/test_memory_optimization_step7.py",
]


def main() -> int:
    print("=" * 60)
    print("记忆模块全面回归测试")
    print("=" * 60)
    if not os.getenv("DATABASE_URL"):
        print("警告: 未设置 DATABASE_URL，步骤1/3/5/7 的集成用例将被跳过。")
    if not os.getenv("REDIS_URL"):
        print("警告: 未设置 REDIS_URL，部分依赖 Redis 的用例可能被跳过。")
    print()

    cmd = [
        sys.executable, "-m", "pytest",
        "-v",
        "--tb=short",
        "-q",
        *MEMORY_TEST_FILES,
    ]
    result = subprocess.run(cmd, cwd=str(ROOT))
    print()
    print("=" * 60)
    if result.returncode == 0:
        print("记忆回归测试：全部通过")
    else:
        print("记忆回归测试：存在失败或跳过（见上方输出）")
    print("=" * 60)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
