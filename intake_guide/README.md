# 用户友好引导模块（Intake Guide）

产品化实现「用户输入 → 字段抽取 → ip_context 更新 → 缺失字段? → 生成 pending_questions → 前端显示 → 用户回答 → 更新 ip_context → 下一轮」的引导流程。

## 设计要点

- **每轮只问 1～3 个关键问题**：`build_pending_questions(missing, max_questions=3)`
- **选项化 + 可跳过**：`QUESTION_MAP` 中配置 `options` 与 `optional`
- **实时回显已收集信息**：`format_echo(ip_context)` 供前端进度条/状态展示
- **ip_context 持久化**：`merge_context(existing, extracted)` 不覆盖已有非空值，支持多轮累积
- **可作为独立 Intake 组件**：前端仅依赖 `pending_questions`、`ip_context`、`phase` 即可渲染

## 目录与引用

```
intake_guide/
  __init__.py   # 对外 API
  config.py     # 必填/可选字段（REQUIRED_KEYS, OPTIONAL_KEYS）
  merge.py      # merge_context(existing, extracted)
  questions.py  # missing_required(ip_context), build_pending_questions(missing, intent, max_questions)
  echo.py       # format_echo(ip_context)
  README.md
```

- **workflows/ip_build_flow.py**：`intake_node` 使用 `merge_context`、`missing_required`、`build_pending_questions`
- **workflows/meta_workflow.py**：Plan 阶段合并抽取字段时使用 `intake_guide.merge_context`
- **main.py**：创作前门控：当 `needs_clarification` 且为创作意图时，用本模块生成 `pending_questions` 并写回 `phase=intake`、`ip_context`
- **plans/intake.py**：仅复出 `IP_INTAKE_REQUIRED_KEYS`、`IP_INTAKE_OPTIONAL_KEYS`（数据源为本模块 config）

## 使用示例

```python
from intake_guide import merge_context, missing_required, build_pending_questions, format_echo

ip_context = merge_context(session.get("ip_context"), {"topic": "产品推广"})
missing = missing_required(ip_context)
if missing:
    pending_questions = build_pending_questions(missing, intent="strategy_planning", max_questions=3)
    echo = format_echo(ip_context)
    # 返回 echo + pending_questions 给前端
```
