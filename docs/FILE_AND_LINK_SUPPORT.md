# 文件与链接支持说明

## 一、支持的文件格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| PDF | .pdf | pypdf 解析 |
| 纯文本 | .txt, .md, .markdown | 直接读取 |
| Word | .docx | python-docx 解析 |
| PowerPoint | .pptx | python-pptx 解析（.ppt 旧格式需先转换为 .pptx） |
| 图片 | .jpg, .jpeg, .png, .gif, .webp, .bmp, .tiff, .tif | OCR 提取文字（需安装 Tesseract-OCR） |

## 二、图片 OCR 前置条件

- **pytesseract**：`pip install pytesseract Pillow`
- **Tesseract-OCR**：需在系统安装
  - Windows：从 https://github.com/UB-Mannheim/tesseract/wiki 下载安装
  - macOS：`brew install tesseract tesseract-lang`
  - Linux：`apt install tesseract-ocr tesseract-ocr-chi-sim`

未安装 Tesseract 时，图片解析将返回空字符串，不影响其他格式。

## 三、对话中的链接解析

用户可在输入中粘贴 http/https 链接，系统会：
1. 从消息中提取最多 5 个链接
2. 异步抓取网页内容
3. 使用 trafilatura 或 readability 提取主文
4. 将内容注入到对话上下文中供 AI 引用

**限制**：
- 单链接最多 5000 字符
- 超时 10 秒
- 抓取失败时跳过该链接，不阻断流程

## 四、涉及模块

- **core/document/parser.py**：文档解析（PPT、MD、图片等）
- **core/link/parser.py**：链接提取与抓取
- **main.py**：frontend_chat、analyze_deep_raw 中集成 link_context
- **frontend/config.py**：ALLOWED_FILE_TYPES 与后端对齐
