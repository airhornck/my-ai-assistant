# 脚本说明

## 诊断与验证

| 脚本 | 用途 |
|------|------|
| `check_syntax.py` | 语法检查、main 导入、路由重复检测 |
| `diagnose_chat.py` | 对话接口诊断（模拟前端请求） |
| `test_frontend_api.py` | 前端 API 接口测试（init、闲聊、创作、会话过期） |

根目录 `check_backend.py`：后端服务完整诊断（health、Docker、Redis、API 端点）。

## 测试

| 脚本 | 用途 |
|------|------|
| `test_new_features.py` | 单元测试与集成测试，见 README_TESTS.md |
| `conftest.py` | pytest 配置与 fixture |
| `run_memory_regression.py` | **记忆模块全面回归**：执行 step1/2/3/5/7 的 pytest（需 DATABASE_URL、REDIS_URL） |
| `verify_capability_apis.py` | **四能力接口校验**：请求 4 个 GET 并校验结构（需先启动服务） |
| `run_capability_apis_content.py` | **四能力接口产出内容**：请求 4 个 GET 并打印响应内容（需先启动服务） |
| `run_capability_apis_with_testclient.py` | 同上，使用 TestClient（需 REDIS_URL、DATABASE_URL、AI 已初始化） |
| `test_capability_apis.py` | 四能力接口 pytest 结构测试（需集成环境 + 可选 DASHSCOPE_API_KEY） |

## 迁移

| 脚本 | 用途 |
|------|------|
| `add_session_documents.sql` | 手动创建 session_documents 表（若未自动建表） |
| `add_brand_memory_columns.sql` | 为 user_profiles 添加 brand_facts、success_cases 列 |

## 运行示例

```bash
# 语法与导入检查
python scripts/check_syntax.py

# 对话诊断
python scripts/diagnose_chat.py

# 后端完整诊断
python check_backend.py

# 记忆模块全面回归测试（需 DATABASE_URL、REDIS_URL）
python scripts/run_memory_regression.py

# 四能力接口：先启动服务后再运行，查看访问产出内容
# uvicorn main:app --reload --port 8000
python scripts/run_capability_apis_content.py
# 仅快速接口、跳过 LLM：SKIP_SLOW=1 python scripts/run_capability_apis_content.py

# 四能力接口结构校验（同上，需服务已启动）
python scripts/verify_capability_apis.py
```
