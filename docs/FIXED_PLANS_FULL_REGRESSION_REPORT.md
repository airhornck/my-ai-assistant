# 固定 Plan 全量旅程回归报告

## 批次 1（对话 1）：账号打造 account_building
- **account_building**: step_outputs=5 issues=无

## 批次 1（对话 2）：内容矩阵 content_matrix
- **content_matrix**: step_outputs=5 issues=无

### ── 新对话（批次 2）──

## 批次 2（对话 3）：IP 诊断 ip_diagnosis
- **ip_diagnosis**: step_outputs=2 issues=无

## 批次 2（对话 4）：能力 — 内容方向榜单
- **cap_content_direction_ranking** (`capability_content_direction_ranking`): steps_done=2/2 issues=无

### ── 新对话（批次 3）──

## 批次 3：能力 — 案例库 + 内容定位矩阵
- **cap_case_library** (`capability_case_library`): steps_done=2/2 issues=无
- **cap_positioning_matrix** (`capability_content_positioning_matrix`): steps_done=2/2 issues=无

### ── 新对话（批次 4）──

## 批次 4：能力 — 每周决策快照
- **cap_weekly_snapshot** (`capability_weekly_decision_snapshot`): steps_done=4/4 issues=无

## 长对话 stress（≈30 轮）：闲聊 + 账号打造直至 done
- **stress**: 前置轮次≈23 + 推进轮次上限35；最终 phase='done' step_outputs=5 issues=无

## 汇总：已知问题与修复状态

## 问题列表（本轮检测）
- [account_building] 无异常
- [content_matrix] 无异常
- [ip_diagnosis] 无异常
- [cap_content_direction_ranking] 无异常
- [cap_case_library] 无异常
- [cap_positioning_matrix] 无异常
- [cap_weekly_snapshot] 无异常
- [stress_30_rounds] 无异常

## 已修复项（代码现状，供对照）
- DashScopeLLMClient 增加 `ainvoke`，分析插件与 IP casual_reply 不再报 `ainv` 缺失。
- IP 执行失败追问：支持「重试/跳过/好的」等，避免死循环重复同一错误。
- `plan_template_name` 写入 state / API / 前端策略脑展示；计划就绪文案含模板展示名。
- 流式与会话写回包含 `plan_template_name`。
- `intake_guide.infer_fields`：建/开/注册账号、内容矩阵话术、品牌名叫/品牌叫、流量/诊断等补全，避免卡在 intake。
- 自动化回归中：若 `pending_questions` 含 `platform`，后续轮次自动带 `platform=B站` 以跑完含 `generate` 的固定 Plan。

## 附录：全量测试过程中曾暴露的问题（均已对照修复）
| # | 现象 | 处理 |
|---|------|------|
| 1 | 插件调用 `llm.ainvoke`，DashScope 客户端无此方法 | `DashScopeLLMClient.ainvoke` 返回 `AIMessage` |
| 2 | 执行失败后用户答「好的」反复重试同一步 | `execute_one_step_node` 识别 `_error` 追问并重试/跳过 |
| 3 | 计划展示名未出现在 API/策略脑 | `plan_template_name` 全链路 + 文案 `_ip_build_plan_ready_message` |
| 4 | 「建一个账号」未推断 topic，「品牌叫X」未推断 brand | 扩展 `infer_fields` 规则 |
| 5 | generate 缺 platform 卡住 executing | 测试脚本遇 `platform` 追问自动补全；真实用户需选平台 |
