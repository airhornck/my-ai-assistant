"""
创建 user_memory_items 表（记忆系统优化方案步骤1）。
若使用应用启动时的 create_tables，则无需单独运行本脚本；
本脚本供在未启动完整应用时单独建表使用。
"""
import asyncio
import sys

# 确保项目根在 path 中
sys.path.insert(0, str(__file__.replace("\\", "/").rsplit("/", 1)[0].rsplit("/", 1)[0]))

from database import engine, create_tables


async def main() -> None:
    await create_tables(engine)
    print("user_memory_items 表已就绪（create_tables 已执行）")


if __name__ == "__main__":
    asyncio.run(main())
