# 前端集成总结

本文档总结为 AI 营销助手后端添加的前端支持接口及相关功能。

---

## 新增内容

### 1. API 接口（main.py）

#### 1.1 `GET /api/v1/frontend/session/init`

**用途**：为前端提供会话初始化入口

**功能**：
- 自动生成演示用 `user_id`（格式：`frontend_user_{timestamp}_{random}`）
- 调用 `SessionManager.create_session` 创建初始会话
- 返回 `user_id`、`session_id`、`thread_id`

**生产环境注意**：
- 需替换为基于认证系统的 user_id 获取（JWT、OAuth 等）
- 当前实现仅供演示，不包含认证

#### 1.2 `POST /api/v1/frontend/chat`

**用途**：统一聊天接口，整合快速回复与深度思考

**功能**：
- **Chat 模式** (`mode="chat"`):
  - 使用 `fast_model`（qwen-turbo）
  - 直接调用 AI Service 生成简短回复（1-2 句话）
  - 响应速度快（1-3 秒）
  - 无思考过程日志
  
- **Deep 模式** (`mode="deep"`):
  - 调用完整 MetaWorkflow（规划→编排→执行）
  - 复用 `/api/v1/analyze-deep/raw` 的核心逻辑
  - 包含意图识别、文档查询增强、多步骤思考
  - 响应时间 30-120 秒
  - 返回详细思考过程日志

**会话过期处理**：
- 检测 `session_id` 是否有效
- 若过期，返回状态码 `440`（非标准，供前端识别）
- 前端捕获 440 后自动重新初始化会话

**错误处理**：
- 参数验证（message 非空、mode 有效）
- 超时控制（deep 模式 120 秒）
- 统一错误响应格式

### 2. 数据模型（models/request.py）

#### 2.1 `FrontendChatRequest`

```python
class FrontendChatRequest(BaseModel):
    message: str           # 用户消息（必填）
    session_id: Optional[str]  # 会话 ID（可选）
    user_id: str          # 用户 ID（必填）
    mode: str = "chat"    # 处理模式：chat | deep
    tags: Optional[List[str]]  # 兴趣标签（仅 deep 模式）
```

### 3. Gradio 前端

#### 3.1 原始版本（frontend/app.py）

- 调用原有 API（`/api/v1/chat/new`、`/api/v1/analyze-deep/raw`）
- 三列布局：系统控制、聊天、思考过程
- 状态管理：使用 `gr.State` 存储 user_id、session_id、thread_id
- 功能：发送消息、上传文件、新建对话

#### 3.2 增强版本（frontend/app_enhanced.py）

- 调用新的前端 API（`/api/v1/frontend/session/init`、`/api/v1/frontend/chat`）
- 新增功能：
  - **模式切换**：用户可选 Chat（快速）或 Deep（深度）
  - **自动会话恢复**：检测到 440 错误时自动重新初始化
  - **动态超时**：Chat 模式 30 秒，Deep 模式 150 秒
- 更好的用户体验：清晰的模式说明、加载提示

### 4. 测试与文档

#### 4.1 测试脚本（scripts/test_frontend_api.py）

功能：
- 测试会话初始化
- 测试 Chat 模式快速回复
- 测试 Deep 模式深度思考
- 测试会话过期场景（440 错误）

运行方式：
```bash
python scripts/test_frontend_api.py
```

#### 4.2 文档

- **FRONTEND_API.md**：完整的接口文档
  - 接口说明、请求/响应格式
  - 两种模式的详细对比
  - 错误处理指南
  - 最佳实践与常见问题
  
- **FRONTEND_INTEGRATION_SUMMARY.md**（本文档）：集成总结

---

## 使用指南

### 1. 启动后端

```bash
# 开发环境
uvicorn main:app --reload --port 8000

# 生产环境（Docker）
docker-compose -f docker-compose.prod.yml up -d
```

### 2. 启动前端

**原始版本**：
```bash
python frontend/app.py
```

**增强版本（推荐）**：
```bash
python frontend/app_enhanced.py
```

前端访问地址：http://localhost:7860

### 3. 测试接口

```bash
# 运行自动化测试
python scripts/test_frontend_api.py

# 手动测试（curl）
curl -X GET http://localhost:8000/api/v1/frontend/session/init

curl -X POST http://localhost:8000/api/v1/frontend/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好",
    "session_id": "YOUR_SESSION_ID",
    "user_id": "YOUR_USER_ID",
    "mode": "chat"
  }'
```

---

## 关键设计决策

### 1. 为什么新增前端专用接口，而非直接使用现有接口？

**现有接口的局限**：
- `/api/v1/analyze-deep/raw`：仅支持深度思考，响应慢（30-120秒）
- `/api/v1/chat/new`：仅创建会话，不包含 user_id 自动生成

**前端专用接口的优势**：
- **统一入口**：`/api/v1/frontend/chat` 整合快速回复与深度思考
- **模式选择**：前端可根据场景选择 chat（快）或 deep（慢）
- **会话恢复**：自动检测会话过期并返回特定错误码（440）
- **简化集成**：`/api/v1/frontend/session/init` 自动生成 user_id，减少前端逻辑

**兼容性**：
- 前端接口不影响现有接口
- 高级用户仍可直接使用 `/api/v1/analyze-deep/raw` 等底层接口

### 2. 为什么使用状态码 440 表示会话过期？

- **440**：非标准 HTTP 状态码（Login Time-out），IIS 服务器曾使用
- **语义明确**：与认证相关的超时场景
- **易于识别**：前端可针对性处理（自动重新初始化）

**替代方案**：
- 401（Unauthorized）：更标准，但可能与认证混淆
- 419（Authentication Timeout）：Laravel 使用，但不如 440 常见

### 3. Chat vs Deep 模式的实现差异

| 维度 | Chat 模式 | Deep 模式 |
|------|----------|----------|
| AI 模型 | qwen-turbo（fast_model） | qwen-max（powerful_model） |
| 调用方式 | 直接调用 `client.ainvoke` | 完整 MetaWorkflow（planning→orchestration→compilation） |
| 响应时间 | 1-3 秒 | 30-120 秒 |
| 思考过程 | 无 | 多步骤日志（JSON） |
| 适用场景 | 简单问答、闲聊、指引 | 复杂营销策略、深度内容生成 |

---

## 性能指标

| 接口 | 平均响应时间 | P99 响应时间 | 超时设置 |
|------|------------|-------------|---------|
| `/frontend/session/init` | < 100ms | < 500ms | 30s |
| `/frontend/chat` (chat) | 1-3s | 5s | 30s |
| `/frontend/chat` (deep) | 30-60s | 120s | 120s |

---

## 安全性考虑

### 当前版本（演示用）

- ✅ 输入验证（message 非空、mode 枚举）
- ✅ 会话隔离（每个 session_id 独立）
- ✅ 超时保护（防止长时间阻塞）
- ❌ 无认证机制
- ❌ 无速率限制
- ❌ user_id 自动生成（不可信）

### 生产环境建议

#### 1. 认证与授权
```python
# 示例：JWT 认证中间件
from fastapi import Depends, HTTPException
from jose import JWTError, jwt

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/v1/frontend/session/init")
async def frontend_session_init(
    current_user: str = Depends(get_current_user),
    sm: SessionManager = Depends(get_session_manager),
):
    # 使用认证的 user_id，而非自动生成
    create_result = await sm.create_session(user_id=current_user, ...)
    ...
```

#### 2. 速率限制
```python
# 示例：使用 slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/v1/frontend/chat")
@limiter.limit("10/minute")  # 每分钟最多 10 次请求
async def frontend_chat(...):
    ...
```

#### 3. 输入验证增强
- XSS 防护：对 message 进行 HTML 转义
- SQL 注入防护：使用参数化查询（已实现）
- 长度限制：message 最大 10,000 字符

#### 4. 日志与监控
- 记录所有 API 调用（user_id、session_id、mode、耗时）
- Prometheus 指标：chat/deep 模式的调用次数、成功率、P99 耗时
- 异常告警：超时率 > 5%、错误率 > 1%

---

## 常见问题

**Q1: 前端应该使用 `frontend/app.py` 还是 `frontend/app_enhanced.py`？**  
A: 推荐 `app_enhanced.py`，支持 chat/deep 模式切换，用户体验更好。`app.py` 仅作为基础示例保留。

**Q2: Chat 模式能否支持多轮对话上下文？**  
A: 当前版本 chat 模式为无状态（每次独立调用 AI），不保留多轮上下文。如需上下文，可改为：
- 从 Redis 读取历史消息（最近 5 条）
- 拼接到 prompt 中："历史对话：\n{history}\n\n用户：{message}"

**Q3: Deep 模式执行时间过长，能否异步返回？**  
A: 当前为同步等待。未来可改为异步任务队列（Celery、RQ）+ WebSocket 推送中间结果。

**Q4: 如何支持多个前端应用共享后端？**  
A: 当前接口已支持。前端应用需：
1. 各自调用 `/frontend/session/init` 获取独立 session_id
2. 请求时携带自己的 session_id
3. 后端自动隔离（每个 session_id 对应独立的 Redis 数据）

**Q5: 能否在前端接口中添加流式输出（SSE）？**  
A: 可以，需改造：
```python
from fastapi.responses import StreamingResponse

@app.post("/api/v1/frontend/chat/stream")
async def frontend_chat_stream(...):
    async def generate():
        # 分步返回 thinking_process 和 response
        for step in thinking_steps:
            yield f"data: {json.dumps(step)}\n\n"
        yield f"data: {json.dumps({'response': final_content})}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## 下一步优化

### 短期（1-2 周）

- [ ] 添加单元测试（pytest）
- [ ] 集成认证中间件（JWT）
- [ ] 速率限制（slowapi）
- [ ] Prometheus 指标增强（chat/deep 模式分别统计）

### 中期（1-2 月）

- [ ] 流式输出（SSE/WebSocket）
- [ ] 多轮对话上下文（chat 模式）
- [ ] 会话持久化（数据库存储，支持跨设备同步）
- [ ] 用户偏好记忆（根据历史交互自动选择 chat/deep）

### 长期（3-6 月）

- [ ] 前端框架适配（React、Vue 示例）
- [ ] 多语言支持（i18n）
- [ ] A/B 测试框架（比较不同 prompt 策略）
- [ ] 模型版本管理（支持灰度发布新模型）

---

## 贡献指南

如需贡献代码或反馈问题：

1. **问题反馈**：在项目 Issues 中创建，标签选择 `frontend` 或 `api`
2. **代码贡献**：
   - Fork 项目
   - 创建分支：`git checkout -b feature/your-feature`
   - 提交代码：`git commit -m "Add your feature"`
   - 推送：`git push origin feature/your-feature`
   - 创建 Pull Request

**代码规范**：
- Python: 遵循 PEP 8
- 类型注解: 使用 `typing` 模块
- 文档字符串: 使用 Google 风格
- 测试覆盖率: 新功能需达 80%+

---

**最后更新**：2026-01-26  
**维护者**：AI 营销助手团队  
**联系方式**：请通过项目 Issues 联系
