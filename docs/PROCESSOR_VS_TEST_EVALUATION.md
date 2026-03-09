# processor.py 与 test.py（重写版）对比评估

## 结论：**不建议用 test.py 替换现有 processor.py**

现有 `processor.py` 在意图质量、与主流程契约、可观测性上更优；test.py 更短但丢失了关键能力与兼容项。建议保留 processor.py；若希望简化，可在其基础上做局部重构而非整体替换。

---

## 一、差异对比摘要

| 维度 | processor.py（现有） | test.py（重写） |
|------|----------------------|------------------|
| **系统提示词** | 长版 `INTENT_CLASSIFY_SYSTEM`：文档/链接原则、五类意图说明、explicit_content_request 规则、用户自我介绍、输出格式 | 仅一句「你是意图分类器，请只输出 JSON 对象。」 |
| **意图合法性** | 仅接受 5 类意图，非法则回退为 `DEFAULT_INTENT` | 不校验，LLM 可能返回任意字符串 |
| **营销关键词修正** | 若判为 casual_chat 但含「推广/营销/文案/品牌…」或像产品提及 → 强制改为 free_discussion | 仅短句闲聊时用 `has_marketing_kw` 排除，长句无修正 |
| **简短闲聊** | `raw in SHORT_CASUAL_REPLIES and len(raw) <= 8` | `raw in SHORT_CASUAL_REPLIES and not has_marketing_kw`（逻辑不同） |
| **explicit_content_request** | 先取 LLM 结果，再用规则覆盖（规则只能置 True）；平台关键词在结构化/自由讨论下也置 True | 仅规则 + 平台关键词，完全不用 LLM 的 explicit 字段 |
| **返回契约** | 含 `analysis_plugin_result: None`，与 main 使用一致 | 无该字段（main 用 `.get()` 不报错，但契约不完整） |
| **document_query / command** | 对两种意图分别写 `structured_data`、`command` | 统一走一套 structured_data，command 仅早期 return 时设置 |
| **LLM 响应解析** | `text = (response.content or "").strip()` 再 `_parse_intent_response(text)`，兼容 Message 与字符串 | 直接 `_parse_intent_response(response.content)`，未统一 strip/兼容性 |
| **日志** | 规则闲聊、意图修正、最终 intent/explicit 等有 logger | 几乎无日志 |
| **JSON 解析失败** | `_parse_intent_response` 内 logger.warning | 静默返回 {} |

---

## 二、为何现有 processor 更优

### 1. 意图分类质量依赖系统提示词

- 现有长版提示词明确约束：文档/链接仅作补充、主推广对象从对话提取、casual_chat 与 free_discussion 的边界、explicit_content_request 的 true/false 规则、用户自我介绍提取等。
- test.py 仅一句提示，模型缺乏约束，易出现：文档场景误判、explicit 漏判/误判、闲聊与营销讨论混淆。

### 2. 与 main 的契约与行为一致

- `main.py` 会使用 `processed.get("analysis_plugin_result")`；processor 显式置为 `None`，语义清晰。
- document_query / command 分支下，processor 对 `structured_data` 与 `command` 的赋值与主流程预期一致；test.py 未区分意图，可能在某些分支下少填或填错。

### 3. 鲁棒性与可维护性

- 意图白名单 + 非法回退，避免下游拿到未知 intent。
- 营销关键词修正减少「用户明显在说推广却被判成闲聊」的情况。
- 日志便于线上排查与 A/B 对比。

### 4. 测试结果（当前代码）

- `scripts/test_intent_rules.py`：45/45 通过。
- `scripts/test_intent_classification.py`：16/18 通过（2 个为结构化请求用例，属 LLM 方差）。
- pytest：`test_intent_rules.py` + `test_intent_classification.py` 共 6 个用例全部通过。

---

## 三、若采用 test.py 会带来的问题

1. **意图与 explicit 质量下降**：无详细系统提示，文档/链接场景与 explicit 判断更容易出错。
2. **契约与分支行为**：缺少 `analysis_plugin_result`；document_query/command 的 structured_data 与 command 未单独处理，存在与主流程不一致风险。
3. **长句营销误判**：无「casual_chat + 营销关键词 → 改为 free_discussion」的修正，长句可能被误判为闲聊。
4. **可观测性变差**：几乎无日志，问题难以追溯。

---

## 四、建议

- **保留现有 `processor.py`**，不整体替换为 test.py。
- 若追求「更短、更清晰」：
  - 可在 processor 内部做局部重构（例如抽取小函数、合并重复的 structured_data 分支），但**保留**：
    - 长版 `INTENT_CLASSIFY_SYSTEM`
    - 意图白名单与营销关键词修正
    - `analysis_plugin_result` 及 document_query/command 的专门处理
    - 现有日志与解析兼容（response.content / strip）
- test.py 可作为「简化版参考」或单测里的对比基线，但不建议直接作为生产实现替换 processor.py。

---

## 五、相关调用与测试

- **直接使用**：`main.py`（InputProcessor）、`services/input_service.py`（重导出）、`core/intent/__init__.py`（重导出）。
- **测试**：`scripts/test_intent_rules.py`、`scripts/test_intent_classification.py`、`scripts/test_intent_full.py`、`scripts/benchmark_intent_performance.py`；`test_new_features.py` 中从 `services.input_service` 导入的 InputProcessor。
- 上述测试均针对当前 `processor.py` 行为；若替换为 test.py，需补全契约（如 analysis_plugin_result）并重新跑全部相关测试与主流程回归。
