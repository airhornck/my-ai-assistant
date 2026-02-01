# 知识库

存放 `marketing_knowledge.md` 等 Markdown 文档，供 RetrievalService 向量检索使用。

- **首次运行**：RetrievalService 会自动加载本目录下的 `*.md`，分块并调用阿里云 Dashscope 嵌入 API，持久化到 `./data/knowledge_vectors/vectors.json`。后续请求直接使用已建索引，响应更快。
- **更新文档**：修改或新增 `.md` 后，删除 `./data/knowledge_vectors/` 目录，下次检索时会重建向量库。
- 可添加更多 `.md` 文件以扩展行业知识。
