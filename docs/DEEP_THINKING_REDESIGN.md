# 深度思考架构重新设计

## 一、当前问题

### 现有逻辑（有误）
- **策略脑**（strategy_workflow）：被当作「独立执行单元」，与内容流并列
- **Meta Workflow**：判断 strategy vs content，二选一执行
- **问题**：策略脑应该是**编排层**，不是执行单元

---

## 二、正确架构

### 策略脑 = 编排层（思维链构建）

```
用户请求
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                  策略脑（Planning Brain）                         │
│              根据用户意图构建思维链（Chain of Thought）            │
│                                                                   │
│  输入：用户目标                                                   │
│  输出：执行计划 = [步骤1, 步骤2, 步骤3, ...]                      │
│                                                                   │
│  示例：                                                           │
│    用户："推广降噪耳机，目标18-35岁"                              │
│    策略脑规划：                                                   │
│      1. 搜索竞品信息（web_search）                                │
│      2. 分析目标人群偏好（analyzer）                              │
│      3. 生成B站推广文案（generator + B站规范）                    │
│      4. 评估内容质量（evaluator）                                 │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                  编排层（Orchestration）                          │
│              按思维链顺序/并行调用执行单元                         │
└─────────────────────────────────────────────────────────────────┘
    │
    ├─→ 搜索模块（web_search）        ← 新增
    │       └─ 网络检索竞品、热点
    │
    ├─→ 分析脑（analyzer）
    │       └─ domain/content/analyzer.py
    │
    ├─→ 生成脑（generator）
    │       └─ domain/content/generator.py
    │
    ├─→ 评估脑（evaluator）
    │       └─ domain/content/evaluator.py
    │
    └─→ 其他插件/工作流
            └─ 可通过 PluginRegistry 动态注册
```

---

## 三、与现有 Meta Workflow 的关系

### 现有 Meta Workflow

```python
planning_node:
  判断：strategy（策略规划） vs content（单篇内容）
  - strategy → 调用 run_strategy_workflow（独立执行）
  - content → 生成步骤规划 → orchestration_node

orchestration_node:
  按 plan 调用子工作流（basic_workflow 等）
```

### 问题
1. **策略脑定位错误**：被当作「生成策略计划文档」的执行单元，而非「构建思维链」的编排者
2. **缺少搜索能力**：无法检索网络信息（竞品、热点等）
3. **思维链不灵活**：planning_node 只是简单判断 strategy/content，没有真正的 CoT

---

## 四、重新设计方案

### 方案 A：重构 Meta Workflow（推荐）

**策略脑 = planning_node**（思维链构建）

```python
async def planning_node(state):
    """
    策略脑：根据用户意图构建思维链。
    
    输入：user_input（品牌、产品、目标）
    输出：plan = [
        {"step": "web_search", "params": {"query": "降噪耳机竞品"}},
        {"step": "analyze", "params": {"focus": "目标人群"}},
        {"step": "generate", "params": {"platform": "B站"}},
        {"step": "evaluate", "params": {}},
    ]
    """
    # 调用 LLM 生成思维链
    system_prompt = """你是策略规划专家。根据用户目标，构建执行思维链。
可用模块：
- web_search: 网络检索（竞品、热点、数据）
- analyze: 分析品牌与热点关联度
- generate: 生成推广文案
- evaluate: 评估内容质量
- memory_query: 查询用户历史偏好

输出 JSON 数组，每步包含 step（模块名）和 params（参数）。"""
    
    user_prompt = f"用户目标：{user_input}\n请规划执行步骤。"
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    response = await llm.invoke(messages, task_type="planning", complexity="high")
    plan = parse_plan_json(response)
    
    return {**state, "plan": plan, "thinking_logs": [...]}
```

**orchestration_node**（执行层）

```python
async def orchestration_node(state):
    """按思维链调用各模块"""
    plan = state["plan"]
    results = []
    
    for step_config in plan:
        step_name = step_config["step"]
        params = step_config["params"]
        
        if step_name == "web_search":
            result = await web_search_module.search(params["query"])
        elif step_name == "analyze":
            result = await analyzer.analyze(...)
        elif step_name == "generate":
            result = await generator.generate(...)
        elif step_name == "evaluate":
            result = await evaluator.evaluate(...)
        
        results.append(result)
    
    return {**state, "step_outputs": results}
```

---

### 方案 B：保持 Meta + 增强 Strategy（折中）

- **Meta Workflow**：保持现有结构（planning → orchestration → compilation）
- **Strategy Workflow**：重构为「思维链构建器」，返回 plan 而非直接生成内容
- **新增 Web Search 模块**：`core/search/` 或 `domain/search/`

---

## 五、搜索模块设计

### 新增模块：`core/search/`

```python
# core/search/web_searcher.py
class WebSearcher:
    """网络检索：竞品信息、热点数据、行业动态"""
    
    async def search(
        self,
        query: str,
        num_results: int = 5,
    ) -> list[dict]:
        """
        返回：[{"title": "...", "snippet": "...", "url": "..."}]
        """
        # 接入搜索 API（如 SerpAPI、百度搜索 API 等）
        ...
```

### 集成到思维链

```python
# 策略脑规划时可包含搜索步骤
plan = [
    {"step": "web_search", "params": {"query": "降噪耳机 2026 热门品牌"}},
    {"step": "analyze", "params": {"with_search_context": True}},
    {"step": "generate", "params": {}},
]
```

---

## 六、推荐实施路径

### 阶段 1：重构策略脑定位（当前）
1. 将 `strategy_workflow` 重命名为 `planning_brain`
2. 职责改为：构建思维链（plan），不直接生成内容
3. Meta Workflow 的 planning_node 调用 planning_brain 获取 plan

### 阶段 2：新增搜索模块
1. 创建 `core/search/web_searcher.py`
2. 注册为可调用模块（orchestration_node 识别 "web_search"）
3. 策略脑规划时可包含搜索步骤

### 阶段 3：统一编排
1. Orchestration_node 支持动态调用：analyzer、generator、evaluator、web_search、memory_query 等
2. 每个模块独立、可测试
3. 策略脑只负责「规划」，不负责「执行」

---

## 七、对比

| 维度 | 现有架构 | 正确架构 |
|------|----------|----------|
| 策略脑 | 独立执行单元（生成策略文档） | 编排层（构建思维链） |
| 深度思考 | Meta 判断 → 二选一执行 | 策略脑规划 → 编排层执行 |
| 搜索能力 | 无 | 新增 web_search 模块 |
| 灵活性 | 固定流程 | 动态思维链 |

---

**下一步**：确认采用方案 A（重构 Meta）还是方案 B（增强 Strategy），然后实施。
