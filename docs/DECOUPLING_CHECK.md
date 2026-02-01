# 模块化解耦检查报告

## 一、解耦设计原则（参考 DECOUPLING_DESIGN.md）

1. **依赖方向**：main → domain → core，避免反向依赖
2. **依赖注入**：模块通过构造函数/参数注入依赖，而非内部 new
3. **接口抽象**：核心能力（如 LLM）通过协议抽象，可替换实现
4. **单一职责**：每个模块只负责一类能力

---

## 二、检查发现

### ✅ 已符合解耦要求

| 模块 | 说明 |
|------|------|
| **core/ai** | ILLMClient 协议 + DashScope 实现，可替换 |
| **domain/content** | Analyzer/Generator/Evaluator 依赖 ILLMClient 注入 |
| **core/intent** | InputProcessor 依赖 SimpleAIService 注入 |
| **core/document** | SessionDocumentBinding 依赖 db 注入 |
| **main.py** | 使用 Depends 注入 SessionManager、AI、DB 等 |
| **workflows/basic_workflow** | 接收 ai_service 参数，非内部实例化 |

### ⚠️ 需优化项

| 问题 | 位置 | 说明 |
|------|------|------|
| **1. meta_workflow 硬编码依赖** | `meta_workflow.py` | WebSearcher、MemoryService 在 build 内部 new，WebSearcher 写死 provider="mock" |
| **2. meta_workflow 访问私有属性** | `meta_workflow.py:71` | `ai_svc._llm` 直接访问，违反封装 |
| **3. meta_workflow 死代码** | `meta_workflow.py:72-74` | 创建 analyzer/generator/evaluator 但从未使用，orchestration 全部走 ai_svc |
| **4. campaign_planner 错误属性** | `campaign_planner.py:75` | `ai_svc.client` 不存在，应使用 `ai_svc.router` |
| ~~**5. main 直接 new SessionDocumentBinding**~~ | ~~`main.py`~~ | **已修复**：frontend_chat 现使用 `Depends(get_session_document_binding)` 注入 |

### ✅ 前端验证现状

| 项目 | 现状 | 建议 |
|------|------|------|
| 空输入校验 | 有（send_message 内） | 保持 |
| 会话过期 440 | 有处理，会重试 | 保持 |
| mode 校验 | 后端校验，前端 Radio 限制 | 可增加前端二次校验 |
| 文件类型 | file_types=[".pdf",".txt",".docx"] | 与后端一致 |
| 上传前 session 校验 | 有 | 保持 |
| 错误展示 | gr.Warning + thinking_json | 可统一错误格式 |
| 输入长度 | history 每条截断 500 字 | 合理 |

---

## 三、修复方案

### 1. meta_workflow：支持依赖注入

- `build_meta_workflow(ai_service, web_searcher=None, memory_service=None, ...)`
- 默认 `web_searcher=WebSearcher(provider="mock")`，生产可注入真实实现
- 移除未使用的 analyzer/generator/evaluator 创建
- 策略脑直接用 `ai_svc._llm` 改为：通过 ai_svc 暴露 `get_llm()` 或新增 `planning_prompt()` 方法；为减少改动，可保留 `_llm` 访问但加注释说明（门面内部协调）

### 2. campaign_planner：修复 client 调用

- `ai_svc.client` → `ai_svc.router`，使用 `await (await ai_svc.router.route(...)).ainvoke(messages)`
- 或：在 SimpleAIService 中增加 `client = router` 别名以兼容旧代码

### 3. 前端：已实施的优化

- ✅ 抽出 `frontend/config.py` 统一后端地址、超时、文件类型等配置
- ✅ 输入长度校验（MAX_INPUT_LENGTH=2000）
- ✅ 模式二次校验（chat/deep）
- ✅ 文件类型前端校验（与后端一致）
