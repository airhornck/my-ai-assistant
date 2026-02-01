# 配置模块

## media_specs.py：媒体平台生成规范

各媒体（B站、小红书、抖音、微博等）的生成提示词、风格要求在此统一维护。

### 新增媒体平台

1. 在 `media_specs.py` 中新增 `MediaSpec` 实例：

```python
NEW_PLATFORM_SPEC = MediaSpec(
    key="new_platform",
    name="新平台名称",
    keywords=["平台名", "英文名", "别名"],  # 用于从用户输入中匹配
    system_prompt="系统角色与能力描述...",
    requirements="""1. 要求一
2. 要求二
...""",
)
```

2. 将新 spec 加入 `MEDIA_SPECS` 列表（顺序影响匹配优先级）：

```python
MEDIA_SPECS: List[MediaSpec] = [
    BILIBILI_SPEC,
    XIAOHONGSHU_SPEC,
    NEW_PLATFORM_SPEC,  # 新增
    ...
]
```

### 匹配逻辑

`resolve_media_spec(topic, raw_query)` 会：
- 按 `MEDIA_SPECS` 顺序检查用户输入是否包含某平台的 `keywords`
- 首次匹配即返回该平台规范
- 无匹配时返回 `GENERIC_SPEC`（通用规范）

### 使用位置

- `services/ai_service.py` 的 `generate()` 调用 `resolve_media_spec` 和 `build_user_prompt`
- `main.py` 的 `frontend_chat` 调用 `needs_clarification` 和 `get_clarification_response`

### 澄清逻辑（交互式流程）

当用户仅描述产品/目标人群（如「推广降噪耳机，目标18-35年轻人」），未指定平台或篇幅时：

1. `needs_clarification(raw_query, topic, product_desc)` 返回 `True`
2. 返回 `get_clarification_response(product_summary)` 引导用户补充：
   - 发布平台（B站/小红书/抖音/微博等）
   - 篇幅要求（完整文稿/简短简介/画报介绍等）
3. 用户补充后再次发送，再进入生成流程
