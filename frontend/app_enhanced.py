"""
AI 营销助手 Gradio 前端（增强版）：验证服务与模型效果。
目标：验证服务是否正常、模型返回是否与预期相符。
启动：python frontend/app_enhanced.py
环境变量：BACKEND_URL（默认 http://localhost:8000）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
import requests

try:
    from frontend.config import (
        ALLOWED_FILE_TYPES,
        BACKEND_URL,
        MAX_CONTENT_LENGTH_PER_MSG,
        MAX_HISTORY_ITEMS,
        MAX_INPUT_LENGTH,
        TIMEOUT_CHAT,
        TIMEOUT_DEEP,
        TIMEOUT_INIT,
        TIMEOUT_UPLOAD,
    )
except ImportError:
    from config import (
        ALLOWED_FILE_TYPES,
        BACKEND_URL,
        MAX_CONTENT_LENGTH_PER_MSG,
        MAX_HISTORY_ITEMS,
        MAX_INPUT_LENGTH,
        TIMEOUT_CHAT,
        TIMEOUT_DEEP,
        TIMEOUT_INIT,
        TIMEOUT_UPLOAD,
    )

ChatHistory = List[Dict[str, str]]

_DEFAULT_THINKING: Dict[str, Any] = {
    "mode": "-",
    "intent": "等待输入",
    "session_id": "-",
    "thread_id": "-",
    "思考过程": "",
}


def _request(
    method: str,
    endpoint: str,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
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
        if r.status_code == 440:
            return False, r.json() if r.content else {}, "SESSION_EXPIRED"
        r.raise_for_status()
        return True, r.json(), None
    except requests.exceptions.Timeout:
        return False, None, "请求超时"
    except requests.exceptions.ConnectionError:
        return False, None, f"无法连接后端 ({BACKEND_URL})"
    except requests.exceptions.HTTPError as e:
        try:
            msg = e.response.json().get("error", str(e))
        except Exception:
            msg = str(e)
        return False, None, f"HTTP {e.response.status_code}: {msg}"
    except Exception as e:
        return False, None, str(e)


def init_session() -> Tuple[str, str, str]:
    success, resp, err = _request("GET", "/api/v1/frontend/session/init", timeout=TIMEOUT_INIT)
    if not success or not resp:
        gr.Warning(f"会话初始化失败: {err}")
        return "", "", ""
    return resp.get("user_id", ""), resp.get("session_id", ""), resp.get("thread_id", "")


def send_message(
    user_input: str,
    history: ChatHistory,
    user_id: str,
    session_id: str,
    thread_id: str,
) -> Tuple[ChatHistory, str, str, str, Dict[str, Any]]:
    """返回 (history, user_id, session_id, thread_id, think_out)，系统按意图自动路由"""
    s = user_input.strip()
    if not s:
        gr.Warning("输入不能为空")
        return history, user_id or "", session_id or "", thread_id or "", dict(_DEFAULT_THINKING)
    if len(s) > MAX_INPUT_LENGTH:
        gr.Warning(f"输入过长（限{MAX_INPUT_LENGTH}字）")
        return history, user_id or "", session_id or "", thread_id or "", dict(_DEFAULT_THINKING)

    if not session_id or not str(session_id).strip():
        user_id, session_id, thread_id = init_session()
        if not session_id:
            t = dict(_DEFAULT_THINKING)
            t["error"] = "会话初始化失败"
            history = list(history or [])
            history.append({"role": "user", "content": s})
            history.append({"role": "assistant", "content": "⚠️ 会话初始化失败，请检查后端是否已启动 (uvicorn main:app --reload)。"})
            return history, user_id or "", "", thread_id or "", t

    history_for_api = []
    for msg in (history or [])[-MAX_HISTORY_ITEMS:]:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            history_for_api.append({
                "role": msg["role"],
                "content": str(msg["content"])[:MAX_CONTENT_LENGTH_PER_MSG],
            })

    payload = {
        "message": s,
        "session_id": session_id,
        "user_id": user_id,
        "tags": [],
    }
    if history_for_api:
        payload["history"] = history_for_api

    success, resp, err = _request("POST", "/api/v1/frontend/chat", json=payload, timeout=TIMEOUT_DEEP)

    if err == "SESSION_EXPIRED":
        user_id, session_id, thread_id = init_session()
        if not session_id:
            t = dict(_DEFAULT_THINKING)
            t["error"] = "会话过期"
            history = list(history or [])
            history.append({"role": "user", "content": s})
            history.append({"role": "assistant", "content": "⚠️ 会话已过期，重新初始化失败。请点击「新建对话」重试。"})
            return history, user_id or "", "", thread_id or "", t
        payload["session_id"] = session_id
        payload["user_id"] = user_id
        success, resp, err = _request("POST", "/api/v1/frontend/chat", json=payload, timeout=TIMEOUT_DEEP)

    if not success or not resp:
        gr.Warning(f"请求失败: {err}")
        t = dict(_DEFAULT_THINKING)
        t["error"] = str(err)
        history = list(history or [])
        history.append({"role": "user", "content": s})
        history.append({"role": "assistant", "content": f"⚠️ 请求失败：{err}\n\n请检查后端是否正常运行，或查看右侧「思考过程」了解详情。"})
        return history, user_id or "", session_id or "", thread_id or "", t

    thinking = resp.get("thinking_process", [])
    new_sid = resp.get("session_id", session_id)

    history = list(history or [])
    history.append({"role": "user", "content": s})
    history.append({"role": "assistant", "content": resp.get("response", "暂无回复")})

    route_mode = resp.get("mode", "unknown")
    think_out = {
        "mode": route_mode,
        "intent": resp.get("intent", "unknown"),
        "session_id": new_sid,
        "thread_id": thread_id,
        "思考过程": thinking if route_mode == "creation" else "（闲聊无思考过程）",
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return history, user_id or "", new_sid, thread_id or "", think_out


def list_session_docs(session_id: str) -> Tuple[bool, List[str]]:
    """按 session_id 列出当前会话已绑定文档。返回 (success, [filename, ...])"""
    if not session_id or not str(session_id).strip():
        return False, []
    ok, resp, _ = _request("GET", "/api/v1/documents", json={"session_id": session_id.strip()}, timeout=10)
    if not ok or not resp or not resp.get("success"):
        return False, []
    data = resp.get("data") or []
    names = [d.get("original_filename", d.get("filename", "")) for d in data if isinstance(d, dict)]
    return True, names


def _format_docs_display(session_id: str, doc_names: List[str]) -> str:
    """格式化「当前会话文档」展示，用于验证文档是否跟随当前会话"""
    sid_short = (session_id or "-")[:12] + "..." if (session_id or "") and len(session_id or "") > 12 else (session_id or "-")
    if not doc_names:
        return f"**当前会话文档**\n\n绑定会话: `{sid_short}`\n\n*（无）上传后即绑定到当前会话*"
    lst = "\n".join(f"- {n}" for n in doc_names)
    return f"**当前会话文档**\n\n绑定会话: `{sid_short}`\n\n{lst}"


def fetch_docs_display(session_id: str) -> str:
    """拉取当前会话文档列表并格式化为展示文本"""
    _, names = list_session_docs(session_id or "")
    return _format_docs_display(session_id or "", names)


def upload_file(file, user_id: str, session_id: str) -> Tuple[str, str]:
    """上传文件并返回 (上传状态, 当前会话文档展示)"""
    import os
    empty_docs = _format_docs_display(session_id or "", [])
    if file is None:
        return "未选择文件", empty_docs
    if not session_id or not str(session_id).strip():
        gr.Warning("请先发送一条消息或点击「新建对话」以初始化会话")
        return "请先初始化会话", "**当前会话文档**\n\n*请先初始化会话*"
    ext = os.path.splitext(getattr(file, "name", "") or "")[1].lower()
    if ext and ext not in ALLOWED_FILE_TYPES:
        return f"不支持{ext}", empty_docs
    try:
        with open(file.name, "rb") as f:
            files = {"file": (os.path.basename(file.name), f, "application/octet-stream")}
            data = {"user_id": user_id, "session_id": session_id.strip()}
            ok, resp, err = _request("POST", "/api/v1/documents/upload", data=data, files=files, timeout=TIMEOUT_UPLOAD)
        if not ok or not resp:
            gr.Warning(f"上传失败: {err}")
            return f"失败: {err}", empty_docs
        fn = resp.get("data", {}).get("original_filename", "")
        gr.Info(f"已上传: {fn}（已绑定到当前会话）")
        _, names = list_session_docs(session_id.strip())
        return f"已上传: {fn}", _format_docs_display(session_id.strip(), names)
    except Exception as e:
        gr.Warning(str(e))
        return str(e), empty_docs


def new_chat() -> Tuple[ChatHistory, str, str, str, Dict[str, Any]]:
    user_id, session_id, thread_id = init_session()
    if not session_id:
        gr.Warning("新建对话失败")
        return [], "", "", "", dict(_DEFAULT_THINKING)
    gr.Info("已新建对话")
    t = dict(_DEFAULT_THINKING)
    t["session_id"] = session_id
    t["thread_id"] = thread_id
    t["create_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return [], user_id, session_id, thread_id, t


def _format_thinking(d: Dict[str, Any]) -> str:
    """将思考过程格式化为可读文本，供 Markdown 展示"""
    if not d:
        return "（暂无）"
    lines = []
    for k, v in d.items():
        if k == "思考过程" and isinstance(v, list):
            for i, step in enumerate(v, 1):
                if isinstance(step, dict):
                    lines.append(f"**步骤{i}** {step.get('step','')}: {step.get('thought','')}")
                else:
                    lines.append(f"- {step}")
        elif v:
            lines.append(f"**{k}**: {v}")
    return "\n".join(lines) if lines else "（暂无）"


def build_ui():
    demo = gr.Blocks(title="AI 营销助手 - 验证端")

    with demo:
        state_uid = gr.State("")
        state_sid = gr.State("")
        state_tid = gr.State("")

        with gr.Row():
            # ========== 左侧：会话与验证信息 ==========
            with gr.Column(scale=1):
                gr.Markdown("**会话控制**")
                new_chat_btn = gr.Button("新建对话", variant="primary")
                gr.Markdown("*若下方 ID 为空，请点击新建对话*")

                gr.Markdown("---")
                gr.Markdown("**验证信息**")
                uid_tb = gr.Textbox(label="User ID", value="", interactive=False)
                sid_tb = gr.Textbox(label="Session ID（对话ID）", value="", interactive=False)
                tid_tb = gr.Textbox(label="Thread ID", value="", interactive=False)

                gr.Markdown("---")
                gr.Markdown("**文档**")
                file_input = gr.File(label="添加", file_count="single", file_types=ALLOWED_FILE_TYPES)
                upload_out = gr.Textbox(label="", interactive=False, lines=1)
                docs_display = gr.Markdown(value="**当前会话文档**\n\n*（无）*", label="")

            # ========== 中间：对话 ==========
            with gr.Column(scale=2):
                gr.Markdown("**对话**")
                chatbot = gr.Chatbot(height=380)
                user_input = gr.Textbox(
                    label="",
                    placeholder="输入内容（闲聊或营销创作需求）；可粘贴链接；支持 PDF/PPT/MD/图片；系统自动识别意图",
                    lines=2,
                )
                send_btn = gr.Button("发送", variant="primary")

            # ========== 右侧：策略脑执行过程 ==========
            with gr.Column(scale=2):
                gr.Markdown("**策略脑执行过程**")
                thinking_md = gr.Markdown(value="（等待输入）")
                thinking_json = gr.JSON(value=dict(_DEFAULT_THINKING), label="原始 JSON", visible=True)

        # ---------- 初始化：单次返回所有值，避免 .then() 链导致显示不同步 ----------
        def _init():
            try:
                uid, sid, tid = init_session()
                t = dict(_DEFAULT_THINKING)
                t["session_id"] = sid or "-"
                t["thread_id"] = tid or "-"
                docs_md = fetch_docs_display(sid or "")
                return uid or "", sid or "", tid or "", t, "（等待输入）", uid or "", sid or "", tid or "", docs_md
            except Exception as e:
                t = dict(_DEFAULT_THINKING)
                t["error"] = str(e)
                return "", "", "", t, "（初始化异常）", "", "", "", "**当前会话文档**\n\n*（初始化异常）*"

        demo.load(
            fn=_init,
            inputs=[],
            outputs=[
                state_uid,
                state_sid,
                state_tid,
                thinking_json,
                thinking_md,
                uid_tb,
                sid_tb,
                tid_tb,
                docs_display,
            ],
            queue=False,
        )

        # ---------- 发送 ----------
        def _send(msg, hist, uid, sid, tid):
            new_hist, new_uid, new_sid, new_tid, think = send_message(msg, hist, uid or "", sid or "", tid or "")
            md = _format_thinking(think)
            docs_md = fetch_docs_display(new_sid or "")
            return new_hist, "", new_uid, new_sid, new_tid, think, md, new_uid, new_sid, new_tid, docs_md

        for evt in [send_btn.click, user_input.submit]:
            evt(
                fn=_send,
                inputs=[user_input, chatbot, state_uid, state_sid, state_tid],
                outputs=[
                    chatbot,
                    user_input,
                    state_uid,
                    state_sid,
                    state_tid,
                    thinking_json,
                    thinking_md,
                    uid_tb,
                    sid_tb,
                    tid_tb,
                    docs_display,
                ],
            )

        # ---------- 上传 ----------
        file_input.change(
            fn=upload_file,
            inputs=[file_input, state_uid, state_sid],
            outputs=[upload_out, docs_display],
        )

        # ---------- 新建对话 ----------
        def _new():
            try:
                hist, uid, sid, tid, think = new_chat()
                md = _format_thinking(think)
                docs_md = fetch_docs_display(sid or "")
                return (
                    hist or [],
                    uid or "",
                    sid or "",
                    tid or "",
                    think,
                    md,
                    uid or "",
                    sid or "",
                    tid or "",
                    docs_md,
                )
            except Exception as e:
                t = dict(_DEFAULT_THINKING)
                t["error"] = str(e)
                return [], "", "", "", t, f"（异常: {e}）", "", "", "", "**当前会话文档**\n\n*（异常）*"

        new_chat_btn.click(
            fn=_new,
            inputs=[],
            outputs=[
                chatbot,
                state_uid,
                state_sid,
                state_tid,
                thinking_json,
                thinking_md,
                uid_tb,
                sid_tb,
                tid_tb,
                docs_display,
            ],
        )

    return demo


def _check_backend() -> bool:
    """启动前检查后端是否可达"""
    try:
        r = requests.get(f"{BACKEND_URL}/api/v1/frontend/session/init", timeout=5)
        if r.status_code == 200 and r.json().get("success"):
            return True
        print(f"[警告] 后端返回异常: {r.status_code} {r.text[:200]}")
    except requests.exceptions.ConnectionError:
        print(f"[错误] 无法连接后端 {BACKEND_URL}，请确保已启动: uvicorn main:app --reload")
    except Exception as e:
        print(f"[错误] 后端检查失败: {e}")
    return False


if __name__ == "__main__":
    print("=" * 50)
    print("AI 营销助手 - 验证端")
    print(f"后端: {BACKEND_URL}")
    if _check_backend():
        print("[OK] 后端连接正常")
    else:
        print("[!!] 后端不可达，请先启动后端后刷新页面")
    print("=" * 50)
    app = build_ui()
    # 不使用 queue，减少 ERR_CONNECTION_RESET / share-modal 导致的崩溃
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        footer_links=[],
    )
