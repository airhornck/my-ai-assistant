# "三脑"架构关系（重构后）

## 一、整体架构

```
用户请求
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│                    策略脑（Planning Brain）                        │
│                   构建思维链（Chain of Thought）                   │
│                                                                    │
│  职责：根据用户意图规划执行步骤                                    │
│  输出：plan = [步骤1, 步骤2, 步骤3, ...]                          │
│                                                                    │
│  示例：                                                            │
│    用户："推广降噪耳机，目标18-35岁"                               │
│    策略脑规划：                                                    │
│      1. web_search("降噪耳机竞品")                                 │
│      2. memory_query(用户偏好)                                     │
│      3. analyze(品牌+热点+搜索结果)                                │
│      4. generate(分析结果+B站规范)                                 │
│      5. evaluate(生成内容)                                         │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│                    编排层（Orchestration）                         │
│                   按思维链顺序执行各模块                           │
└──────────────────────────────────────────────────────────────────┘
    │
    ├─→ 搜索模块（web_search）        ← 新增
    │       └─ core/search/web_searcher.py
    │       └─ 检索竞品、热点、行业数据
    │
    ├─→ 记忆查询（memory_query）
    │       └─ domain/memory/service.py
    │       └─ 用户历史偏好、品牌事实
    │
    ├─→ 分析脑（analyze）
    │       └─ domain/content/analyzer.py
    │       └─ 品牌与热点关联度分析
    │
    ├─→ 生成脑（generate）
    │       └─ domain/content/generator.py
    │       └─ 根据分析生成推广文案
    │
    └─→ 评估脑（evaluate）
            └─ domain/content/evaluator.py
            └─ 四维度打分 + 改进建议
    │
    ▼
最终输出：推广文案 + 完整思考过程
```

---

## 二、各"脑"职责（重新定义）

### 1. 策略脑（Planning Brain）

**位置**：`workflows/meta_workflow.py` 的 `planning_node`

**职责**：
- 理解用户意图
- **构建思维链**（CoT）：规划需要哪些步骤
- 决定是否需要搜索、记忆查询等

**输入**：
- 用户请求（brand、product、topic、raw_query）

**输出**：
```json
[
  {"step": "web_search", "params": {"query": "..."}, "reason": "..."},
  {"step": "analyze", "params": {}, "reason": "..."},
  {"step": "generate", "params": {"platform": "B站"}, "reason": "..."},
  {"step": "evaluate", "params": {}, "reason": "..."}
]
```

**关键**：策略脑**不执行**，只规划。

---

### 2. 分析脑（Analyzer）

**位置**：`domain/content/analyzer.py`

**职责**：
- 分析品牌与热点**关联度**
- 可引用搜索结果、用户记忆

**输入**：
- ContentRequest（brand、product、topic）
- preference_context（可包含搜索结果）

**输出**：
```json
{
  "semantic_score": 85,
  "angle": "年轻群体科技感",
  "reason": "..."
}
```

**调用方**：编排层（orchestration_node）

---

### 3. 生成脑（Generator）

**位置**：`domain/content/generator.py`

**职责**：
- 根据分析结果生成推广文案
- 匹配媒体平台规范

**输入**：
- analysis（分析脑输出）
- topic、raw_query
- session_document_context

**输出**：
- 推广文案（字符串）

**调用方**：编排层

---

### 4. 评估脑（Evaluator）

**位置**：`domain/content/evaluator.py`

**职责**：
- 对生成内容质量评估
- 四维度打分

**输入**：
- content（生成脑输出）
- context（brand、topic、analysis）

**输出**：
```json
{
  "scores": {...},
  "overall": 8.5,
  "suggestions": "...",
  "overall_score": 9
}
```

**调用方**：编排层

---

## 三、深度思考执行流程

```
用户："推广降噪耳机，目标18-35岁，生成B站完整文稿"
    │
    ▼
【策略脑】构建思维链
    ├─ 分析意图：需要推广文案
    ├─ 判断：需要竞品信息 → 加入 web_search
    ├─ 判断：有用户历史 → 加入 memory_query
    └─ 规划：web_search → memory_query → analyze → generate → evaluate
    │
    ▼
【编排层】按思维链执行
    ├─ 步骤1: web_search("降噪耳机竞品 2026")
    │   └─ 结果：[竞品A, 竞品B, ...]
    │
    ├─ 步骤2: memory_query(user_id)
    │   └─ 结果：用户偏好简洁风格、关注性价比
    │
    ├─ 步骤3: analyze(品牌+热点+搜索结果+记忆)
    │   └─ 结果：semantic_score=85, angle="性价比+科技感"
    │
    ├─ 步骤4: generate(分析结果+B站规范+完整文稿要求)
    │   └─ 结果：完整推广文案（1500字）
    │
    └─ 步骤5: evaluate(生成内容)
        └─ 结果：overall_score=8.5, suggestions="可再强化卖点"
    │
    ▼
【汇总】
    └─ 最终输出：推广文案 + 完整思考过程
```

---

## 四、与旧架构对比

| 维度 | 旧架构 | 新架构 |
|------|--------|--------|
| **策略脑** | 独立执行单元（生成策略文档） | 编排层（构建思维链） |
| **深度思考** | Meta 判断 → 二选一 | 策略脑规划 → 编排执行 |
| **搜索** | 无 | 新增 web_search 模块 |
| **灵活性** | 固定流程 | 动态思维链 |
| **可扩展** | 需修改 Meta | 注册新模块即可 |

---

## 五、扩展示例

### 新增模块：情感分析

```python
# domain/content/sentiment_analyzer.py
class SentimentAnalyzer:
    def __init__(self, llm: ILLMClient):
        self._llm = llm
    
    async def analyze_sentiment(self, text: str) -> dict:
        """分析文案情感倾向"""
        ...

# 策略脑可规划包含此步骤
plan = [
    ...,
    {"step": "sentiment_analysis", "params": {"text": "..."}, "reason": "检查情感倾向"},
    ...
]

# orchestration_node 增加分支
elif step_name == "sentiment_analysis":
    result = await sentiment_analyzer.analyze_sentiment(params["text"])
```

---

**已完成**：
- ✅ 新增 `core/search/` 搜索模块
- ✅ 重构 `meta_workflow`（策略脑 = 思维链构建）
- ✅ 编排层支持动态模块调用
- ✅ 旧 `strategy_workflow` 改名为 `campaign_planner`