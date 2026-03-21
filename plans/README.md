# plans 包：Plan 模板与注册中心

Plan 相关逻辑统一放在本目录，便于维护与扩展。

## 目录结构

```
plans/
  __init__.py       # 统一入口：get_plan, resolve_template_id, 模板 ID 常量, Intake 字段等
  registry.py       # 注册中心：register, get_plan, resolve_template_id, list_template_ids
  intake.py         # IP 打造 Intake 必填/可选字段
  templates/
    __init__.py     # 加载时注册各固定 Plan，并导出模板 ID 常量
    ip_diagnosis.py
    account_building.py
    content_matrix.py
    capability_content_direction_ranking.py
    capability_case_library.py
    capability_content_positioning_matrix.py
    capability_weekly_decision_snapshot.py
```

每个固定 Plan 对应一个文件，新增固定 Plan 采用**两步添加**（类似插件）：见下方「新增固定 Plan」。

## 使用方式

- **获取步骤**：`from plans import get_plan` → `get_plan(template_id)`
- **解析模板 ID**：`from plans import resolve_template_id` → `resolve_template_id(intent, ip_context)`
- **Intake 字段**：`from plans import IP_INTAKE_REQUIRED_KEYS, IP_INTAKE_OPTIONAL_KEYS`
- **模板 ID 常量**：`from plans import TEMPLATE_IP_DIAGNOSIS, CAPABILITY_TEMPLATE_*` 等

## 新增固定 Plan（两步添加，类似插件）

1. **新建文件**：在 `plans/templates/` 下新建 `<name>.py`，定义模板 ID 常量、**`register(..., name=展示名, description=...)`**、`steps`、可选的 `intent_selector`，并在文件末尾调用 `register_plan()`。
2. **注册**：在 `plans/templates/__init__.py` 中增加一行：`import plans.templates.<name>  # noqa: F401`，并在 `__all__` 与 re-export 区补充该模块导出的常量（若需对外暴露）。

详见项目根目录下 `plan_template/README.md` 与 `plan_template/example_plan.py`。
