"""
诊断对话应答流程：模拟前端发送，打印后端响应与异常。
用于排查「输入对话无法正常应答」问题。
运行前请确保后端已启动：uvicorn main:app --reload
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

BACKEND = "http://localhost:8000"


def main():
    print("=" * 60)
    print("对话应答诊断")
    print("=" * 60)

    # 1. 初始化会话
    print("\n1. 初始化会话...")
    try:
        r = requests.get(f"{BACKEND}/api/v1/frontend/session/init", timeout=10)
        print(f"   状态码: {r.status_code}")
        data = r.json()
        if r.status_code != 200 or not data.get("success"):
            print(f"   失败: {data}")
            return
        user_id = data.get("user_id", "")
        session_id = data.get("session_id", "")
        print(f"   user_id: {user_id[:40]}...")
        print(f"   session_id: {session_id[:36]}...")
    except Exception as e:
        print(f"   异常: {e}")
        return

    # 2. 发送聊天消息（系统按意图自动路由，无需指定 mode）
    print("\n2. 发送消息...")
    payload = {
        "message": "你好",
        "session_id": session_id,
        "user_id": user_id,
    }
    try:
        r = requests.post(
            f"{BACKEND}/api/v1/frontend/chat",
            json=payload,
            timeout=60,
        )
        print(f"   状态码: {r.status_code}")
        try:
            data = r.json()
        except Exception:
            print(f"   响应非 JSON: {r.text[:500]}")
            return

        if r.status_code == 200:
            if data.get("success"):
                resp_text = data.get("response", "")
                print(f"   成功! 回复长度: {len(resp_text)} 字")
                print(f"   回复预览: {resp_text[:200]}...")
            else:
                print(f"   失败: success=False")
                print(f"   error: {data.get('error')}")
                print(f"   detail: {data.get('detail', '')}")
        else:
            print(f"   HTTP 错误: {data.get('error', data)}")
    except requests.exceptions.Timeout:
        print("   超时 (60s)")
    except Exception as e:
        print(f"   异常: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60)
    print("诊断完成。若后端返回 200 且 success=True，则 API 正常。")
    print("若前端仍无应答，请检查：")
    print("  - 后端控制台是否有异常日志")
    print("  - 浏览器控制台是否有 JS 报错")
    print("=" * 60)


if __name__ == "__main__":
    main()
