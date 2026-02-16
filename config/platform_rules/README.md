# 平台规则配置

各平台限流规则、敏感词、违禁画面等。支持热更新（调用 `reload()`）。

- 单文件多平台：`bilibili: { ... }`
- 可与 `config/diagnosis_thresholds.yaml` 合并
- 环境变量 `PLATFORM_RULES_DIR` 可覆盖目录路径
