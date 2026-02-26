# GitHub 上传准备

## 上传前检查

- [ ] **敏感信息**：确认未提交 `.env`、`.env.dev`、`.env.prod`（已列入 `.gitignore`）
- [ ] **API Key**：文档与示例中仅使用占位符（如 `sk-your_key_here`）
- [ ] **本地验证**（可选）：`python scripts/verify_capability_apis.py` 通过后再推送

## 建议提交信息

```
feat: AI 营销助手与 Lumina 四模块能力接口

- 意图识别、记忆系统、内容生成与多插件扩展
- Lumina 四模块：内容方向榜单、案例库、内容定位矩阵、每周决策快照
- 统一对外 API 与能力路由，Docker 开发/生产部署
- 文档：README、API 参考、Lumina 映射、上传准备
```

## 上传步骤

```bash
# 1. 查看变更（确认无 .env / .env.dev / .env.prod）
git status

# 2. 添加文件
git add -A

# 3. 提交
git commit -m "feat: AI 营销助手与 Lumina 四模块能力接口"

# 4. 推送（首次可先设远程）
git remote add origin https://github.com/<你的用户名>/<仓库名>.git   # 仅首次
git push -u origin main
```

## 首次仓库创建建议

- 在 GitHub 新建仓库时可选 **不** 初始化 README，避免冲突
- 若已存在 `main` 分支且与远程有分歧，可使用 `git pull origin main --rebase` 后再 `git push`
