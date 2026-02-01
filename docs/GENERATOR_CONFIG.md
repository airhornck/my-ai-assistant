# 生成脑模块配置

生成脑已模块化：**文本**、**图片**、**视频** 分别配置不同模型接口。

## 文本模块（已实现）

- **模型**：qwen3-max
- **配置**：`config/api_config.py` 的 `generation_text` 接口；`generator_config` 为兼容层
- **环境变量**：
  - `DASHSCOPE_API_KEY` 或 `GENERATOR_TEXT_API_KEY`：API Key
  - `GENERATOR_TEXT_MODEL`：模型名，默认 `qwen3-max`
  - `GENERATOR_TEXT_BASE_URL`：可选，默认 DashScope 兼容地址

## 图片模块（占位）

待接入文生图等接口时配置：

- `GENERATOR_IMAGE_MODEL`
- `GENERATOR_IMAGE_API_KEY`
- `GENERATOR_IMAGE_BASE_URL`（可选）

## 视频模块（占位）

待接入文生视频等接口时配置：

- `GENERATOR_VIDEO_MODEL`
- `GENERATOR_VIDEO_API_KEY`
- `GENERATOR_VIDEO_BASE_URL`（可选）

## 策略脑调用

在规划步骤中可指定 `output_type`：

```json
{"step": "generate", "params": {"platform": "B站", "output_type": "text"}}
{"step": "generate", "params": {"output_type": "image"}}
{"step": "generate", "params": {"output_type": "video"}}
```

缺省为 `text`。
