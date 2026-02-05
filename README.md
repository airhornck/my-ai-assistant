# my-ai-assistant

AI 助手 API：内容分析、生成与评估，支持用户画像与记忆优化。

## 模型与 API

- **主应用**（分析 / 生成 / 评估）与 **记忆优化器**（memory-optimizer）均使用 **阿里云 Qwen3-max**。
- 阿里云百炼 OpenAI 兼容 API：`https://dashscope.aliyuncs.com/compatible-mode/v1`，模型 `qwen3-max`。
- 环境变量：`DASHSCOPE_API_KEY`（必填）。获取：<https://dashscope.aliyun.com/>。
- 示例配置见 `.env.prod.example`。

## 知识库与 RAG

- **knowledge/**：存放 `marketing_knowledge.md` 等文档，供策略脑检索行业知识。
- **知识库模块**：`modules/knowledge_base/` 独立可维护，支持本地向量与阿里云百炼对接（生产可设 `USE_ALIYUN_KNOWLEDGE=1`）。
- **向量检索**：使用 **阿里云 Dashscope 嵌入 API** + **numpy** 实现轻量级 RAG，兼容 Python 3.14，无重度依赖。
- 首次调用检索时会自动加载文档、分块、调用嵌入 API 并持久化到 `./data/knowledge_vectors/vectors.json`。
- 需配置 `DASHSCOPE_API_KEY`；若未配置，策略脑仍可运行，但检索返回空。

## 插件与扩展

- **脑级插件中心**：各脑（分析脑、生成脑等）有独立的 `BrainPluginCenter`，插件注册在所属脑中，支持定时/实时/工作流/技能四类。
- **规划脑输出**：步骤（供前端思考过程展示）+ **analysis_plugins / generation_plugins**（由 plan 推导，供编排执行）；编排调用分析脑时传入 analysis_plugins，分析脑按列表并行执行插件。
- **B站热点**：分析脑定时插件，每 6 小时刷新缓存；编排步骤含 `kb_retrieve` 时注入知识库检索结果。
- **独立模块**：数据闭环、知识库、营销方法论、案例模板与打分，见 `docs/MODULE_ARCHITECTURE.md`、`docs/DATA_LOOP_AND_KNOWLEDGE_MODULES_DESIGN.md`。
- **扩展开发**：详见 **docs/PLUGIN_DEVELOPMENT_GUIDE.md**、**docs/BRAIN_PLUGIN_ARCHITECTURE.md**；整体架构见 **docs/BRAIN_ARCHITECTURE.md**；模板见 `plugin_template/`，插件目录 `plugins/`。

## 快速链接

- **文件与架构说明（新人必读）**：`docs/PROJECT_FILE_AND_ARCHITECTURE.md`（各目录/文件说明与调用关系）
- **整体架构**：`docs/BRAIN_ARCHITECTURE.md`（三脑 + 编排 + 步骤与插件列表）
- **模块与独立服务**：`docs/MODULE_ARCHITECTURE.md`（意图、文档、数据闭环、知识库、方法论、案例模板）
- **快速启动**：`docs/QUICK_START.md`
- **ESC 部署**：`docs/DEPLOYMENT.md`
- **环境变量**：`docs/ENV_KEYS_REFERENCE.md`
- **项目总结**：`docs/PROJECT_SUMMARY.md`

## 数据库表结构变更

修改 `database.py` 中模型后，表结构会变化。**首次运行前**：

- **新建库**：直接启动应用，`create_tables` 会创建所有表。
- **已有库**：需备份后重建，或执行迁移。例如新增 `brand_facts`、`success_cases` 时，可运行：
  ```bash
  psql -U postgres -d ai_assistant -f scripts/add_brand_memory_columns.sql
  ```
