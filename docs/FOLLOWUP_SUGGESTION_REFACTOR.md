# 后续建议模块重构方案

## 一、现状与问题

### 1.1 当前流程

1. **生成**（`workflows/follow_up_suggestion.py`）  
   - LLM 自由文本输出：含「专家建议」「引导句」等自然语言描述，以及可选的 `STEP: generate/analyze` 行。  
   - 仅做一步解析：`_parse_step_from_response()` 抽出 STEP 行，返回 `(正文, step_name)`。

2. **消费**（`workflows/meta_workflow.py` 的 `compilation_node`）  
   - 拿到一整段「正文」后，用大量字符串规则做清洗：  
     去掉「**专家建议**：」「专家建议：」「**：」「引导句：」、  
     再找「建议」且排除「专家建议」、再清「引导句：」等。  
   - 逻辑复杂、易受 LLM 措辞变化影响，难以维护。

### 1.2 核心问题

- **格式未约束**：LLM 输出是自由文本，标签和结构不统一（**专家建议**：、专家建议：、引导句：等）。  
- **职责错位**：展示层在做「语义清洗」（猜哪里是建议、哪里是引导），而不是「格式解析」。  
- **难以扩展**：若以后要加「下一步按钮文案」「多条建议」等，当前一串 replace/find 会更难写。

---

## 二、目标

- **输出规范**：后续建议的「内容形状」在生成端就固定下来，便于解析和展示。  
- **逻辑简单**：消费端只做「解析 + 拼装」，不做任何「去掉某某前缀」的语义清洗。  
- **易扩展**：新增字段（如多条建议、按钮文案）只需改协议与模板，不改清洗逻辑。

---

## 三、方案：结构化输出 + 固定展示

### 3.1 输出规范（生成端约定）

**要求 LLM 输出 JSON，且仅包含以下字段（便于解析、避免多余键）：**

```json
{
  "suggestion_body": "1～3 条具体建议的纯正文，不要任何标签或前缀（如「专家建议：」）。若为终止点，可为一句收尾。",
  "guide_sentence": "可选。一句引导用户续聊的话；若无或已终止点则为空字符串。",
  "step": "generate | analyze | "
}
```

- **suggestion_body**（必填）：  
  只写建议/收尾的**纯正文**。  
  禁止写「专家建议：」「由于…建议…」等前缀或解释，避免消费端再做截断。
- **guide_sentence**（可选）：  
  若有可执行下一步，写一句引导语（如「如果您有具体方向，可以告诉我」）；  
  否则为空字符串 `""`。  
  禁止写「引导句：」前缀，只写内容。
- **step**：  
  `"generate"` / `"analyze"` / `""`（空表示终止点，不设 suggested_next_plan）。

**解析约定：**

- 若 LLM 返回的是一段文本而非 JSON：  
  先尝试按「最后一行为 STEP: xxx」解析出 `step`，其余视为 `suggestion_body`，`guide_sentence` 置空（兼容旧行为）。  
- 若解析到合法 JSON：  
  取 `suggestion_body`、`guide_sentence`、`step`，缺失则用默认值（空字符串 / 空 step）。

### 3.2 展示规范（消费端）

- **报告中的「后续建议」区块**（在 `meta_workflow.py` 的 compilation_node 内）固定为：
  1. 分隔线：`---`
  2. 标题：`## 后续建议`
  3. 正文：`suggestion_body`（不再做任何 strip/replace）
  4. 若 `guide_sentence` 非空：换行后追加 `guide_sentence`
- **suggested_next_plan**：  
  仅当 `step in ("generate", "analyze")` 时设置，逻辑与现有一致。

消费端**不再**出现：
- 去掉「专家建议：」「引导句：」「**：」等逻辑；
- 查找「建议」并截断「建议」后内容的逻辑。

### 3.3 模块职责划分

| 模块 | 职责 |
|------|------|
| **follow_up_suggestion** | 构造 prompt，要求 JSON 输出；解析 JSON（或 fallback 旧格式）；返回 `(suggestion_body, guide_sentence, step)` 或兼容的 `(suggestion_text, step_name)`。 |
| **meta_workflow（compilation_node）** | 根据返回的 body/guide/step 拼装「后续建议」区块并写入 report；设置 suggested_next_plan。不做任何正文清洗。 |

---

## 四、实施步骤建议

1. **follow_up_suggestion.py**  
   - 增加「要求输出 JSON」的 system/user prompt（可保留一段说明：字段含义、禁止写标签等）。  
   - 增加 `_parse_followup_response(text) -> tuple[str, str, str]`：  
     优先尝试 `json.loads` 取 `suggestion_body`, `guide_sentence`, `step`；  
     失败则回退到现有 `_parse_step_from_response`，把整段正文当作 `suggestion_body`，`guide_sentence` 为空。  
   - `get_follow_up_suggestion` 的返回值改为三元组 `(suggestion_body, guide_sentence, step)`，或为兼容暂保留 `(suggestion_body + guide_sentence 的拼接, step)` 并由调用方按新协议解析；推荐直接改为三元组，调用方改一次即可。

2. **meta_workflow.py**  
   - 在 compilation_node 中：  
     - 调用 `get_follow_up_suggestion` 得到 `(body, guide, step)`。  
     - 若有内容：  
       - 追加 `\n\n---\n\n## 后续建议\n`；  
       - 追加 `body`；  
       - 若 `guide` 非空，追加 `\n\n` + `guide`；  
     - 删除所有「专家建议」「引导句」「建议」相关的清洗代码。  
   - suggested_next_plan 仍按 `step in ("generate", "analyze")` 设置。

3. **兼容与回退**  
   - 若 LLM 经常不返回 JSON，可保留 fallback：按当前自由文本解析，只取「STEP 行」和「其余正文」，整段作为 suggestion_body 展示（至少不再做复杂清洗）。  
   - 上线后可根据日志中 JSON 解析成功率再决定是否收紧 prompt 或加重试。

---

## 五、小结

- **规范输出**：用 JSON 明确 `suggestion_body`、`guide_sentence`、`step`，禁止在正文中写「专家建议：」「引导句：」等标签。  
- **简化逻辑**：消费端只做「解析 → 按字段拼装」，不再做任何基于自然语言的清洗。  
- **易维护易扩展**：以后新增字段（如 `buttons`、`tips`）只需扩展 JSON 与展示模板即可。

如认可该方案，可按上述步骤在 `follow_up_suggestion.py` 与 `meta_workflow.py` 中落地实现；需要的话我可以再补一版具体的 prompt 示例与解析代码片段。
