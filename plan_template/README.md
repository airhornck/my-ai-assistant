# Plan 模板开发指南

所有 Plan（固定 / 动态）均通过 **模板 ID** 引用，由 `plans.registry` 统一解析。新增或修改 Plan 时，请按本模板与约定操作。

## 一、概念

- **template_id**：唯一标识一个 Plan 模板，如 `ip_diagnosis`、`capability_content_direction_ranking`、`dynamic`。
- **name**：固定 Plan 的**对外展示名**（短标题，如「账号打造」），供用户文案、`get_template_meta()` 使用；注册时**建议必填**，缺省时回退为 `template_id`。
- **description**：补充说明（流程概要、文档/调试），可与 `name` 区分长短。
- **固定 Plan**：步骤在注册时写死，通过 `get_plan(template_id)` 直接返回步骤列表。
- **动态 Plan**：模板 ID 为 `dynamic`，由 LLM 根据意图与上下文在运行时生成步骤，仍写入 `plan_template_id="dynamic"` 保持引用一致。
- **意图选择器**：`intent_selector(intent, ip_context) -> bool`，用于在 IP 打造流程中根据意图/话题解析出应使用的固定模板 ID；无匹配时使用 `dynamic`。

**Plan 相关代码已统一放在项目根目录下的 `plans/` 包中；每个固定 Plan 一个文件，便于维护与扩展。**

## 二、结构说明

### 2.1 `register()` 模板级字段（元数据）

| 参数 | 说明 |
|------|------|
| `template_id` | 唯一 ID，会话与 API 中引用。 |
| **`name`** | **对外展示名**（短标题，如「账号打造」）；固定 Plan **建议必填**，缺省回退为 `template_id`。 |
| `description` | 流程概要、文档与调试说明，可与 `name` 区分长短。 |
| `plan_type` | `PLAN_TYPE_FIXED` / `PLAN_TYPE_DYNAMIC`。 |
| `steps` | 固定模板的步骤列表。 |
| `intent_selector` / `selector_priority` | 可选；IP 打造流程中自动匹配模板时使用。 |

### 2.2 `steps[]` 每一步

每个步骤为 `dict`，建议包含：

| 字段 | 说明 |
|------|------|
| `step` | 步骤类型：`memory_query`、`analyze`、`generate`、`casual_reply`、`web_search`、`evaluate`、或能力专用如 `case_library`。 |
| `plugins` | 插件名列表，如 `["content_direction_ranking"]`；无则 `[]`。 |
| `params` | 参数模板，如 `{"platform": ""}`，执行时由上下文填充。 |
| `reason` | 人类可读的步骤说明，用于日志与调试。 |

## 三、新增固定 Plan：两步添加（类似插件）

与插件开发一致，固定 Plan 采用 **两步添加**，无需改动其他业务文件。

### 步骤 1：新建 Plan 文件

在 `plans/templates/` 下新建 `<name>.py`（如 `my_feature_plan.py`），内容结构参考 `plan_template/example_plan.py`：

- 定义模板 ID 常量（如 `TEMPLATE_MY_FEATURE = "my_feature"`）。
- 在 `register(...)` 中填写 **`name=`**（展示名）与 **`description=`**（流程说明）。
- 定义 `steps` 列表。
- 若需在 IP 打造流程中按意图自动选中，实现 `_intent_selector(intent, ip_context) -> bool` 并传入 `register()`。
- 实现 `register_plan()`，内部调用 `plans.registry.register(...)`。
- **在文件末尾调用 `register_plan()`**，以便该模块被 import 时自动完成注册。

### 步骤 2：在模板包中注册

在 `plans/templates/__init__.py` 中：

1. 增加一行导入（触发注册）：  
   `import plans.templates.<name>  # noqa: F401`
2. 若需对外暴露该 Plan 的模板 ID 常量，在 `__init__.py` 中增加 re-export，并加入 `__all__`。

完成以上两步后，新固定 Plan 即可被 `get_plan(template_id)` 与（若配置了意图选择器）`resolve_template_id(intent, ip_context)` 使用。

## 四、统一引用方式

- **获取步骤**：`from plans import get_plan` → `steps = get_plan(template_id)`。
- **解析模板 ID**（IP 打造）：`from plans import resolve_template_id` → `template_id = resolve_template_id(intent, ip_context)`。
- **列表**：`from plans import list_template_ids` → `ids = list_template_ids()`。
- **元数据**：`from plans import get_template_meta` → `meta = get_template_meta(template_id)`（含 `name`、`description`、`template_id`、`type` 等）。

能力接口、IP 打造流程、会话状态中的 `plan_template_id` 一律使用上述 `template_id`，动态生成的 Plan 使用 `plan_template_id=PLAN_TEMPLATE_DYNAMIC`（即 `"dynamic"`）。

## 五、示例参考

- 固定模板 + 意图选择：`plans/templates/ip_diagnosis.py`、`account_building.py`、`content_matrix.py`。
- 固定模板、无选择器（接口直传 template_id）：`plans/templates/capability_content_direction_ranking.py` 等四能力文件。
- 开发模板占位：`plan_template/example_plan.py`。

## 六、常量与入口

- 动态模板 ID：`from plans import PLAN_TEMPLATE_DYNAMIC`（`"dynamic"`）。
- 模板类型：`from plans import PLAN_TYPE_FIXED`、`PLAN_TYPE_DYNAMIC`。
- 兼容入口：`config.ip_build_plan_templates` 仍转发自 `plans`，建议统一使用 `from plans import ...`。
