# 示例插件：展示如何使用 plugin_template 编写可被 meta_workflow 编排调用的子工作流。
# 注册名建议与规划步骤名一致（如 "示例步骤"），或使用默认 content 回退。

from plugin_template.example_plugin.workflow import build_workflow

__all__ = ["build_workflow"]
