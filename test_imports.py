# test_imports.py - 用于检查所有核心模块是否能正常导入，无语法错误
print("=== 开始基础导入测试 ===\n")

try:
    print("1. 正在导入数据库模块...")
    from database import Base, get_db, create_tables
    print("   ✅ 数据库模块导入成功")

    print("2. 正在导入会话管理模块...")
    from memory.session_manager import SessionManager
    print("   ✅ 会话管理模块导入成功")

    print("3. 正在导入工作流模块...")
    from workflows.basic_workflow import build_basic_workflow, State
    print("   ✅ 工作流模块导入成功")

    print("4. 正在导入AI服务模块...")
    from services.ai_service import SimpleAIService
    print("   ✅ AI服务模块导入成功")

    print("5. 正在导入主应用模块...")
    # 注意：导入FastAPI应用本身有时会执行代码，我们只做最轻量导入
    from main import app
    print("   ✅ 主应用模块导入成功")

    print("\n=== 所有模块导入成功！===")
    print("提示：这仅代表代码无语法和导入路径错误。")
    print("下一步请运行‘本地API启动’进行功能测试。")

except ModuleNotFoundError as e:
    print(f"\n❌ 模块未找到错误: {e}")
    print("可能原因：1) 模块文件不存在 2) 模块名拼写错误 3) 文件不在Python搜索路径中")
except ImportError as e:
    print(f"\n❌ 导入错误: {e}")
    print("可能原因：1) 文件内存在语法错误 2) 依赖未安装 3) 导入的类/函数名错误")
except Exception as e:
    print(f"\n❌ 发生未知错误: {e}")
    print("请检查以上堆栈跟踪信息。")