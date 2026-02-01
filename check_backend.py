"""
后端服务诊断脚本
检查后端服务状态、数据库连接、Redis 连接等
运行：python check_backend.py
"""
import sys
import requests
import time

try:
    from frontend.config import BACKEND_URL
except ImportError:
    BACKEND_URL = "http://localhost:8000"

def check_backend_running():
    """检查后端是否运行"""
    print("1. 检查后端服务...")
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
        print(f"   ✅ 后端服务运行中")
        print(f"   状态码: {resp.status_code}")
        data = resp.json()
        print(f"   健康状态: {data}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"   ❌ 无法连接到后端 ({BACKEND_URL})")
        print(f"   请检查:")
        print(f"      1. 是否启动了后端？运行: uvicorn main:app --reload")
        print(f"      2. 端口是否正确？默认应该是 8000")
        return False
    except requests.exceptions.Timeout:
        print(f"   ⚠️ 连接超时")
        return False
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False

def check_database():
    """检查数据库容器"""
    print("\n2. 检查 PostgreSQL 容器...")
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=postgres", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            print(f"   ✅ PostgreSQL 容器运行中")
            print(f"   {result.stdout.strip()}")
            return True
        else:
            print(f"   ❌ PostgreSQL 容器未运行")
            print(f"   请运行: docker compose -f docker-compose.dev.yml up -d")
            return False
    except FileNotFoundError:
        print(f"   ⚠️ Docker 未安装或不在 PATH 中")
        return False
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False

def check_redis():
    """检查 Redis 容器"""
    print("\n3. 检查 Redis 容器...")
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=redis", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            print(f"   ✅ Redis 容器运行中")
            print(f"   {result.stdout.strip()}")
            return True
        else:
            print(f"   ❌ Redis 容器未运行")
            print(f"   请运行: docker compose -f docker-compose.dev.yml up -d")
            return False
    except FileNotFoundError:
        print(f"   ⚠️ Docker 未安装或不在 PATH 中")
        return False
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return False

def check_api_endpoints():
    """检查 API 端点"""
    print("\n4. 检查前端 API 端点...")
    
    # 检查根路径
    try:
        resp = requests.get(f"{BACKEND_URL}/", timeout=5)
        print(f"   ✅ 根路径可访问")
        endpoints = resp.json().get("endpoints", {})
        if "frontend_session_init" in endpoints:
            print(f"   ✅ frontend/session/init 端点已注册")
            print(f"      {endpoints['frontend_session_init']}")
        else:
            print(f"   ❌ frontend/session/init 端点未注册")
            print(f"   可用端点: {list(endpoints.keys())}")
    except Exception as e:
        print(f"   ❌ 无法检查端点: {e}")
    
    # 直接测试 frontend/session/init
    print("\n5. 测试 /api/v1/frontend/session/init...")
    try:
        resp = requests.get(f"{BACKEND_URL}/api/v1/frontend/session/init", timeout=5)
        if resp.status_code == 200:
            print(f"   ✅ 端点工作正常")
            data = resp.json()
            print(f"   响应: user_id={data.get('user_id', '')[:20]}...")
        else:
            print(f"   ❌ 端点返回错误")
            print(f"   状态码: {resp.status_code}")
            print(f"   响应: {resp.text}")
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")

def main():
    print("=" * 60)
    print("后端服务诊断")
    print("=" * 60)
    
    # 检查后端
    backend_ok = check_backend_running()
    
    # 检查数据库和 Redis
    if backend_ok:
        check_api_endpoints()
    else:
        print("\n⚠️ 后端未运行，检查依赖服务...")
        check_database()
        check_redis()
        
        print("\n" + "=" * 60)
        print("建议操作：")
        print("=" * 60)
        print("1. 启动数据库和 Redis:")
        print("   docker compose -f docker-compose.dev.yml up -d")
        print("")
        print("2. 检查 .env 文件是否存在并配置了 DASHSCOPE_API_KEY")
        print("   copy .env.dev .env")
        print("   notepad .env")
        print("")
        print("3. 启动后端:")
        print("   uvicorn main:app --reload")
        print("")
        print("4. 重新运行此脚本验证:")
        print("   python check_backend.py")

if __name__ == "__main__":
    main()
