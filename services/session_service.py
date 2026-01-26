import redis
import uuid
import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any


class SessionService:
    """会话服务类，使用 Redis 作为后端存储"""
    
    def __init__(self):
        """初始化 Redis 连接"""
        self.redis_client = redis.Redis()
    
    async def create_session(self, user_id: str, initial_data: Optional[Dict[str, Any]] = None) -> str:
        """
        创建新的会话
        
        Args:
            user_id: 用户唯一标识
            initial_data: 初始数据字典（可选）
            
        Returns:
            session_id: 生成的会话ID
        """
        # 生成唯一的 session_id
        session_id = str(uuid.uuid4())
        
        # 构建会话数据
        session_data = {
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "initial_data": initial_data or {}
        }
        
        # 将数据转换为 JSON 字符串
        session_json = json.dumps(session_data, ensure_ascii=False)
        
        # 存储到 Redis，键名为 session:{session_id}，设置过期时间为1小时（3600秒）
        await asyncio.to_thread(
            self.redis_client.setex,
            f"session:{session_id}",
            3600,  # 1小时 = 3600秒
            session_json
        )
        
        return session_id
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 session_id 获取会话数据
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话数据字典，如果不存在则返回 None
        """
        # 从 Redis 获取数据
        session_json = await asyncio.to_thread(
            self.redis_client.get,
            f"session:{session_id}"
        )
        
        # 如果数据不存在，返回 None
        if session_json is None:
            return None
        
        # 将 JSON 字符串解析为字典
        try:
            session_data = json.loads(session_json.decode('utf-8'))
            return session_data
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
