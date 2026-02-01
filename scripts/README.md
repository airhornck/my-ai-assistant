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
```
