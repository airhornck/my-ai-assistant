# 模块架构说明

## 解耦设计

为便于生产维护与扩展，公共能力按职责拆分为独立模块。

### 1. 意图理解 `core/intent/`

- **processor.py**：InputProcessor，意图识别与输入标准化
- **types.py**：意图常量（casual_chat、structured_request、free_discussion、document_query、command）
- **使用**：`from core.intent import InputProcessor, INTENT_*`
- **兼容层**：`services/input_service.py` 重导出，保留原有导入路径

### 2. 文档能力 `core/document/`

- **storage.py**：物理存储（当前本地文件，可扩展 OSS）
- **parser.py**：文本解析（PDF、TXT、DOCX），可扩展更多格式
- **session_binding.py**：会话-文档关联，支持「对话中附加文件」
- **使用**：`from core.document import SessionDocumentBinding`

### 3. 文档与会话的关系

- 上传时需提供 `session_id`，文档绑定到该会话
- 理解对话时自动加载会话附加文档，解析后注入上下文
- 意图识别与内容生成均可引用会话文档
- 新建对话时，会话切换，原会话文档不再出现在新会话中

### 4. API 变更

| 接口 | 变更 |
|------|------|
| POST /api/v1/documents/upload | 新增必填 `session_id`，文档绑定到会话 |
| GET /api/v1/documents | 支持 `session_id`（会话文档）或 `user_id`（用户全部文档） |

### 5. 数据表

- **documents**：文档元信息（保持不变）
- **session_documents**：`(session_id, doc_id)` 关联，实现会话级附加
