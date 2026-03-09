# 上传前验证清单

在准备上传代码前，建议按以下顺序执行，确保 E2E、能力接口与前端依赖的后端均通过。

## 1. 启动后端

```bash
uvicorn main:app --reload --port 8000
```

（或使用项目约定的端口，并设置环境变量 `BASE_URL` / `BACKEND_URL`。）

## 2. 三行业用户 E2E（闲聊 → 需求识别 → 策略脑 → 账号提升）

```bash
python scripts/run_e2e_three_industries.py
```

- 模拟教育、美妆、科技 3 个行业用户，每用户 2 轮（闲聊 + 账号提升/诊断需求）。
- 校验：会话初始化成功、每轮 `success=True`、返回中有 `response` 或 `thinking_process`。
- 若未启动后端，脚本会提示先启动并退出码 1。

## 3. 四能力接口单独调用测试

```bash
# 全部接口（含需 LLM 的慢接口）
python scripts/run_capability_apis_full_test.py

# 仅快接口（跳过 content-direction-ranking、weekly-decision-snapshot）
set SKIP_SLOW=1
python scripts/run_capability_apis_full_test.py
```

- 校验：4 个 GET 能力接口返回 200、`success=True`、数据结构符合预期（如 `data.items`、`data.matrix`、`data.priorities` 等）。
- 可选：未设 `SKIP_SLOW=1` 时会多测一项「缺 user_id 时 weekly-decision-snapshot 仍 200 + 结构」，用于补全/智能识别行为。
- 报告说明：能力接口仅返回 JSON；Word 报告在对话流中由 word_report 插件生成，下载为 `GET /api/v1/reports/{filename}`；需补全信息时由主流程澄清引导。

## 4. 前端依赖的后端接口检查

```bash
python scripts/check_frontend_backend.py
```

- 校验：`/health`、`/api/v1/frontend/session/init`、`/api/v1/memory`、`/api/v1/reports/{filename}` 路由可用且行为符合预期（记忆接口需 200 且 success 或可接受错误信息）。
- 前端默认使用 `BACKEND_URL=http://localhost:8000`，可与 `BASE_URL` 一致。

## 5. 前端界面手动检查（建议）

启动前端：

```bash
python frontend/app_enhanced.py
```

建议验证：

- **对话 Tab**：输入消息、发送，能收到回复；思维过程/策略脑展示正常。
- **记忆 Tab**：加载记忆、查看单条、清空/删除（可选），与 `GET/DELETE /api/v1/memory` 一致。
- **调试 Tab**：若有能力/缓存报告入口，请求的 URL 与后端一致，无 404。
- 报告下载：若对话中生成了 Word 报告，前端若有下载链接，应指向 `GET /api/v1/reports/{filename}` 或 `/data/reports/{filename}`（以项目实际为准）。

## 通过标准

- 步骤 2、3、4 的脚本均退出码 0。
- 步骤 5 手动检查无报错、无错误调用。
- 满足后即可视为整体通过，可上传代码。
