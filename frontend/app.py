"""
AI 营销助手 Gradio 前端：三列布局，支持自由文本、命令、文档上传，实时展示思考过程。
启动：python frontend/app.py
环境变量：BACKEND_URL（默认 http://localhost:8000）
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Union

import gradio as gr
import requests

# ===== 配置：后端 API 地址 =====
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
DEFAULT_USER_ID = "gradio_user_001"

# Gradio 6.x 使用新的消息格式：List[Dict] 而不是 List[Tuple]
# 每条消息格式：{"role": "user"|"assistant", "content": "..."}
ChatHistory = List[Dict[str, str]]


# ===== 辅助函数：HTTP 调用与错误处理 =====


def _request(
    method: str,
    endpoint: str,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    统一 HTTP 调用：返回 (success, response_json, error_message)。
    """
    url = f"{BACKEND_URL}{endpoint}"
    try:
        if method.upper() == "GET":
            r = requests.get(url, params=json or {}, timeout=timeout)
        elif method.upper() == "POST":
            if files:
                r = requests.post(url, data=data, files=files, timeout=timeout)
            else:
                r = requests.post(url, json=json, timeout=timeout)
        else:
            return False, None, f"不支持的 HTTP 方法: {method}"
        r.raise_for_status()
        resp = r.json()
        return True, resp, None
    except requests.exceptions.Timeout:
        return False, None, "请求超时，请稍后重试。"
    except requests.exceptions.ConnectionError:
        return False, None, f"无法连接到后端 ({BACKEND_URL})，请检查服务是否启动。"
    except requests.exceptions.HTTPError as e:
        try:
            err_body = e.response.json()
            msg = err_body.get("error", str(e))
        except Exception:
            msg = str(e)
        return False, None, f"HTTP {e.response.status_code}: {msg}"
    except Exception as e:
        return False, None, f"请求失败: {str(e)}"


# ===== 初始化：创建新会话 =====


def init_session(user_id: str) -> Tuple[str, str, str]:
    """
    应用启动时调用后端 /api/v1/chat/new 创建对话链，返回 (user_id, session_id, thread_id)。
    """
    success, resp, err = _request("POST", "/api/v1/chat/new", json={"user_id": user_id})
    if not success or not resp:
        gr.Warning(f"初始化会话失败: {err}")
        return user_id, "", ""
    session_id = (resp.get("session_id") or "").strip()
    thread_id = (resp.get("thread_id") or "").strip()
    if session_id:
        gr.Info(f"✅ 已创建新对话链：thread={thread_id[:8] if thread_id else '-'}..., session={session_id[:8]}...")
    return user_id, session_id, thread_id


# ===== 核心交互函数 =====


def send_message(
    user_input: str,
    history: ChatHistory,
    user_id: str,
    session_id: str,
    thread_id: str,
) -> Tuple[ChatHistory, str, Any]:
    """
    发送用户输入到后端 /api/v1/analyze-deep/raw，返回更新后的对话历史与思考过程（JSON）。
    """
    if not user_input or not user_input.strip():
        gr.Warning("输入为空，请输入内容。")
        return history, "", ""

    # 若无 session_id（首次请求），先初始化
    if not session_id or not session_id.strip():
        user_id, session_id, thread_id = init_session(user_id)

    # 调用后端 /api/v1/analyze-deep/raw
    success, resp, err = _request(
        "POST",
        "/api/v1/analyze-deep/raw",
        json={"user_id": user_id, "raw_input": user_input, "session_id": session_id},
        timeout=120.0,
    )
    if not success or not resp:
        gr.Warning(f"❌ 请求失败: {err}")
        return history, "", f"错误: {err}"

    intent = resp.get("intent", "")
    # 若为 command，直接提示
    if intent == "command":
        cmd = resp.get("command", "")
        msg = resp.get("message", "")
        gr.Info(f"命令已识别: /{cmd}")
        # Gradio 6.x 新消息格式
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": f"[命令] {msg}"})
        return history, "", f'{{"intent": "command", "command": "{cmd}"}}'

    # 正常分析结果（兼容 data / response；thinking 可能为 thinking_logs）
    ai_reply = (resp.get("data") or resp.get("response") or "").strip()
    thinking = resp.get("thinking_process") or resp.get("thinking_logs") or []
    new_session_id = (resp.get("session_id") or session_id) or session_id

    # 若有待补充问题且无正文，用问题列表作为回复展示
    if not ai_reply and (resp.get("pending_questions") or []):
        lines = ["请补充以下信息："]
        for q in (resp.get("pending_questions") or [])[:5]:
            if isinstance(q, dict) and q.get("question"):
                lines.append(f"• {q.get('question', '')}")
        ai_reply = "\n".join(lines)

    # 更新对话历史（Gradio 6.x 新格式：字典列表）
    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": ai_reply or "暂无回复"})

    # 返回思考过程（JSON 显示）
    thinking_json = {
        "intent": intent,
        "session_id": new_session_id,
        "phase": resp.get("phase", ""),
        "pending_questions": resp.get("pending_questions", []),
        "思考过程": thinking,
    }
    return history, new_session_id, thinking_json


def upload_file(
    file,
    user_id: str,
    session_id: str,
) -> str:
    """上传文件并绑定到当前会话（类似 OpenAI 在对话中附加文件）。"""
    if file is None:
        gr.Warning("未选择文件。")
        return "未选择文件。"
    if not session_id or not str(session_id).strip():
        gr.Warning("会话未初始化，请先发送消息或刷新。")
        return "请先初始化会话"
    try:
        with open(file.name, "rb") as f:
            files = {"file": (os.path.basename(file.name), f, "application/octet-stream")}
            data_form = {"user_id": user_id, "session_id": session_id.strip()}
            success, resp, err = _request(
                "POST",
                "/api/v1/documents/upload",
                data=data_form,
                files=files,
                timeout=60.0,
            )
        if not success or not resp:
            gr.Warning(f"❌ 上传失败: {err}")
            return f"上传失败: {err}"
        doc = resp.get("data", {})
        doc_id = doc.get("doc_id", "")
        filename = doc.get("original_filename", "")
        gr.Info(f"✅ 文件已上传：{filename} (doc_id={doc_id[:12]}...)")
        return f"上传成功：{filename}\ndoc_id: {doc_id}\n存储路径: {doc.get('storage_path', '')}"
    except Exception as e:
        gr.Warning(f"❌ 上传异常: {str(e)}")
        return f"上传异常: {str(e)}"


def new_chat(user_id: str) -> Tuple[ChatHistory, str, str, Any]:
    """
    调用后端 /api/v1/chat/new，重置聊天历史并获取新 session_id 与 thread_id。
    """
    success, resp, err = _request("POST", "/api/v1/chat/new", json={"user_id": user_id})
    if not success or not resp:
        gr.Warning(f"❌ 新建对话链失败: {err}")
        return [], "", "", f"错误: {err}"
    new_session_id = (resp.get("session_id") or "").strip()
    new_thread_id = (resp.get("thread_id") or "").strip()
    gr.Info(f"✅ 新建对话链：thread={new_thread_id[:8] if new_thread_id else '-'}..., session={new_session_id[:8] if new_session_id else '-'}...")
    return [], new_session_id, new_thread_id, f'{{"thread_id": "{new_thread_id}", "session_id": "{new_session_id}"}}'


# ===== Gradio 界面 =====


def build_ui():
    """构建三列布局的 Gradio 界面。"""
    # 创建 Blocks（Python 3.14 兼容模式：移除 theme 和 css 参数）
    demo = gr.Blocks(title="AI 营销助手")
    
    with demo:
        gr.Markdown("# 🚀 AI 营销助手")

        # 会话状态（gr.State）
        state_user_id = gr.State(value=DEFAULT_USER_ID)
        state_session_id = gr.State(value="")
        state_thread_id = gr.State(value="")

        with gr.Row():
            # ===== 左侧边栏：系统控制 =====
            with gr.Column(scale=1):
                gr.Markdown("## 📋 系统控制")
                user_id_display = gr.Textbox(
                    label="User ID",
                    value=DEFAULT_USER_ID,
                    interactive=False,
                )
                session_id_display = gr.Textbox(
                    label="Session ID",
                    value="",
                    interactive=False,
                )
                thread_id_display = gr.Textbox(
                    label="Thread ID",
                    value="",
                    interactive=False,
                )
                new_chat_btn = gr.Button("🆕 新建对话", variant="secondary")
                gr.Markdown("---")
                gr.Markdown("## 📁 文档上传")
                file_input = gr.File(
                    label="选择文件（PDF/TXT/MD/DOCX/PPTX/图片）",
                    file_count="single",
                    file_types=[".pdf", ".txt", ".md", ".docx", ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"],
                )
                upload_btn = gr.Button("📤 上传", variant="primary")
                upload_status = gr.Textbox(label="上传状态", interactive=False, lines=3)

            # ===== 中间主区域：聊天界面 =====
            with gr.Column(scale=3):
                gr.Markdown("## 💬 对话")
                # Python 3.14 兼容：移除 type 参数
                chatbot = gr.Chatbot(
                    label="聊天记录",
                    height=500,
                )
                with gr.Row():
                    user_input_box = gr.Textbox(
                        label="",
                        placeholder="输入内容，如「我想推广一个新款降噪耳机…」或 /new_chat",
                        lines=3,
                        scale=9,
                    )
                    send_btn = gr.Button("📨 发送", variant="primary", scale=1)

            # ===== 右侧边栏：深度思考过程 =====
            with gr.Column(scale=2):
                gr.Markdown("## 🧠 深度思考")
                thinking_display = gr.JSON(label="Thinking Process", value={})

        # ===== 初始化：应用启动时创建会话 =====
        demo.load(
            fn=init_session,
            inputs=[state_user_id],
            outputs=[state_user_id, state_session_id, state_thread_id],
        ).then(
            fn=lambda uid, sid, tid: (uid, sid, tid),
            inputs=[state_user_id, state_session_id, state_thread_id],
            outputs=[user_id_display, session_id_display, thread_id_display],
        )

        # ===== 事件绑定 =====

        # 发送消息（点击发送或回车）
        def on_send(msg, hist, uid, sid, tid):
            new_hist, new_sid, think = send_message(msg, hist, uid, sid, tid)
            return new_hist, "", new_sid, think

        send_btn.click(
            fn=on_send,
            inputs=[user_input_box, chatbot, state_user_id, state_session_id, state_thread_id],
            outputs=[chatbot, user_input_box, state_session_id, thinking_display],
        ).then(
            fn=lambda sid: sid,
            inputs=[state_session_id],
            outputs=[session_id_display],
        )
        user_input_box.submit(
            fn=on_send,
            inputs=[user_input_box, chatbot, state_user_id, state_session_id, state_thread_id],
            outputs=[chatbot, user_input_box, state_session_id, thinking_display],
        ).then(
            fn=lambda sid: sid,
            inputs=[state_session_id],
            outputs=[session_id_display],
        )

        # 上传文件
        upload_btn.click(
            fn=upload_file,
            inputs=[file_input, state_user_id, state_session_id],
            outputs=[upload_status],
        )

        # 新建对话
        def on_new_chat(uid):
            hist, sid, tid, think = new_chat(uid)
            return hist, sid, tid, sid, tid, think

        new_chat_btn.click(
            fn=on_new_chat,
            inputs=[state_user_id],
            outputs=[
                chatbot,
                state_session_id,
                state_thread_id,
                session_id_display,
                thread_id_display,
                thinking_display,
            ],
        )

    return demo


if __name__ == "__main__":
    print(f"🚀 启动 Gradio 前端，后端地址: {BACKEND_URL}")
    print("若后端未启动，请先运行: uvicorn main:app --reload")
    app = build_ui()
    app.launch(server_name="0.0.0.0", server_port=7860, share=False)
