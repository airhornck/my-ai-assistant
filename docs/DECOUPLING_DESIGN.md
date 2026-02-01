# 解耦架构设计

## 一、边界与依赖关系

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              main / API 层                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          domain/ 业务域（可单独开发测试）                      │
│  ┌─────────────┐  ┌─────────────────────────┐  ┌─────────────┐               │
│  │  intent     │  │  content                │  │  memory     │               │
│  │  意图理解   │  │  analyzer / generator / │  │  记忆服务   │               │
│  │  (core/)    │  │  evaluator 分析→生成→评估 │  │             │               │
│  └──────┬──────┘  └──────────┬──────────────┘  └──────┬──────┘               │
│         │                    │                        │                       │
└─────────┼────────────────────┼────────────────────────┼───────────────────────┘
          │                    │                        │
          ▼                    ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          core/ 公共能力（可替换实现）                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  ai         │  │  document   │  │  cache      │  │  plugin_bus         │ │
│  │  ILLMClient │  │  文档存储解析 │  │  智能缓存   │  │  事件总线           │ │
│  │  DashScope  │  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│  └─────────────┘                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 二、模块职责

| 模块 | 职责 | 可替换性 |
|------|------|----------|
| **core/ai** | LLM 调用抽象，按 task_type/complexity 路由 | 可替换为 OpenAI、其他国产大模型 |
| **core/intent** | 意图识别，依赖 ILLMClient | 已解耦 |
| **core/document** | 文档存储、解析、会话绑定 | 已解耦 |
| **domain/content** | 分析脑、生成脑、评估脑，各自依赖 ILLMClient | 业务逻辑可单独测试 |
| **domain/memory** | 记忆查询、画像构建 | 可扩展存储后端 |
| **workflows** | 编排，组合 domain 能力 | 依赖注入，便于测试 |

## 三、AI 接口协议

```python
# core/ai/port.py
class ILLMClient(Protocol):
    """LLM 调用协议，实现者可替换为不同供应商"""
    async def invoke(
        self,
        messages: list,
        *,
        task_type: str = "chat",
        complexity: str = "medium",
    ) -> str: ...
```

- **实现**：`core/ai/dashscope_client.py` 提供 `DashScopeLLMClient`
- **替换**：新建 `core/ai/openai_client.py` 等，在 `SimpleAIService` 中注入即可

## 四、模块与文件

| 模块 | 路径 | 职责 |
|------|------|------|
| core/ai | core/ai/port.py, dashscope_client.py | LLM 调用抽象与阿里云实现 |
| domain/content | domain/content/analyzer.py 等 | 分析脑、生成脑、评估脑 |
| domain/memory | domain/memory/ (复用 services.memory_service) | 记忆查询 |
| services/ai_service | services/ai_service.py | 门面，组合 domain + cache |
