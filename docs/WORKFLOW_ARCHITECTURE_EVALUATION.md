# 工作流编排方案评估与演进

本文档评估当前 `meta_workflow.py` 中以 `router` 为核心的循环方案，并记录可行的优化演进方向。

---

## 1. 当前方案：LangGraph Router 循环

### 1.1 图结构

```
router → (analyze / generate / evaluate / parallel_retrieval / casual_reply / skip) → router → ... → compilation → END
```

- **核心节点**：`router`（调度中心），根据 `plan` 和 `current_step` 决定下一步。
- **循环机制**：每执行完业务节点后返回 `router`，形成循环，直到 `plan` 全部完成。

### 1.2 节点说明

| 节点 | 作用 |
|------|------|
| `router` | 调度核心，根据 plan 决定下一个节点 |
| `parallel_retrieval` | 并行执行 web_search、memory_query、bilibili_hotspot、kb_retrieve |
| `analyze` | 调用分析脑子图 |
| `generate` | 调用生成脑子图 |
| `evaluate` | 调用评估节点 |
| `casual_reply` | 闲聊回复（plan 只有这一步时短路） |
| `skip` | 未知步骤兜底（非监控） |
| `compilation` | 汇总所有输出，生成最终响应 |
| `human_decision` | 人工介入（评估后需修订时） |

### 1.3 优点

1. **灵活性高**：plan 由策略脑动态生成，步骤数量和顺序不固定，router 方式天然适配。
2. **可维护性好**：新增步骤只需在 `_router_next` 加一个 `if`，无需改图结构。
3. **调试友好**：每个节点职责清晰，router 是唯一调度点，易追踪。

### 1.4 缺点

1. **每次都要经过 router**：即使 plan 只有 3 步，也要 3 次进入 router 节点（虽然只是透传 state，有一定开销）。
2. **状态透传**：router 节点本质是透传 `state → state`，没有实际计算但仍占用图节点。
3. **循环复杂度**：图结构看起来是线性的，但实际上是「节点 + 循环边」，对 LangGraph 可视化不友好。

---

## 2. 其他可行方案

### 方案 1：直接线性图（适合固定流程）

如果 plan 结构固定（如始终是 planning → analyze → generate → compilation），可以直接写死边：

```python
workflow = StateGraph(MetaState)
workflow.add_node("planning", planning_node)
workflow.add_node("analyze", analyze_node)
workflow.add_node("generate", generate_node)
workflow.add_node("compilation", compilation_node)

workflow.set_entry_point("planning")
workflow.add_edge("planning", "analyze")
workflow.add_edge("analyze", "generate")
workflow.add_edge("generate", "compilation")
workflow.add_edge("compilation", END)
```

- **优点**：无 router 循环，性能最高，图可视化清晰。
- **缺点**：不灵活，无法动态调整步骤。

---

### 方案 2：动态子图（适合复杂步骤）

将每个 plan 步骤封装为独立子图，运行时动态拼接：

```python
def build_dynamic_graph(plan_steps: list[str]):
    graph = StateGraph(MetaState)
    prev = "start"
    for step in plan_steps:
        graph.add_node(step, get_step_node(step))
        graph.add_edge(prev, step)
        prev = step
    graph.add_edge(prev, "compilation")
    return graph.compile()
```

- **优点**：灵活 + 性能好（无 router 循环）。
- **缺点**：每次请求都要重新构建图，复杂度高。

---

### 方案 3：LCEL 管道（适合纯串行）

如果步骤完全串行且不需要分支，可直接用 LCEL：

```python
chain = (
    planning_prompt
    | llm
    | parse_plan
    | analyze_step
    | generate_step
    | compilation
)
result = await chain.ainvoke({"user_input": "..."})
```

- **优点**：最简洁、无状态管理开销。
- **缺点**：不支持并行、分支、条件跳转。

---

### 方案 4：保留 router，但优化透传

将 router 改为**纯边条件判断**，不作为独立节点：

```python
# 条件边直接在 add_conditional_edges 中完成，不额外加节点
workflow.add_conditional_edges(
    "analyze",
    lambda state: _router_next(state),
    ["generate", "compilation", "skip"]
)
```

- **优点**：去掉 router 透传节点，性能提升。
- **缺点**：需要大改现有图的连接方式。

---

## 3. 方案对比与选型建议

| 维度 | 当前 router 方案 | 方案 1 线性图 | 方案 2 动态子图 | 方案 3 LCEL | 方案 4 优化透传 |
|------|------------------|--------------|----------------|-------------|-----------------|
| 灵活性 | ✅ 高 | ❌ 固定 | ✅ 高 | ❌ 固定 | ✅ 高 |
| 性能 | ⚠️ 中 | ✅ 高 | ✅ 高 | ✅ 最高 | ✅ 高 |
| 可维护性 | ✅ 好 | ✅ 好 | ⚠️ 中 | ✅ 好 | ⚠️ 中 |
| 实现复杂度 | 当前 | 低 | 高 | 低 | 高 |
| 适用场景 | plan 动态变化 | 步骤固定 | 步骤极多 | 纯串行无分支 | 高 QPS |

### 选型建议

| 场景 | 推荐方案 |
|------|----------|
| **当前业务（plan 动态、有并行/分支）** | ✅ **保留 router**，当前方案最合理 |
| **未来 plan 固定为 3~5 步** | 方案 1：直接线性图 |
| **步骤极简（纯串行、无分支）** | 方案 3：LCEL 管道 |
| **性能敏感（QPS 极高）** | 方案 4：去掉 router 节点，用条件边 |

---

## 4. 结论

- **当前 router 方案是合理且高效的**，尤其适合：
  - plan 动态生成
  - 有并行步骤（parallel_retrieval）
  - 需要分支（evaluate → human_decision）

- 只有当 **QPS 极高且 plan 完全固定** 时，才需要考虑方案 4 优化。

- 建议**保持现状**，将本文档作为后续架构演进的参考。

---

## 5. 附录：相关文件

- `workflows/meta_workflow.py`：当前实现（使用 router 循环）
- `workflows/analysis_brain_subgraph.py`：分析脑子图
- `workflows/generation_brain_subgraph.py`：生成脑子图
