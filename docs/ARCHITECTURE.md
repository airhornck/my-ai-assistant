# 项目架构说明

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户请求                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  主入口 (main.py)                                                          │
│  - 意图识别 (Intent Classification)                                        │
│  - 路由分发：闲聊 → 策略脑 → 分析/生成                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  策略脑 (Planning Node)                                                     │
│  - LLM 动态规划步骤 (Chain of Thought)                                     │
│  - 输出: plan = [step1, step2, ...]                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  编排层 (Workflows)                                                          │
│  - meta_workflow.py: 元工作流                                               │
│  - langgraph_orchestrator.py: LangGraph 编排 (可选)                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
            │   分析脑       │ │   生成脑       │ │   搜索        │
            │ (Plugins)    │ │ (Plugins)    │ │ (Web Search) │
            └───────────────┘ └───────────────┘ └───────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  能力中心 (Capabilities)                                                    │
│  - core/capabilities/: 统一获取所有 Port                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、核心模块说明

### 2.1 入口层 (`main.py`)

| 文件 | 说明 |
|------|------|
| `main.py` | FastAPI 主入口，统一路由 `/api/v1/analyze-deep/raw` |

### 2.2 核心模块 (`core/`)

| 目录 | 说明 |
|------|------|
| `core/intent/` | 意图识别：闲聊、咨询、创作等 |
| `core/multimodal/` | 多模态理解 Port（图像/视频分析） |
| `core/brain_plugin_center.py` | 脑级插件中心 |
| `core/plugin_bus.py` | 插件总线（事件驱动） |
| `core/capabilities/` | 能力中心统一入口 |

### 2.3 服务层 (`services/`)

| 文件 | 说明 |
|------|------|
| `services/ai_service.py` | AI 调用门面（通义千问/DeepSeek） |
| `services/memory_service.py` | 记忆服务（短期/长期/上下文） |
| `services/prediction/` | 预测模型 Port（爆款/CTR 预测） |
| `services/video_decomposition/` | 视频拆解 Port |
| `services/*_refresh.py` | 热点刷新定时任务 |

### 2.4 工作流 (`workflows/`)

| 文件 | 说明 |
|------|------|
| `workflows/meta_workflow.py` | 元工作流（策略脑 → 编排 → 执行） |
| `workflows/langgraph_orchestrator.py` | LangGraph 编排器（可选） |
| `workflows/analysis_brain_subgraph.py` | 分析脑子图 |
| `workflows/types.py` | 类型定义 |

### 2.5 领域模型 (`domain/`)

| 目录 | 说明 |
|------|------|
| `domain/content/` | 内容分析/生成/评估 |

### 2.6 插件 (`plugins/`)

| 插件 | 类型 | 说明 |
|------|------|------|
| `bilibili_hotspot/` | 定时 | B站热点刷新 |
| `douyin_hotspot/` | 定时 | 抖音热点刷新 |
| `xiaohongshu_hotspot/` | 定时 | 小红书热点刷新 |
| `account_diagnosis/` | 诊断 | 账号诊断 |
| `ctr_prediction/` | 诊断 | 点击率预测 |
| `viral_prediction/` | 诊断 | 爆款预测 |
| `text_generator/` | 生成 | 文案生成 |
| `campaign_plan_generator/` | 生成 | 营销方案生成 |
| `methodology/` | 分析 | 方法论插件 |
| `case_library/` | 分析 | 案例库插件 |
| `knowledge_base/` | 分析 | 知识库插件 |

### 2.7 能力模块 (`modules/`)

| 目录 | Port | 说明 |
|------|------|------|
| `modules/knowledge_base/` | ✅ KnowledgePort | 知识库 RAG |
| `modules/platform_rules/` | ✅ PlatformRulesPort | 平台规则（敏感词/违禁） |
| `modules/sample_library/` | ✅ SampleLibraryPort | 样本库 |
| `modules/methodology/` | ✅ (MethodologyPort) | 方法论文档 |
| `modules/case_template/` | ✅ (CaseTemplatePort) | 案例模板 |
| `modules/data_loop/` | ✅ (DataLoopPort) | 数据闭环 |

> 注：带 ✅ 为已实现 Port，带 () 为已补齐抽象接口

### 2.8 配置 (`config/`)

| 文件 | 说明 |
|------|------|
| `config/capabilities.yaml` | 能力中心配置 |
| `config/platform_rules/` | 平台规则 YAML |
| `config/intent_rules.yaml` | 意图规则 |
| `config/diagnosis_thresholds.yaml` | 诊断阈值 |

---

## 三、数据流

### 3.1 完整创作流程

```
用户输入
    │
    ▼
意图识别 (core/intent/)
    │
    ▼
策略脑规划 (planning_node)
    │ plan = ["memory_query", "kb_retrieve", "analyze", "generate"]
    │
    ▼
LangGraph 编排 (可选)
    │
    ├─► memory_query: 查询用户偏好
    ├─► kb_retrieve: 检索知识库
    ├─► analyze: 调用分析脑插件
    └─► generate: 调用生成脑插件
    │
    ▼
返回结果
```

### 3.2 插件执行流程

```
插件中心 (BrainPluginCenter)
    │
    ├─► 定时插件 (SCHEDULED): 按时间触发
    ├─► 实时插件 (REALTIME): 每次请求触发
    ├─► 工作流插件 (WORKFLOW): 编排时调用
    └─► 技能插件 (SKILL): 意图匹配触发
```

---

## 四、Port 架构

### 4.1 现有 Port 接口

| Port | 位置 | 实现 |
|------|------|------|
| `IMultimodalPort` | `core/multimodal/port.py` | aliyun_adapter, mock_adapter |
| `IPredictionPort` | `services/prediction/port.py` | mock_adapter |
| `IVideoDecompositionPort` | `services/video_decomposition/port.py` | mock_adapter |
| `SampleLibraryPort` | `modules/sample_library/port.py` | mock_adapter |
| `PlatformRulesPort` | `modules/platform_rules/port.py` | yaml_adapter |
| `KnowledgePort` | `modules/knowledge_base/port.py` | local_adapter, aliyun_adapter |

### 4.2 统一获取方式

```python
from core.capabilities import get_capabilities

caps = get_capabilities()

# 各能力通过 Port 接口调用
await caps.multimodal.analyze_image(url)
await caps.prediction.predict_viral(features)
await caps.knowledge.retrieve(query)
```

---

## 五、配置管理

### 5.1 环境变量 (.env)

```bash
# LLM
DASHSCOPE_API_KEY=sk-xxx

# 能力中心
MULTIMODAL_PROVIDER=mock
PREDICTION_PROVIDER=mock
USE_ALIYUN_KNOWLEDGE=0
```

### 5.2 配置文件 (config/capabilities.yaml)

- 所有 adapter 配置集中管理
- 支持环境变量覆盖
- provider 可切换实现

---

## 六、部署架构

```
┌─────────────────────────────────────────────┐
│              Docker Compose                  │
├─────────────────────────────────────────────┤
│  app (FastAPI)         :8000               │
│  postgres (PostgreSQL) :5432               │
│  redis (Cache)         :6379               │
│  prometheus (监控)     :9090               │
│  grafana (可视化)       :3000               │
└─────────────────────────────────────────────┘
```

---

## 七、测试

```bash
# 综合测试
python scripts/test_comprehensive/runner.py

# 意图测试
python scripts/test_intent_rules.py
```
