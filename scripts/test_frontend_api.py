"""
测试前端 API 接口：/api/v1/frontend/session/init 与 /api/v1/frontend/chat
运行前请确保后端服务已启动：uvicorn main:app --reload
"""
import requests

BACKEND_URL = "http://localhost:8000"


def test_session_init():
    """测试会话初始化接口"""
    print("=== 测试 GET /api/v1/frontend/session/init ===")
    resp = requests.get(f"{BACKEND_URL}/api/v1/frontend/session/init")
    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {data}")
    
    if data.get("success"):
        user_id = data.get("user_id")
        session_id = data.get("session_id")
        print(f"✅ 初始化成功: user_id={user_id}, session_id={session_id}")
        return user_id, session_id
    else:
        print(f"❌ 初始化失败: {data.get('error')}")
        return None, None


def test_chat_casual(user_id: str, session_id: str):
    """测试闲聊路由（意图=casual_chat 时自动走快捷回复）"""
    print("\n=== 测试 POST /api/v1/frontend/chat（闲聊） ===")
    payload = {
        "message": "你好，我想了解一下AI营销助手的功能",
        "session_id": session_id,
        "user_id": user_id,
    }
    resp = requests.post(f"{BACKEND_URL}/api/v1/frontend/chat", json=payload)
    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {data}")
    
    if data.get("success"):
        print(f"✅ 闲聊成功 mode={data.get('mode')}")
        print(f"  AI 回复: {data.get('response')}")
    else:
        print(f"❌ 闲聊失败: {data.get('error')}")


def test_chat_creation(user_id: str, session_id: str):
    """测试创作路由（意图=free_discussion 时自动走 MetaWorkflow）"""
    print("\n=== 测试 POST /api/v1/frontend/chat（创作） ===")
    payload = {
        "message": "我想推广一款新的降噪耳机，目标用户是年轻的上班族",
        "session_id": session_id,
        "user_id": user_id,
        "tags": ["科技", "年轻人"],
    }
    resp = requests.post(f"{BACKEND_URL}/api/v1/frontend/chat", json=payload, timeout=150)
    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {data.keys()}")  # 不打印全部内容，太长
    
    if data.get("success"):
        print(f"✅ 创作成功 mode={data.get('mode')}")
        print(f"  意图: {data.get('intent')}")
        print(f"  AI 回复长度: {len(data.get('response', ''))}")
        print(f"  思考步骤数: {len(data.get('thinking_process', []))}")
        print(f"  AI 回复预览: {data.get('response', '')[:200]}...")
    else:
        print(f"❌ 创作失败: {data.get('error')}")


def test_session_expired(user_id: str):
    """测试会话过期场景"""
    print("\n=== 测试会话过期（使用无效 session_id） ===")
    payload = {
        "message": "测试会话过期",
        "session_id": "invalid_session_id_12345",
        "user_id": user_id,
    }
    resp = requests.post(f"{BACKEND_URL}/api/v1/frontend/chat", json=payload)
    print(f"状态码: {resp.status_code}")
    data = resp.json()
    print(f"响应: {data}")
    
    if resp.status_code == 440:
        print(f"✅ 会话过期检测正确，状态码 440")
        print(f"  错误码: {data.get('error_code')}")
    else:
        print(f"⚠️ 期望状态码 440，实际: {resp.status_code}")


if __name__ == "__main__":
    print("开始测试前端 API 接口...\n")
    
    # 1. 测试会话初始化
    user_id, session_id = test_session_init()
    if not user_id or not session_id:
        print("\n❌ 会话初始化失败，跳过后续测试")
        exit(1)
    
    # 2. 测试闲聊路由
    test_chat_casual(user_id, session_id)
    
    # 3. 测试创作路由（MetaWorkflow）- 需要较长时间
    print("\n⏳ 创作模式可能需要 1-2 分钟，请耐心等待...")
    test_chat_creation(user_id, session_id)
    
    # 4. 测试会话过期
    test_session_expired(user_id)
    
    print("\n=== 测试完成 ===")
