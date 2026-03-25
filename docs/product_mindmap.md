# AI 营销助手 - 产品脑图

```mermaid
mindmap
  root((AI 营销助手\n面向营销与内容场景的智能分析与创作平台))
    
    %% 第一层：用户接入层
    用户接入层
      Web前端
        Gradio界面
        对话交互
        文档上传
        报告下载
      API客户端
        HTTP REST API
        流式响应SSE
        会话管理
      客户端类型
        营销人员
        内容创作者
        品牌运营者
    
    %% 第一层：核心能力层
    核心能力层
      意图识别
        闲聊识别
        创作意图
        文档问答
        指令识别
      智能计划
        固定模板
          IP诊断
          账号打造
          内容矩阵
          四模块能力
        动态规划
          PlanningAgent
          步骤生成
      工作流编排
        元工作流
        分析子图
        生成子图
        IP打造流程
    
    %% 第一层：功能模块层
    功能模块层
      Lumina四模块
        内容方向榜单
        案例库
        内容定位矩阵
        每周决策快照
      创作能力
        文案生成
        脚本生成
        活动策划
        封面诊断
      分析能力
        热点追踪
          B站热点
          抖音热点
          小红书热点
          Acfun热点
        视频拆解
        传播预测
        点击率预测
      诊断优化
        账号诊断
        限流诊断
        爆文结构分析
        商业定位
    
    %% 第一层：智能大脑层
    智能大脑层
      分析脑
        热点分析插件
        案例库插件
        方法论插件
        知识库插件
      生成脑
        文本生成插件
        图片生成插件
        视频生成插件
        报告生成插件
      策略脑
        策略编排器
        A/B测试分桶
        技能运行时
        失败回退机制
    
    %% 第一层：数据知识层
    数据知识层
      知识库
        方法论库
        平台规则
        案例模板
        样本库
      记忆系统
        短期记忆
        长期记忆
        用户画像
        对话历史
      数据闭环
        效果追踪
        反馈收集
        标签提炼
        持续优化
    
    %% 第一层：技术基础层
    技术基础层
      AI模型
        阿里云DashScope
        Qwen大模型
        嵌入模型
        多模态能力
      数据存储
        PostgreSQL
        Redis缓存
        智能缓存
        文档存储
      工程架构
        FastAPI
        LangGraph
        异步处理
        插件化架构
    
    %% 第一层：运营支撑层
    运营支撑层
      监控观测
        Prometheus指标
        Grafana可视化
        健康检查
        链路追踪
      系统管理
        会话管理
        用户管理
        反馈管理
        文档管理
      部署运维
        Docker容器化
        开发环境
        生产环境
        自动扩缩容
```

---

## 产品架构分层详解

### 1. 用户接入层
| 组件 | 功能描述 |
|------|----------|
| Gradio前端 | 交互式Web界面，支持对话、文件上传 |
| REST API | 完整的HTTP API接口，支持第三方集成 |
| 会话管理 | 支持多轮对话、会话续期、上下文保持 |

### 2. 核心能力层
| 组件 | 功能描述 |
|------|----------|
| InputProcessor | 意图分类与输入标准化 |
| PlanningAgent | 动态步骤规划与任务分解 |
| Meta Workflow | LangGraph编排的元工作流 |

### 3. 功能模块层 (Lumina对齐)
| 模块 | 能力描述 |
|------|----------|
| 内容方向榜单 | 各平台热门内容趋势分析 |
| 案例库 | 行业优秀案例检索与学习 |
| 内容定位矩阵 | 账号定位与内容策略规划 |
| 每周决策快照 | 数据驱动的运营决策建议 |

### 4. 智能大脑层
| 大脑类型 | 插件示例 |
|----------|----------|
| 分析脑 | 热点分析、案例库、方法论、知识库 |
| 生成脑 | 文本、图片、视频、报告生成 |
| 策略脑 | 编排器、A/B测试、回退机制 |

### 5. 数据知识层
| 类型 | 内容 |
|------|------|
| 知识库 | 营销方法论、平台规则、案例模板 |
| 记忆系统 | 用户画像、对话历史、偏好学习 |
| 数据闭环 | 效果追踪、反馈优化、标签体系 |

### 6. 技术基础层
| 技术 | 用途 |
|------|------|
| DashScope/Qwen | 大模型推理与嵌入 |
| LangGraph | 工作流编排 |
| PostgreSQL | 持久化存储 |
| Redis | 缓存与会话 |

---

## 核心流程图

```mermaid
flowchart TB
    User[用户输入] --> Intent[意图识别]
    Intent -->|闲聊| Casual[闲聊回复]
    Intent -->|创作| Plan[计划制定]
    Intent -->|文档| Doc[文档问答]
    
    Plan --> Meta[元工作流]
    Meta --> Analysis[分析脑]
    Meta --> Generate[生成脑]
    
    Analysis --> PluginsA[热点/案例/方法论插件]
    Generate --> PluginsG[文本/图片/视频插件]
    
    PluginsA --> Memory[(记忆更新)]
    PluginsG --> Output[内容输出]
    Memory --> Output
    
    Output --> Feedback[反馈收集]
    Feedback --> Optimize[优化迭代]
```

---

## 插件生态全景

```
plugins/
├── 热点追踪类
│   ├── bilibili_hotspot          # B站热点
│   ├── douyin_hotspot            # 抖音热点
│   ├── xiaohongshu_hotspot       # 小红书热点
│   └── acfun_hotspot             # Acfun热点
├── 内容生成类
│   ├── text_generator            # 文案生成
│   ├── image_generator           # 图片生成
│   ├── video_generator           # 视频生成
│   ├── script_replication        # 脚本仿写
│   └── text_viral_structure      # 爆文结构
├── 诊断分析类
│   ├── cover_diagnosis           # 封面诊断
│   ├── rate_limit_diagnosis      # 限流诊断
│   ├── viral_prediction          # 传播预测
│   └── ctr_prediction            # CTR预测
├── 能力插件类
│   ├── case_library              # 案例库
│   ├── methodology               # 方法论
│   └── knowledge_base            # 知识库
└── 报告生成类
    └── report_generation         # Word报告
```

---

*文档生成时间: 2026-03-25*
*产品版本: v1.0.0*
