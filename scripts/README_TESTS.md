# 全流程测试说明

## 运行方式（独立于应用启动）

```bash
# 安装测试依赖（若未安装）
pip install -r requirements.txt

# 仅运行单元测试（无需 Redis/DB）
pytest scripts/test_new_features.py -v -k "test_plugin_bus or test_input_processor"

# 运行全部用例（集成测试在无 REDIS_URL/DATABASE_URL 时自动跳过）
pytest scripts/test_new_features.py -v
```

## 用例与验证点

| 用例 | 类型 | 验证 |
|------|------|------|
| `test_plugin_bus_document_query_routing` | 单元 | 插件总线路由 DocumentQueryEvent，插件可写回 `enhanced` |
| `test_input_processor_command_new_chat` | 单元 | `/new_chat` 返回 intent=command、command=new_chat |
| `test_input_processor_free_text_mocked` | 单元 | 自由文本经 mock AI 返回 free_discussion 与 raw_query |
| `test_api_new_chat_command` | 集成 | POST analyze-deep/raw 发送 /new_chat，返回正确 intent/command |
| `test_api_chat_new_creates_thread_and_session` | 集成 | POST chat/new 返回 thread_id、session_id |
| `test_api_upload_pdf_and_list` | 集成 | 上传 PDF 后文档入库，GET documents 可查元信息 |
| `test_api_structured_input` | 集成 | POST analyze-deep（JSON）返回 session_id（需 DASHSCOPE_API_KEY） |
| `test_api_free_text_input` | 集成 | POST analyze-deep/raw 自由文本返回 intent 与结果（需 DASHSCOPE_API_KEY） |

## 环境要求

- **单元测试**：无外部依赖，可直接运行。
- **集成测试**：需 `REDIS_URL`、`DATABASE_URL`（缺则自动跳过）。
- **深度分析相关**：`test_api_structured_input`、`test_api_free_text_input` 需 `DASHSCOPE_API_KEY`（缺则跳过）。
