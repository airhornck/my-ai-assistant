# 前端验证端故障排查

## 快速验证

运行前后端连接验证脚本（需先启动后端）：

```bash
# 1. 启动后端
uvicorn main:app --reload

# 2. 另开终端，运行验证
python scripts/diagnose_chat.py
```

若验证通过，说明 API 连接正常；若仍无法在浏览器中验证，多为 Gradio 或浏览器端问题。

## share-modal.js addEventListener 错误

**现象**：控制台报 `Uncaught TypeError: Cannot read properties of null (reading 'addEventListener')`，位于 `share-modal.js`。

**原因**：Gradio 6.x 在 `share=False` 时，部分分享相关 DOM 未渲染，但脚本仍尝试绑定事件，属于 Gradio 内部问题。

**影响**：通常不影响核心功能。若输入无反应，请优先检查下方「连接重置」项。

**可选尝试**：
1. 升级 Gradio：`pip install -U "gradio>=6.5.0"`（升级后仍可能报错）
2. 已在 `app_enhanced.py` 中通过 `footer_links=[]` + `css` 强制隐藏页脚，减少触发
3. 若 ID 为空，点击「新建对话」手动初始化
4. 刷新页面、更换浏览器（Chrome / Edge 无痕模式）
5. 该报错多为非致命，若对话能正常收发，可暂时忽略

---

## ERR_CONNECTION_RESET / 输入无反应

**现象**：发送消息后无响应，控制台出现 `ERR_CONNECTION_RESET`、`network error`。

**排查步骤**：

1. **确认后端已启动**  
   前端依赖后端 API，需先运行：
   ```bash
   uvicorn main:app --reload
   ```
   默认监听 http://localhost:8000。

2. **检查后端连通性**  
   在浏览器访问：`http://localhost:8000/docs`，应能打开 Swagger 文档。

3. **检查 User ID / Session ID**  
   页面加载后，左侧应显示 User ID、Session ID、Thread ID。若为空或显示「会话初始化失败」，说明前端无法连接后端。

4. **长时间请求（深度思考）**  
   深度思考约 30–120 秒，可能触发浏览器或代理超时。可先使用普通 Chat 模式验证。

---

## 验证端使用说明

- **User ID / Session ID / Thread ID**：用于确认会话是否正常初始化。
- **策略脑执行过程**：右侧展示深度思考的步骤与结果，用于检查模型返回是否符合预期。
- **新建对话**：位于左侧顶部，用于重置会话并获取新的 ID。
