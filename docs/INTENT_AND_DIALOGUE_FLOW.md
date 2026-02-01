# 意图识别与对话流程

## 意图类型

| 意图 | 说明 | 处理方式 |
|------|------|----------|
| `casual_chat` | 日常闲聊、问候、功能咨询、非营销对话 | 快捷对话回复，不进入工作流 |
| `structured_request` | 明确的结构化营销需求（品牌、产品、话题） | 澄清检查 → MetaWorkflow 生成 |
| `free_discussion` | 营销相关但不完全结构化 | 澄清检查 → MetaWorkflow 生成 |
| `document_query` | 基于已上传文档的查询 | 文档插件增强 → MetaWorkflow |
| `command` | 以 / 开头的命令 | 命令处理 |

## 对话流程

### 1. 结构化输入（明确目标）

用户：推广降噪耳机，目标18-35年轻人，B站完整文稿

- 意图：`structured_request` 或 `free_discussion`
- 平台/篇幅已明确 → 直接进入 MetaWorkflow 生成

### 2. 非结构化输入（需澄清）

用户：推广降噪耳机，目标18-35年轻人

- 意图：`structured_request` 或 `free_discussion`
- 平台/篇幅未明确 → 返回澄清问题，引导用户补充平台和篇幅
- 用户补充后 → 进入 MetaWorkflow

### 3. 日常闲聊（非营销）

用户：你好 / 有什么功能 / 怎么用

- 意图：`casual_chat`
- 快捷对话回复（1-3 句），不进入 MetaWorkflow
- 可简要介绍能力，自然接话

## 使用位置

- **意图识别**：`services/input_service.py` 的 `InputProcessor.process()`
- **闲聊回复**：`services/ai_service.py` 的 `reply_casual()`
- **澄清逻辑**：`config/media_specs.py` 的 `needs_clarification()`、`get_clarification_response()`
- **流程编排**：`main.py` 的 `frontend_chat`、`analyze_deep_raw`

## Chat 模式与 Deep 模式

两种模式均使用同一套意图识别逻辑：

- **Chat 模式**：意图 → casual_chat 走 `reply_casual`，其余走澄清/生成
- **Deep 模式**：意图 → casual_chat 走 `reply_casual`，command 单独处理，其余走澄清/MetaWorkflow
