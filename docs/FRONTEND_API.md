# 前端 API 接口文档

本文档介绍为 Gradio 前端（及其他前端框架）提供的统一 API 接口。

## 接口总览

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/v1/frontend/session/init` | GET | 初始化会话，获取 user_id、session_id、thread_id |
| `/api/v1/chat/new` | POST | 新建对话，保持 user_id 不变，返回新的 session_id、thread_id |
| `/api/v1/frontend/chat` | POST | 统一聊天接口，支持快速回复和深度思考两种模式 |
| `/api/v1/documents/upload` | POST | 上传文档（每次 1 个，每会话最多 5 个） |

---

## 1. 会话初始化接口

### `GET /api/v1/frontend/session/init`

**用途**：为前端提供初始化入口，生成默认 user_id 并创建初始会话。

**请求参数**：无

**响应示例**：

```json
{
  "success": true,
  "user_id": "frontend_user_1706234567_a3f2c1",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "thread_id": "661f8511-f3bc-52e5-b827-557766551111"
}
```

**响应字段**：

- `success` (bool): 是否成功
- `user_id` (str): 自动生成的用户 ID（演示用，基于时间戳+随机数）
- `session_id` (str): 会话 ID（对话 ID，见下方说明）
- `thread_id` (str): 对话链 ID（见下方说明）

### Session ID 与 Thread ID 说明

| 字段 | 用途 | 说明 |
|------|------|------|
| **session_id（对话 ID）** | 单次对话的会话标识 | 每次「新建对话」会生成新的 session_id；用于会话级记忆（品牌、产品、创作内容、后续建议等）；文档绑定到 session_id。 |
| **thread_id** | LangGraph 断点续跑与多轮编排 | 与 session_id 一一对应，用于 MetaWorkflow 的 `configurable.thread_id`，支持评估后「是否修订」的中断与恢复；日常使用可视为与 session_id 同步。 |
| **user_id** | 用户身份 | 同一用户多次「新建对话」时 **user_id 不变**，仅 session_id 和 thread_id 更新。 |

**新建对话时**：不更换 user_id，只新建 session_id 与 thread_id。调用 `POST /api/v1/chat/new` 并传入当前 user_id 即可。

**错误响应**：

```json
{
  "success": false,
  "error": "初始化会话失败，请稍后重试。",
  "detail": "具体错误信息"
}
```

**示例代码**（Python）：

```python
import requests

resp = requests.get("http://localhost:8000/api/v1/frontend/session/init")
data = resp.json()
user_id = data["user_id"]
session_id = data["session_id"]
```

---

## 2. 新建对话接口

### `POST /api/v1/chat/new`

**用途**：新建对话，保持 user_id 不变，仅创建新的 session_id 与 thread_id。

**请求体**：

```json
{
  "user_id": "frontend_user_1706234567_a3f2c1"
}
```

**响应示例**：

```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "thread_id": "661f8511-f3bc-52e5-b827-557766551111"
}
```

---

## 3. 统一聊天接口

### `POST /api/v1/frontend/chat`

**用途**：统一处理前端聊天消息，根据 `mode` 选择不同处理流程。

**请求体**：

```json
{
  "message": "我想推广一款新的降噪耳机",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "frontend_user_1706234567_a3f2c1",
  "mode": "chat",
  "tags": ["科技", "年轻人"]
}
```

**请求字段**：

- `message` (str, 必填): 用户消息内容（自然语言或命令）
- `session_id` (str, 可选): 会话 ID；若为空或过期则自动创建新会话
- `user_id` (str, 必填): 用户唯一标识
- `mode` (str, 默认 "chat"): 处理模式
  - `"chat"`: 快速回复模式，直接调用 AI 生成简短回复（1-2句话）
  - `"deep"`: 深度思考模式，调用完整 MetaWorkflow 进行多步骤分析
- `tags` (list[str], 可选): 用户兴趣标签（仅 deep 模式使用）

### 3.1 快速回复模式 (`mode="chat"`)

**特点**：
- 响应速度快（通常 1-3 秒）
- 使用 `fast_model`（qwen-turbo）
- 适合简单问答、闲聊、指引

**响应示例**：

```json
{
  "success": true,
  "response": "当然！AI营销助手可以帮您生成营销文案、分析用户画像、优化内容策略等。您想从哪方面开始？",
  "thinking_process": [],
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "mode": "chat"
}
```

**响应字段**：

- `success` (bool): 是否成功
- `response` (str): AI 回复内容
- `thinking_process` (list): 思考过程（chat 模式为空列表）
- `session_id` (str): 会话 ID
- `mode` (str): 实际使用的模式

### 3.2 深度思考模式 (`mode="deep"`)

**特点**：
- 响应时间较长（通常 30-120 秒）
- 调用完整 MetaWorkflow，包含规划、编排、执行多个步骤
- 适合复杂营销策略、深度内容生成、多轮推理

**响应示例**：

```json
{
  "success": true,
  "response": "（完整的营销策略方案，包含品牌分析、用户画像、文案建议等，500-1000字）",
  "thinking_process": [
    {"phase": "planning", "content": "识别用户需求：降噪耳机推广..."},
    {"phase": "analysis", "content": "目标用户：年轻上班族，注重效率与品质..."},
    {"phase": "content_generation", "content": "文案策略：强调降噪技术如何提升工作效率..."}
  ],
  "content_sections": {
    "thinking_narrative": "思维链叙述内容（第一人称连贯叙述）",
    "output": "最终输出正文",
    "evaluation": "- 综合分：8/10\n- 质量评估：...",
    "suggestion": "后续建议引导内容"
  },
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "mode": "deep",
  "intent": "free_discussion"
}
```

**响应字段**：

- `success` (bool): 是否成功
- `response` (str): AI 完整回复（长文本，为各 section 拼接后的全文）
- `thinking_process` (list): 思考过程日志（每步包含 phase 和 content）
- `content_sections` (object): 结构化内容块，供前端分区渲染
  - `thinking_narrative` (str): 思维链叙述
  - `output` (str): 最终输出正文
  - `evaluation` (str): 质量评估（如有）
  - `suggestion` (str): 后续建议（如有）
- `session_id` (str): 会话 ID
- `mode` (str): 实际使用的模式
- `intent` (str): 识别的意图类型

---

## 4. 错误处理

### 3.1 会话过期（状态码 440）

当 `session_id` 无效或过期时，接口返回特定错误码 `440`，前端应捕获此错误并触发重新初始化。

**响应示例**：

```json
{
  "success": false,
  "error": "会话已过期，请重新初始化",
  "error_code": "SESSION_EXPIRED"
}
```

**前端处理建议**（伪代码）：

```python
def send_message(msg, session_id):
    resp = requests.post("/api/v1/frontend/chat", json={...})
    if resp.status_code == 440:
        # 会话过期，重新初始化
        new_session = requests.get("/api/v1/frontend/session/init").json()
        session_id = new_session["session_id"]
        # 重试请求
        resp = requests.post("/api/v1/frontend/chat", json={...})
    return resp.json()
```

### 3.2 其他错误

| 状态码 | 含义 | 示例 |
|--------|------|------|
| 400 | 请求参数错误 | message 为空、mode 无效 |
| 500 | 服务器内部错误 | AI 调用失败、数据库错误 |
| 504 | 请求超时 | deep 模式执行超过 120 秒 |

---

## 5. 最佳实践

### 5.1 会话管理

- **初始化**：应用启动时调用 `/frontend/session/init`，获取并存储 `user_id`、`session_id`、`thread_id`
- **新建对话**：点击「新建对话」时调用 `POST /api/v1/chat/new`，传入当前 `user_id`，获取新的 `session_id` 与 `thread_id`；**user_id 保持不变**
- **持久化**：将 `session_id` 存储在前端状态（如 Gradio `gr.State`、React `useState`）
- **过期处理**：捕获 440 错误，自动重新初始化

### 5.2 文档上传

- **每次上传 1 个文件**：接口单次只接收一个文件
- **每会话最多 5 个**：同一 `session_id` 下累计最多 5 个文档，超出时返回 400 错误

### 5.3 模式选择

| 场景 | 推荐模式 |
|------|---------|
| 简单问答、快速咨询 | `mode="chat"` |
| 完整营销方案、深度分析 | `mode="deep"` |
| 用户不确定 | 默认 `mode="chat"`，提供"深度分析"按钮触发 deep |

### 5.4 性能优化

- **chat 模式**：响应快，适合频繁交互，无需超时控制
- **deep 模式**：
  - 前端设置 `timeout=150` 秒（requests）或更长
  - 显示加载动画或进度条（"AI 正在深度思考，预计 1-2 分钟..."）
  - 可选：实现 WebSocket 推送中间结果（未来功能）

### 5.5 安全性

**当前版本**（演示用）：
- `user_id` 由 `/frontend/session/init` 自动生成（时间戳+随机数）
- 无认证机制，任何人可调用

**生产环境建议**：
- 前端通过认证（OAuth、JWT 等）获取真实 `user_id`
- 接口增加 API Key 或 Token 验证
- 替换 `/frontend/session/init` 为基于认证的会话创建

---

## 6. 测试

### 6.1 快速测试（命令行）

```bash
# 1. 初始化会话
curl -X GET http://localhost:8000/api/v1/frontend/session/init

# 2. Chat 模式
curl -X POST http://localhost:8000/api/v1/frontend/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好",
    "session_id": "YOUR_SESSION_ID",
    "user_id": "YOUR_USER_ID",
    "mode": "chat"
  }'

# 3. Deep 模式
curl -X POST http://localhost:8000/api/v1/frontend/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "我想推广一款耳机",
    "session_id": "YOUR_SESSION_ID",
    "user_id": "YOUR_USER_ID",
    "mode": "deep"
  }'
```

### 6.2 Python 测试脚本

运行测试脚本：

```bash
python scripts/test_frontend_api.py
```

该脚本会自动测试：
1. 会话初始化
2. Chat 模式快速回复
3. Deep 模式深度思考
4. 会话过期场景

---

## 7. 常见问题

**Q1: 为什么 deep 模式这么慢？**  
A: Deep 模式调用完整的 MetaWorkflow，包含多步骤规划、分析、内容生成、评估，通常需要 30-120 秒。如需快速响应，请使用 chat 模式。

**Q2: session_id 过期时间是多久？**  
A: 默认 3600 秒（1 小时）。可在 `SessionManager` 的 `create_session` 中通过 `ttl_seconds` 参数调整。

**Q3: 如何支持流式输出？**  
A: 当前版本为一次性返回。流式输出需改造为 Server-Sent Events (SSE) 或 WebSocket，属于未来功能。

**Q4: 能否同时使用多个会话？**  
A: 可以。每个 `session_id` 独立，前端可维护多个会话并行。例如，多个标签页各有独立 `session_id`。

---

## 8. 与现有接口的关系

| 现有接口 | 新前端接口 | 关系 |
|---------|----------|------|
| `/api/v1/chat/new` | `/api/v1/frontend/session/init` | 功能类似，前端接口增加 user_id 自动生成 |
| `/api/v1/analyze-deep/raw` | `/api/v1/frontend/chat` (deep) | 前端接口封装了 deep 模式，内部调用相同逻辑 |
| - | `/api/v1/frontend/chat` (chat) | 新增快速回复模式，简化交互 |

**建议**：
- **前端应用**：优先使用 `/api/v1/frontend/*` 接口
- **高级用户/集成**：可直接使用 `/api/v1/analyze-deep/raw` 等底层接口

---

## 9. 下一步优化方向

- [ ] 流式输出（SSE/WebSocket）
- [ ] 生产级认证（JWT、OAuth2）
- [ ] 会话持久化（数据库存储，支持跨设备同步）
- [ ] 速率限制（防止滥用）
- [ ] 多语言支持（i18n）

---

**最后更新**：2026-01-26  
**维护者**：AI 营销助手团队
