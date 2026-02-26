# 项目总结

## 项目概述

AI 营销助手是一个智能内容分析、生成与评估的 API 服务，支持用户画像、记忆系统与多插件扩展。

## 核心功能

1. **意图识别**：准确识别用户意图（闲聊、咨询、创作等）
2. **记忆系统**：短期记忆、长期记忆、上下文窗口、标签更新
3. **内容生成**：文案创作、短视频脚本、热点分析
4. **诊断评估**：账号诊断、点击率预测、爆款预测
5. **插件扩展**：热点插件、诊断插件、生成插件
6. **Lumina 四模块能力接口**：内容方向榜单、定位决策案例库、内容定位矩阵、每周决策快照

## 技术架构

- **API 框架**：FastAPI
- **AI 能力**：阿里云 Qwen3-max + Dashscope 嵌入
- **数据存储**：PostgreSQL + Redis
- **部署方式**：Docker Compose

## 测试结果

综合测试通过率：**100%**

| 场景 | 请求数 | 成功率 |
|------|--------|--------|
| 记忆系统 | 110 | 100% |
| 意图识别 | 45 | 100% |
| 全流程 | 15 | 100% |
| 插件测试 | 52 | 100% |
| **总计** | **222** | **100%** |

## 项目结构

```
my-ai-assistant/
├── core/              # 核心模块
│   ├── intent/        # 意图识别
│   ├── multimodal/    # 多模态
│   └── plugin_*/      # 插件中心
├── services/          # 服务层
│   ├── ai_service.py  # AI 调用
│   ├── memory_service.py  # 记忆服务
│   └── *_refresh.py  # 热点刷新
├── workflows/         # 工作流
│   └── meta_workflow.py  # 主流程
├── domain/           # 领域模型
│   └── content/       # 内容分析/生成
├── plugins/           # 插件实现
│   ├── hotspot/       # 热点插件
│   ├── diagnosis/     # 诊断插件
│   └── generation/   # 生成插件
├── scripts/          # 测试脚本
│   └── test_comprehensive/  # 综合测试
└── docs/             # 文档
```

## 部署方式

- **生产**：Docker Compose（API + PostgreSQL + Redis + Prometheus + Grafana）
- **本地开发**：`docker-compose.dev.yml` 仅启动 Redis + Postgres，本机运行 `uvicorn main:app --reload --port 8000`

## 文档索引

- [快速开始](./QUICK_START.md) | [部署指南](./DEPLOYMENT.md) | [API 参考](./API_REFERENCE.md) | [Lumina 四模块映射](./LUMINA_MODULES_MAPPING.md) | [Git 上传](./GIT_UPLOAD.md)