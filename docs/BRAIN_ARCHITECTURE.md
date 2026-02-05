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
│  职责：根据用户意图规划执行步骤与各脑插件列表                      │
│  输出：plan（步骤，供前端思考过程展示）+ analysis_plugins /       │
│        generation_plugins（供编排执行，由 plan 推导）              │
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
    ├─→ 知识库检索（kb_retrieve）   ← 可选步骤，与 web_search 等并行
    │       └─ modules/knowledge_base 或 services/retrieval_service
    │       └─ 行业方法论、案例等，注入 analyze 前上下文
    │
    ├─→ 分析脑（analyze）
    │       └─ domain/content/analyzer.py + BrainPluginCenter
    │       └─ 品牌与热点关联度分析；可接收 analysis_plugins 并行执行插件
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
- **plan**（步骤数组）：供编排执行与前端「思考过程」展示。
- **analysis_plugins** / **generation_plugins**：由 plan 推导，供编排在调用分析脑/生成脑时传入；当前 analysis_plugins 可扩展（如 methodology_inject、ip_diagnosis），generation_plugins 含 copy_writer 等。

```json
{
  "plan": [
    {"step": "web_search", "params": {"query": "..."}, "reason": "..."},
    {"step": "kb_retrieve", "params": {}, "reason": "知识库检索"},
    {"step": "analyze", "params": {}, "reason": "..."},
    {"step": "generate", "params": {"platform": "B站"}, "reason": "..."},
    {"step": "evaluate", "params": {}, "reason": "..."}
  ],
  "analysis_plugins": [],
  "generation_plugins": ["copy_writer"]
}
```

**关键**：策略脑**不执行**，只规划；步骤保证前端思考过程体验，插件列表供编排按意图执行。

---

### 2. 分析脑（Analyzer）

**位置**：`domain/content/analyzer.py` + `BrainPluginCenter`（分析脑插件中心）

**职责**：
- 分析品牌与热点**关联度**
- 可引用搜索结果、用户记忆、知识库检索（kb_context）
- 可选接收 **analysis_plugins**：按列表并行执行插件（单插件超时），结果合并进 analysis

**输入**：
- ContentRequest（brand、product、topic）
- preference_context（可包含搜索结果、知识库检索、用户记忆）
- analysis_plugins（可选）：本轮要执行的分析脑插件名列表，由编排层传入

**输出**：
```json
{
  "semantic_score": 85,
  "angle": "年轻群体科技感",
  "reason": "...",
  "bilibili_hotspot": "..."
}
```
（插件输出以插件名为键合并进 analysis）

**调用方**：编排层（orchestration_node）；编排执行 analyze 时传入 analysis_plugins（由规划脑推导）

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
- ✅ 编排层支持动态模块调用（含 kb_retrieve、bilibili_hotspot 等）
- ✅ 旧 `strategy_workflow` 改名为 `campaign_planner`
- ✅ 规划脑输出 **步骤 + analysis_plugins / generation_plugins**（由 plan 推导，保障前端思考过程体验）
- ✅ 编排层执行 analyze 时传入 analysis_plugins；分析脑按列表并行执行插件（单插件超时）
- ✅ 知识库独立模块（modules/knowledge_base），生产可对接阿里云百炼；活动策划已收口到统一入口（task_type=campaign_or_copy 时编排层走 strategy_orchestrator）

**独立模块（可维护，支撑脑与插件）**：数据闭环、知识库、营销方法论、案例模板与打分，见 `docs/DATA_LOOP_AND_KNOWLEDGE_MODULES_DESIGN.md`、`docs/IP_PLUGIN_ARCHITECTURE_ANALYSIS.md`。