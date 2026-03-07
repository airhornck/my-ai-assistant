"""
AI 营销助手 Gradio 前端（增强版）：验证服务与模型效果。
目标：验证服务是否正常、模型返回是否与预期相符。
启动：python frontend/app_enhanced.py
环境变量：BACKEND_URL（默认 http://localhost:8000）
"""
from __future__ import annotations

import os
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
        elif method.upper() == "DELETE":
            r = requests.delete(url, params=json or {}, timeout=timeout)
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


def _normalize_backend_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """统一后端返回：闲聊用 response/thinking_process，创作 SSE 用 content/thinking_logs。"""
    out = dict(data)
    if "response" in out and "content" not in out:
        out["content"] = out.get("response", "")
    if "thinking_process" in out and "thinking_logs" not in out:
        out["thinking_logs"] = out.get("thinking_process", [])
    return out


def _request_stream_and_collect(
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """流式请求：POST ?stream=true。若后端返回 JSON（如闲聊）则解析并规范化；若返回 SSE 则消费并取最后一条 state。"""
    import json as _json
    url = f"{BACKEND_URL}/api/v1/frontend/chat?stream=true"
    try:
        r = requests.post(url, json=payload, stream=True, timeout=TIMEOUT_DEEP)
        r.raise_for_status()
    except Exception as e:
        return False, None, str(e)

    ct = (r.headers.get("Content-Type") or "").lower()
    if "application/json" in ct:
        try:
            raw = r.content.decode("utf-8", errors="replace")
            data = _json.loads(raw)
        except Exception as e:
            return False, None, str(e)
        if isinstance(data, dict) and data.get("error"):
            return False, data, data.get("error", "请求失败")
        if isinstance(data, dict):
            return True, _normalize_backend_data(data), None
        return False, None, "响应格式异常"

    last_data: Optional[Dict[str, Any]] = None
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            data = _json.loads(line[6:].strip())
        except Exception:
            continue
        if isinstance(data, dict) and data.get("error"):
            return False, {"error": data.get("error", "")}, data.get("error", "")
        last_data = data
    if last_data is None:
        return False, None, "流式响应无有效数据"
    return True, _normalize_backend_data(last_data), None


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


def send_message_with_stream_option(
    user_input: str,
    history: ChatHistory,
    user_id: str,
    session_id: str,
    thread_id: str,
    use_stream: bool,
) -> Tuple[ChatHistory, str, str, str, Dict[str, Any]]:
    """统一入口：use_stream=True 时走流式请求并收集最后 state 单次返回；否则走普通 POST。单次返回，不使用 generator，避免 queue 触发 share-modal 等问题。"""
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
            hist = list(history or [])
            hist.append({"role": "user", "content": s})
            hist.append({"role": "assistant", "content": "⚠️ 会话初始化失败，请检查后端是否已启动 (uvicorn main:app --reload)。"})
            return hist, user_id or "", "", thread_id or "", t

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

    if use_stream:
        success, data, err = _request_stream_and_collect(payload)
        if not success:
            t = dict(_DEFAULT_THINKING)
            t["error"] = err or (data.get("error") if isinstance(data, dict) else "流式请求失败")
            hist = list(history or [])
            hist.append({"role": "user", "content": s})
            hist.append({"role": "assistant", "content": f"⚠️ {t['error']}"})
            return hist, user_id or "", session_id or "", thread_id or "", t
        thinking_logs = data.get("thinking_logs") or []
        content = (data.get("content") or "").strip()
        new_sid = data.get("session_id") or session_id
        hist = list(history or [])
        hist.append({"role": "user", "content": s})
        hist.append({"role": "assistant", "content": content or "暂无回复"})
        think_out = {
            "mode": data.get("mode", "creation"),
            "intent": data.get("intent", "unknown"),
            "session_id": new_sid,
            "thread_id": thread_id or "",
            "思考过程": thinking_logs,
            "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return hist, user_id or "", new_sid, thread_id or "", think_out
    return send_message(s, history, user_id, session_id, thread_id)


def _stream_send_generator(
    user_input: str,
    history: ChatHistory,
    user_id: str,
    session_id: str,
    thread_id: str,
):
    """流式请求：POST ?stream=true，遇 JSON（如闲聊）yield 一次；遇 SSE 每收到一条 state 即 yield 一次，实现界面逐步更新。"""
    import json as _json
    s = (user_input or "").strip()
    uid = user_id or ""
    sid = session_id or ""
    tid = thread_id or ""
    base_hist = list(history or [])
    base_hist.append({"role": "user", "content": s})

    if not sid or not str(sid).strip():
        uid, sid, tid = init_session()
        if not sid:
            t = dict(_DEFAULT_THINKING)
            t["error"] = "会话初始化失败"
            yield base_hist + [{"role": "assistant", "content": "⚠️ 会话初始化失败"}], "", uid, sid, tid, t, _format_thinking(t), uid, sid, tid, fetch_docs_display(sid)
            return

    history_for_api = []
    for msg in (history or [])[-MAX_HISTORY_ITEMS:]:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            history_for_api.append({
                "role": msg["role"],
                "content": str(msg["content"])[:MAX_CONTENT_LENGTH_PER_MSG],
            })
    payload = {
        "message": s,
        "session_id": sid,
        "user_id": uid,
        "tags": [],
    }
    if history_for_api:
        payload["history"] = history_for_api

    url = f"{BACKEND_URL}/api/v1/frontend/chat?stream=true"
    try:
        r = requests.post(url, json=payload, stream=True, timeout=TIMEOUT_DEEP)
        r.raise_for_status()
    except Exception as e:
        t = dict(_DEFAULT_THINKING)
        t["error"] = str(e)
        yield base_hist + [{"role": "assistant", "content": f"⚠️ {e}"}], "", uid, sid, tid, t, _format_thinking(t), uid, sid, tid, fetch_docs_display(sid)
        return

    ct = (r.headers.get("Content-Type") or "").lower()
    if "application/json" in ct:
        try:
            raw = r.content.decode("utf-8", errors="replace")
            data = _json.loads(raw)
        except Exception as e:
            t = dict(_DEFAULT_THINKING)
            t["error"] = str(e)
            yield base_hist + [{"role": "assistant", "content": f"⚠️ 解析失败"}], "", uid, sid, tid, t, _format_thinking(t), uid, sid, tid, fetch_docs_display(sid)
            return
        data = _normalize_backend_data(data) if isinstance(data, dict) else {}
        content = (data.get("content") or "").strip()
        new_sid = data.get("session_id") or sid
        think = {
            "mode": data.get("mode", "creation"),
            "intent": data.get("intent", "unknown"),
            "session_id": new_sid,
            "thread_id": tid,
            "思考过程": data.get("thinking_logs") or data.get("thinking_process") or [],
            "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        hist = base_hist + [{"role": "assistant", "content": content or "暂无回复"}]
        yield hist, "", uid, new_sid, tid, think, _format_thinking(think), uid, new_sid, tid, fetch_docs_display(new_sid)
        return

    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            chunk = _json.loads(line[6:].strip())
        except Exception:
            continue
        if not isinstance(chunk, dict):
            continue
        if chunk.get("error"):
            t = dict(_DEFAULT_THINKING)
            t["error"] = chunk.get("error", "")
            yield base_hist + [{"role": "assistant", "content": f"⚠️ {t['error']}"}], "", uid, sid, tid, t, _format_thinking(t), uid, sid, tid, fetch_docs_display(sid)
            return
        chunk = _normalize_backend_data(chunk)
        content = (chunk.get("content") or "").strip()
        new_sid = chunk.get("session_id") or sid
        logs = chunk.get("thinking_logs") or []
        think = {
            "mode": chunk.get("mode", "creation"),
            "intent": chunk.get("intent", "unknown"),
            "session_id": new_sid,
            "thread_id": tid,
            "思考过程": logs,
            "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        # 无正文时仅显示占位，避免思考过程与最终回复混在同一气泡；详细步骤在右侧「策略脑执行过程」展示
        if not content:
            content = "（生成中，请查看右侧「策略脑执行过程」）"
        hist = base_hist + [{"role": "assistant", "content": content}]
        yield hist, "", uid, new_sid, tid, think, _format_thinking(think), uid, new_sid, tid, fetch_docs_display(new_sid)


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
    """格式化「当前会话文档」展示，用于验证文档是否跟随当前会话。每会话最多 5 个。"""
    sid_short = (session_id or "-")[:12] + "..." if (session_id or "") and len(session_id or "") > 12 else (session_id or "-")
    if not doc_names:
        return f"**当前会话文档**（最多 5 个）\n\n绑定会话: `{sid_short}`\n\n*（无）上传后即绑定到当前会话*"
    lst = "\n".join(f"- {n}" for n in doc_names)
    return f"**当前会话文档**（{len(doc_names)}/5）\n\n绑定会话: `{sid_short}`\n\n{lst}"


def fetch_docs_display(session_id: str) -> str:
    """拉取当前会话文档列表并格式化为展示文本"""
    _, names = list_session_docs(session_id or "")
    return _format_docs_display(session_id or "", names)


def fetch_memory_list(user_id: str) -> Tuple[str, List[Tuple[str, str]], int]:
    """
    拉取该用户的记忆列表（GET /api/v1/memory）。
    返回 (Markdown 摘要, choices for Dropdown [(value_id, label_preview), ...], recent_interaction_count)。
    """
    empty_md = "**记忆**\n\n请先发送一条消息或点击「新建对话」，获得 User ID 后再点击「加载记忆」。"
    uid = (user_id or "").strip()
    if not uid:
        return empty_md, [], 0
    ok, resp, err = _request("GET", "/api/v1/memory", json={"user_id": uid}, timeout=15)
    if not ok or not resp:
        return f"**记忆**\n\n加载失败：{err or '未知错误'}。", [], 0
    profile = resp.get("profile_summary") or {}
    items = resp.get("memory_items") or []
    recent_count = resp.get("recent_interaction_count", 0)
    parts = ["**记忆**"]
    if profile:
        ps = []
        if profile.get("brand_name"):
            ps.append(f"品牌：{profile['brand_name']}")
        if profile.get("industry"):
            ps.append(f"行业：{profile['industry']}")
        if profile.get("preferred_style"):
            ps.append(f"风格：{profile['preferred_style']}")
        if profile.get("tags"):
            ps.append("标签：" + "、".join(profile["tags"][:8]))
        if ps:
            parts.append("画像：" + "；".join(ps))
    parts.append(f"记忆条 **{len(items)}** 条，近期交互 **{recent_count}** 条。")
    md = "\n\n".join(parts)
    choices: List[Tuple[str, str]] = []
    for m in items:
        mid = str(m.get("id", ""))
        preview = (m.get("content_preview") or "")[:60] + ("…" if len(m.get("content_preview") or "") > 60 else "")
        source = m.get("source") or ""
        date = (m.get("created_at") or "")[:10]
        label = f"[{date}] {source}：{preview}"
        choices.append((mid, label))
    return md, choices, recent_count


def fetch_memory_content(user_id: str, memory_id: str) -> str:
    """拉取单条记忆完整内容（GET /api/v1/memory/{id}）。"""
    uid = (user_id or "").strip()
    if not uid or not (memory_id or "").strip():
        return "（请先加载记忆并选择一条）"
    ok, resp, err = _request("GET", f"/api/v1/memory/{memory_id.strip()}", json={"user_id": uid}, timeout=10)
    if not ok or not resp:
        return f"加载失败：{err or '未知错误'}"
    return resp.get("content", "（无内容）")


def clear_memory_api(user_id: str) -> Tuple[bool, str]:
    """清空该用户所有记忆条（DELETE /api/v1/memory）。"""
    uid = (user_id or "").strip()
    if not uid:
        return False, "User ID 为空"
    ok, resp, err = _request("DELETE", "/api/v1/memory", json={"user_id": uid}, timeout=10)
    if not ok:
        return False, err or "清空失败"
    return True, "已清空所有记忆条"


def delete_memory_item_api(user_id: str, memory_id: str) -> Tuple[bool, str]:
    """删除单条记忆（DELETE /api/v1/memory/{id}）。"""
    uid = (user_id or "").strip()
    if not uid or not (memory_id or "").strip():
        return False, "请选择要删除的记忆条"
    ok, resp, err = _request("DELETE", f"/api/v1/memory/{memory_id.strip()}", json={"user_id": uid}, timeout=10)
    if not ok:
        return False, err or "删除失败"
    return True, "已删除该条记忆"


def _normalize_report_type(raw: str) -> str:
    """后端只接受英文 key；若前端传来中文标签则映射回 key。"""
    if not raw or not str(raw).strip():
        return ""
    raw = str(raw).strip()
    # 后端合法 key
    keys = ["bilibili_hotspot", "douyin_hotspot", "xiaohongshu_hotspot", "acfun_hotspot", "case_library", "methodology"]
    if raw in keys:
        return raw
    # 中文标签 -> key
    label_to_key = {"B站热点": "bilibili_hotspot", "抖音热点": "douyin_hotspot", "小红书热点": "xiaohongshu_hotspot",
                    "AcFun热点": "acfun_hotspot", "案例库": "case_library", "方法论": "methodology"}
    return label_to_key.get(raw, raw)


def fetch_cache_report(report_type: str) -> Tuple[str, str]:
    """拉取插件缓存报告内容。返回 (报告正文或错误信息, 用于显示的标题/状态)。"""
    if not report_type or not str(report_type).strip():
        return "", "请选择报告类型后点击「加载」"
    key = _normalize_report_type(report_type)
    if not key:
        return "", "请选择报告类型后点击「加载」"
    ok, resp, err = _request(
        "GET", "/api/v1/debug/cache-reports", json={"report_type": key}, timeout=15
    )
    if not ok:
        return "", f"加载失败：{err or '未知错误'}"
    if not resp.get("success"):
        return "", resp.get("error", "未知错误")
    report = resp.get("report")
    if report is None:
        return "（缓存为空或已过期）", f"报告类型: {report_type} — 无内容"
    title = f"报告类型: {key} | 长度: {resp.get('length', 0)} 字符"
    return (report if isinstance(report, str) else str(report)), title


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


def _request_new_chat(user_id: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """调用 /api/v1/chat/new 新建对话，保持 user_id 不变，仅新建 session_id 与 thread_id。"""
    if not user_id or not str(user_id).strip():
        return False, None, None, None, "user_id 为空，请先初始化"
    ok, resp, err = _request("POST", "/api/v1/chat/new", json={"user_id": user_id.strip()}, timeout=TIMEOUT_INIT)
    if not ok or not resp or not resp.get("success"):
        return False, None, None, None, err or "新建对话失败"
    return True, user_id.strip(), resp.get("session_id"), resp.get("thread_id"), None


def new_chat(current_user_id: str = "") -> Tuple[ChatHistory, str, str, str, Dict[str, Any]]:
    """新建对话：保持 user_id 不变，仅新建 session_id（对话 ID）。若无 user_id 则先初始化。"""
    user_id = (current_user_id or "").strip()
    if not user_id:
        user_id, session_id, thread_id = init_session()
        if not session_id:
            gr.Warning("新建对话失败（首次需初始化）")
            return [], "", "", "", dict(_DEFAULT_THINKING)
    else:
        ok, uid, sid, tid, err = _request_new_chat(user_id)
        if not ok:
            gr.Warning(err or "新建对话失败")
            return [], user_id, "", "", dict(_DEFAULT_THINKING)
        session_id, thread_id = sid or "", tid or ""
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


CUSTOM_CSS = """
.contain { max-width: 1600px; margin: 0 auto; padding: 10px; }
.gr-panel { border-radius: 10px; padding: 12px; margin: 6px 0; background: var(--block-background-fill); border: 1px solid var(--block-border-color); }
.section-title { font-size: 0.9rem; font-weight: 600; margin-bottom: 6px; }
.chat-wrap .message { border-radius: 10px; }
.debug-table-wrap { overflow-x: auto; min-height: 120px; }
.db-snapshot-wrap { min-height: 200px; }
"""


# 插件报告类型与中文标签（便于调试页展示）
CACHE_REPORT_CHOICES = [
    ("bilibili_hotspot", "B站热点"),
    ("douyin_hotspot", "抖音热点"),
    ("xiaohongshu_hotspot", "小红书热点"),
    ("acfun_hotspot", "AcFun热点"),
    ("case_library", "案例库"),
    ("methodology", "方法论"),
]


def build_ui():
    demo = gr.Blocks(title="AI 营销助手")

    with demo:
        state_uid = gr.State("")
        state_sid = gr.State("")
        state_tid = gr.State("")

        gr.Markdown("# AI 营销助手", elem_classes=["contain"])

        with gr.Tabs():
            # ==================== Tab 1: 对话 ====================
            with gr.TabItem("对话", id=0):
                with gr.Column(elem_classes=["contain"]):
                    # 第一行：会话信息 + 新建对话
                    with gr.Row():
                        new_chat_btn = gr.Button("新建对话", variant="primary", size="sm")
                        uid_tb = gr.Textbox(label="User ID", value="", interactive=False, show_label=True, scale=2)
                        sid_tb = gr.Textbox(label="Session ID", value="", interactive=False, show_label=True, scale=2)
                        tid_tb = gr.Textbox(label="Thread ID", value="", interactive=False, show_label=True, scale=1)

                    # 第二行：对话区 + 策略脑
                    with gr.Row():
                        with gr.Column(scale=3):
                            chatbot = gr.Chatbot(height=380, elem_classes=["chat-wrap"], label="对话", show_label=True)
                        with gr.Column(scale=2):
                            gr.Markdown("### 策略脑执行过程", elem_classes=["section-title"])
                            thinking_md = gr.Markdown(value="（等待输入）", elem_classes=["gr-panel"])
                            thinking_json = gr.JSON(value=dict(_DEFAULT_THINKING), label="原始 JSON", show_label=True)

                    # 第三行：输入 + 发送
                    with gr.Row():
                        user_input = gr.Textbox(
                            placeholder="输入内容（闲聊或营销创作）；支持链接、PDF/图片",
                            lines=2,
                            show_label=False,
                            scale=4,
                        )
                        stream_check = gr.Checkbox(value=True, label="流式", show_label=True)
                        send_btn = gr.Button("发送", variant="primary")

                    # 第四行：可折叠 — 文档与数据库快照
                    with gr.Accordion("文档与数据库快照（点击展开）", open=False):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown("**文档**", elem_classes=["section-title"])
                                file_input = gr.File(file_count="single", file_types=ALLOWED_FILE_TYPES, show_label=False)
                                upload_out = gr.Textbox(interactive=False, lines=1, show_label=False)
                                docs_display = gr.Markdown(value="*（无）*", elem_classes=["gr-panel"])
                            with gr.Column(scale=2):
                                gr.Markdown("**记忆** — 当前 User 的记忆条（品牌/事实/成功案例等）", elem_classes=["section-title"])
                                with gr.Row():
                                    load_memory_btn = gr.Button("加载记忆", variant="primary", size="sm")
                                    clear_memory_btn = gr.Button("清空记忆", variant="secondary", size="sm")
                                memory_summary_md = gr.Markdown(value="点击「加载记忆」查看当前用户的记忆列表与画像。", elem_classes=["gr-panel"])
                                memory_dropdown = gr.Dropdown(
                                    choices=[],
                                    value=None,
                                    label="选择一条记忆查看详情",
                                    interactive=True,
                                    allow_custom_value=False,
                                )
                                memory_content_tb = gr.Textbox(
                                    value="",
                                    label="记忆内容（只读）",
                                    lines=6,
                                    interactive=False,
                                    max_lines=15,
                                )
                                delete_memory_btn = gr.Button("删除当前选中记忆", variant="secondary", size="sm")

            # ==================== Tab 2: 调试 — 数据库与缓存 ====================
            with gr.TabItem("调试：数据库与缓存", id=1):
                with gr.Column(elem_classes=["contain"]):
                    gr.Markdown("---")
                    gr.Markdown("### 1. 记忆（GET /api/v1/memory）", elem_classes=["section-title"])
                    with gr.Row():
                        debug_uid = gr.Textbox(
                            label="User ID",
                            placeholder="输入 user_id 或点击「填入当前会话 User ID」",
                            value="",
                            scale=3,
                        )
                        copy_uid_btn = gr.Button("填入当前会话 User ID", variant="secondary", size="sm")
                        load_memory_debug_btn = gr.Button("加载记忆", variant="primary", size="sm")
                        clear_memory_debug_btn = gr.Button("清空记忆", variant="secondary", size="sm")
                    memory_debug_summary_md = gr.Markdown(value="填写 User ID 后点击「加载记忆」。", elem_classes=["gr-panel"])
                    memory_debug_dropdown = gr.Dropdown(
                        choices=[],
                        value=None,
                        label="选择一条记忆查看详情",
                        interactive=True,
                        allow_custom_value=False,
                    )
                    memory_debug_content_tb = gr.Textbox(
                        value="",
                        label="记忆内容（只读）",
                        lines=10,
                        interactive=False,
                        max_lines=20,
                    )
                    delete_memory_debug_btn = gr.Button("删除当前选中记忆", variant="secondary", size="sm")

                    gr.Markdown("---")
                    gr.Markdown("### 2. 插件缓存 / 报告（Redis 中已缓存的报告内容）", elem_classes=["section-title"])
                    with gr.Row():
                        cache_report_type = gr.Dropdown(
                            choices=[c[0] for c in CACHE_REPORT_CHOICES],
                            value="bilibili_hotspot",
                            label="报告类型（bilibili_hotspot=B站, douyin=抖音, xiaohongshu=小红书, acfun=AcFun, case_library=案例库, methodology=方法论）",
                        )
                        load_cache_btn = gr.Button("加载报告内容", variant="primary", size="sm")
                    cache_title_md = gr.Markdown(value="选择报告类型后点击「加载报告内容」查看当前缓存。", elem_classes=["gr-panel"])
                    cache_report_content = gr.Textbox(
                        value="",
                        label="报告正文（只读）",
                        lines=22,
                        interactive=False,
                        max_lines=30,
                    )

        # ---------- 初始化 ----------
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
                return "", "", "", t, "（初始化异常）", "", "", "", "*（初始化异常）*"

        demo.load(
            fn=_init,
            inputs=[],
            outputs=[
                state_uid, state_sid, state_tid,
                thinking_json, thinking_md,
                uid_tb, sid_tb, tid_tb, docs_display,
            ],
            queue=False,
        )

        # ---------- 发送 ----------
        def _send(msg, hist, uid, sid, tid, use_stream):
            if use_stream:
                for out in _stream_send_generator(msg, hist, uid or "", sid or "", tid or ""):
                    yield out
            else:
                new_hist, new_uid, new_sid, new_tid, think = send_message_with_stream_option(
                    msg, hist, uid or "", sid or "", tid or "", use_stream
                )
                md = _format_thinking(think)
                docs_md = fetch_docs_display(new_sid or "")
                yield new_hist, "", new_uid, new_sid, new_tid, think, md, new_uid, new_sid, new_tid, docs_md

        for evt in [send_btn.click, user_input.submit]:
            evt(
                fn=_send,
                inputs=[user_input, chatbot, state_uid, state_sid, state_tid, stream_check],
                outputs=[
                    chatbot, user_input, state_uid, state_sid, state_tid,
                    thinking_json, thinking_md, uid_tb, sid_tb, tid_tb, docs_display,
                ],
                queue=True,
            )

        def _load_memory(uid: str):
            md, choices, _ = fetch_memory_list(uid or "")
            first_id = choices[0][0] if choices else None
            content = fetch_memory_content(uid or "", first_id) if first_id else "（无）"
            return md, gr.Dropdown(choices=choices, value=first_id), content

        def _on_memory_select(uid: str, memory_id: Optional[str]):
            if not memory_id:
                return "（请先加载记忆并选择一条）"
            return fetch_memory_content(uid or "", memory_id)

        def _clear_memory_ui(uid: str):
            ok, msg = clear_memory_api(uid or "")
            if not ok:
                return f"**记忆**\n\n{msg}", gr.Dropdown(choices=[], value=None), "（清空未成功）"
            md, choices, _ = fetch_memory_list(uid or "")
            return md, gr.Dropdown(choices=choices, value=None), "（已清空）"

        def _delete_memory_ui(uid: str, memory_id: Optional[str]):
            md, choices, _ = fetch_memory_list(uid or "")
            if not memory_id:
                return "**记忆**\n\n请先选择要删除的记忆条。", gr.Dropdown(choices=choices, value=None), "（未选择）"
            ok, msg = delete_memory_item_api(uid or "", memory_id)
            if not ok:
                return f"**记忆**\n\n{msg}", gr.Dropdown(choices=choices, value=memory_id), "（删除未成功）"
            first_id = choices[0][0] if choices else None
            content = fetch_memory_content(uid or "", first_id) if first_id else "（已删除该条）"
            return md, gr.Dropdown(choices=choices, value=first_id), content

        load_memory_btn.click(
            fn=_load_memory,
            inputs=[state_uid],
            outputs=[memory_summary_md, memory_dropdown, memory_content_tb],
            queue=False,
        )
        memory_dropdown.change(
            fn=_on_memory_select,
            inputs=[state_uid, memory_dropdown],
            outputs=[memory_content_tb],
            queue=False,
        )
        clear_memory_btn.click(
            fn=_clear_memory_ui,
            inputs=[state_uid],
            outputs=[memory_summary_md, memory_dropdown, memory_content_tb],
            queue=False,
        )
        delete_memory_btn.click(
            fn=_delete_memory_ui,
            inputs=[state_uid, memory_dropdown],
            outputs=[memory_summary_md, memory_dropdown, memory_content_tb],
            queue=False,
        )

        file_input.change(
            fn=upload_file,
            inputs=[file_input, state_uid, state_sid],
            outputs=[upload_out, docs_display],
        )

        def _new(uid: str):
            try:
                hist, uid, sid, tid, think = new_chat(uid or "")
                md = _format_thinking(think)
                docs_md = fetch_docs_display(sid or "")
                return (
                    hist or [], uid or "", sid or "", tid or "",
                    think, md, uid or "", sid or "", tid or "", docs_md,
                )
            except Exception as e:
                t = dict(_DEFAULT_THINKING)
                t["error"] = str(e)
                return [], "", "", "", t, f"（异常: {e}）", "", "", "", "*（异常）*"

        new_chat_btn.click(
            fn=_new,
            inputs=[state_uid],
            outputs=[
                chatbot, state_uid, state_sid, state_tid,
                thinking_json, thinking_md, uid_tb, sid_tb, tid_tb, docs_display,
            ],
        )

        # ---------- 调试 Tab：填入当前 User ID ----------
        def _copy_uid(uid: str):
            return uid or ""

        copy_uid_btn.click(fn=_copy_uid, inputs=[state_uid], outputs=[debug_uid], queue=False)

        # ---------- 调试 Tab：加载记忆 ----------
        def _load_memory_debug(uid: str):
            md, choices, _ = fetch_memory_list(uid or "")
            first_id = choices[0][0] if choices else None
            content = fetch_memory_content(uid or "", first_id) if first_id else "（无）"
            return md, gr.Dropdown(choices=choices, value=first_id), content

        def _on_memory_debug_select(uid: str, memory_id: Optional[str]):
            if not memory_id:
                return "（请先加载记忆并选择一条）"
            return fetch_memory_content(uid or "", memory_id)

        def _clear_memory_debug_ui(uid: str):
            ok, msg = clear_memory_api(uid or "")
            if not ok:
                return f"**记忆**\n\n{msg}", gr.Dropdown(choices=[], value=None), "（清空未成功）"
            md, choices, _ = fetch_memory_list(uid or "")
            return md, gr.Dropdown(choices=choices, value=None), "（已清空）"

        def _delete_memory_debug_ui(uid: str, memory_id: Optional[str]):
            md, choices, _ = fetch_memory_list(uid or "")
            if not memory_id:
                return "**记忆**\n\n请先选择要删除的记忆条。", gr.Dropdown(choices=choices, value=None), "（未选择）"
            ok, msg = delete_memory_item_api(uid or "", memory_id)
            if not ok:
                return f"**记忆**\n\n{msg}", gr.Dropdown(choices=choices, value=memory_id), "（删除未成功）"
            first_id = choices[0][0] if choices else None
            content = fetch_memory_content(uid or "", first_id) if first_id else "（已删除该条）"
            return md, gr.Dropdown(choices=choices, value=first_id), content

        load_memory_debug_btn.click(
            fn=_load_memory_debug,
            inputs=[debug_uid],
            outputs=[memory_debug_summary_md, memory_debug_dropdown, memory_debug_content_tb],
            queue=False,
        )
        memory_debug_dropdown.change(
            fn=_on_memory_debug_select,
            inputs=[debug_uid, memory_debug_dropdown],
            outputs=[memory_debug_content_tb],
            queue=False,
        )
        clear_memory_debug_btn.click(
            fn=_clear_memory_debug_ui,
            inputs=[debug_uid],
            outputs=[memory_debug_summary_md, memory_debug_dropdown, memory_debug_content_tb],
            queue=False,
        )
        delete_memory_debug_btn.click(
            fn=_delete_memory_debug_ui,
            inputs=[debug_uid, memory_debug_dropdown],
            outputs=[memory_debug_summary_md, memory_debug_dropdown, memory_debug_content_tb],
            queue=False,
        )

        # ---------- 调试 Tab：加载插件缓存报告 ----------
        def _load_cache(rt: str):
            content, title = fetch_cache_report(rt or "")
            return title, content

        load_cache_btn.click(
            fn=_load_cache,
            inputs=[cache_report_type],
            outputs=[cache_title_md, cache_report_content],
            queue=False,
        )

        demo.queue()
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
    # 端口：环境变量 GRADIO_SERVER_PORT 优先；7860 被占用时自动尝试 7861～7870
    try:
        _port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    except (ValueError, TypeError):
        _port = 7860
    _fix_label_for = """
    <script>
    (function() {
      function fixLabelFor() {
        try {
          document.querySelectorAll('label[for]').forEach(function(label) {
            var id = label.getAttribute('for');
            if (id && !document.getElementById(id)) {
              label.removeAttribute('for');
            }
          });
        } catch (e) {}
      }
      function run() {
        fixLabelFor();
        if (document.readyState === 'loading') {
          document.addEventListener('DOMContentLoaded', fixLabelFor);
        }
        var t = 0, iv = setInterval(function() { fixLabelFor(); t += 200; if (t >= 5000) clearInterval(iv); }, 200);
        var obs = new MutationObserver(function() { fixLabelFor(); });
        obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
      }
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', run);
      } else {
        run();
      }
    })();
    </script>
    """
    app = build_ui()
    # Gradio 6: theme/css 放在 launch；queue 已对发送事件启用；端口占用时自动尝试下一端口
    for attempt in range(11):
        port = _port + attempt
        try:
            app.launch(
                server_name="0.0.0.0",
                server_port=port,
                share=False,
                show_error=True,
                footer_links=[],
                head=_fix_label_for,
                theme=gr.themes.Soft(primary_hue="slate", secondary_hue="gray"),
                css=CUSTOM_CSS,
            )
            break
        except OSError as e:
            if "10048" in str(e) or "address already in use" in str(e).lower() or "Cannot find empty port" in str(e):
                if attempt < 10:
                    print(f"[提示] 端口 {port} 已被占用，尝试 {port + 1} ...")
                else:
                    print(f"[错误] 端口 {_port}～{port} 均不可用，请关闭占用进程或设置 GRADIO_SERVER_PORT=其他端口")
                    raise
            else:
                raise
