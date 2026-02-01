# 插件模板包
#
# 使用方式：
# 1. 复制 plugin_template 目录并重命名为你的插件名（如 my_plugin）
# 2. 在 workflow.py 中实现 build_workflow(config)，定义节点并返回 CompiledGraph
# 3. 在应用启动时（或通过发现机制）调用：
#    get_registry().register_workflow("your_plugin_name", your_build_workflow)
#    get_registry().init_plugins(config)  # 由 main.py lifespan 统一调用
#
# 详见 plugin_template/README.md 与 workflow.py 内注释。

from plugin_template.workflow import build_workflow

__all__ = ["build_workflow"]
