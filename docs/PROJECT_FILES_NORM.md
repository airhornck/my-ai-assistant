# 项目文件与测试规范性说明

本文档说明项目目录规范、测试/脚本归属，以及已清理的无用文件，便于后续维护与协作。

---

## 一、目录结构规范

### 1. 根目录

- **保留的入口与配置**：`main.py`、`database.py`、`pytest.ini`、`requirements.txt`、`.env.*` 示例、`README.md`、`START_HERE.md`、`TROUBLESHOOTING.md` 等。
- **根目录测试**：仅保留**与核心模块直接对应的**测试，便于单独运行：
  - `test_intent_agent.py`：IntentAgent 行为测试
  - `test_planning_agent.py`：PlanningAgent 行为测试  
  - 其余接口/流程测试请使用 `scripts/` 下脚本或 pytest（见下）。
- **工具脚本**：
  - `check_backend.py`：后端健康与依赖诊断（Docker、Redis、API），可保留在根目录便于直接执行。
  - `fix_port_conflict.ps1`：Windows 端口冲突处理，按需使用。

### 2. 测试与脚本（`scripts/`）

- **pytest 发现**：`pytest.ini` 中 `testpaths = scripts`，即 **pytest 只收集 `scripts/` 下的 `test_*.py`**，根目录的 `test_*.py` 不会被 pytest 发现，仅用于手动运行。
- **推荐约定**：
  - **自动化/CI 用**：放在 `scripts/`，命名为 `test_*.py` 或 `run_*_regression.py` 等，通过 `pytest scripts/` 或 `python scripts/xxx.py` 执行。
  - **能力接口**：统一用 `scripts/test_four_capability_apis.py`（支持 `--quick` 仅测澄清）、`scripts/test_capability_apis.py`（pytest 集成）进行测试，勿在根目录新增重复的能力接口小脚本。
  - **流程/回归**：如 `scripts/test_refactor_intent_memory_planning.py`、`scripts/run_regression_user_simulation.py`、`scripts/run_memory_regression.py` 等，保留在 `scripts/`。
- **脚本说明**：详见 `scripts/README.md`。

### 3. 核心代码

- **编排与领域**：`workflows/`（meta_workflow、reasoning_loop、子图）、`domain/`（content、memory）、`core/`（intent、brain_plugin_center、deps 等）。
- **意图**：`core/intent/` 下以 `processor.py`、`intent_agent.py`、`planning_agent.py`、`marketing_intent_classifier.py`、`types.py` 等为主；**不再保留与 processor 逻辑重复的 `test.py`**（已删除）。

### 4. 文档

- **设计与对比**：`docs/` 下保留架构、对接、测试计划等（如 `ORCHESTRATION_MEMORY_VS_OPENCLAW.md`、`INTENT_DESIGN_ALIGNMENT.md`、`TEST_PLAN.md`）。
- **临时/日志**：如 `docs/DAILY_LOG.md` 为项目日志，可按需保留或迁移到团队约定位置。

### 5. 生成文件与忽略

- **测试结果**：`scripts/test_comprehensive/test_results.json`、`test_results_partial.json` 由 `runner.py` 生成，已加入 `.gitignore`，不提交。
- **数据与缓存**：`data/`、`__pycache__/`、`.env` 等按 `.gitignore` 忽略。

---

## 二、已删除文件（本次清理）

### 根目录一次性/重复测试脚本（已删）

| 文件 | 说明 |
|------|------|
| `test_simple.py` | 单次请求 analyze-deep/raw，与 scripts 回归重复 |
| `test_simple2.py` | 同上 |
| `test_err.py` | 单场景错误打印，一次性调试用 |
| `test_loop.py` | 单次 analyze-deep/raw 请求 |
| `test_new.py` | 3 条固定 case，与 test_final/verify_fix 重复 |
| `test_final.py` | 与 test_new.py 内容相同 |
| `verify_fix.py` | 与 test_new.py 内容相同 |
| `test_full_flow.py` | 2～3 条 frontend/chat 请求，与 scripts 内流程测试重复 |
| `test_full_flow2.py` | 同上 |
| `test_multi_cases.py` | 多 case 调用 analyze-deep/raw，可由 scripts 回归覆盖 |
| `test_capabilities.py` | 4 个能力接口简单请求，由 `scripts/test_four_capability_apis.py` 替代 |

以上均未在 pytest 中发现，且功能可由 `scripts/` 下脚本或 `scripts/test_refactor_intent_memory_planning.py`、`scripts/test_four_capability_apis.py` 等覆盖。

### 重复/死代码（已删）

| 文件 | 说明 |
|------|------|
| `core/intent/test.py` | 与 `core/intent/processor.py` 逻辑重复（COMMAND_PATTERN、SHORT_CASUAL_REPLIES、意图分类等），且无其他模块引用，已删除。实际使用的为 `processor.py`。 |
| `workflows/langgraph_orchestrator.py` | 设计参考用编排器，未接入 main/meta_workflow，逻辑已由 meta_workflow 覆盖，已删除。 |

### 生成的测试结果（已删并加入 .gitignore）

| 文件 | 说明 |
|------|------|
| `scripts/test_comprehensive/test_results.json` | runner 生成，已加入 .gitignore |
| `scripts/test_comprehensive/test_results_partial.json` | 同上 |

---

## 三、保留的根目录测试

- **`test_intent_agent.py`**：对 IntentAgent 的意图分类与置信度等测试，可 `python test_intent_agent.py` 单独运行。
- **`test_planning_agent.py`**：对 PlanningAgent 的规划步骤与插件列表测试，可 `python test_planning_agent.py` 单独运行。

如需扩展自动化测试，建议在 `scripts/` 下新增 `test_*.py` 或 `run_*_regression.py`，并在 `scripts/README.md` 中补充说明。

---

## 四、后续建议

1. **新增接口/流程测试**：优先放在 `scripts/`，命名 `test_*.py` 或 `run_*_regression.py`，并在 `scripts/README.md` 中登记。
2. **临时调试脚本**：尽量放在 `scripts/` 或本地忽略，避免提交到根目录的 `test_*.py`。
3. **意图/处理器逻辑**：仅保留在 `core/intent/processor.py` 及现有 intent 子模块，避免再新增与 processor 重复的 `test.py` 式文件。
4. **生成物**：测试结果、报告等生成路径建议在 `.gitignore` 中统一忽略，避免误提交。
