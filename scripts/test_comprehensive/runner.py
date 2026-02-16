# 综合测试运行器
import asyncio
import httpx
import random
import subprocess
import time
import json
import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_root))

# 加载 .env
from dotenv import load_dotenv
for _f in (".env", ".env.dev", ".env.prod"):
    _p = _root / _f
    if _p.exists():
        load_dotenv(_p, override=True)
        break

from scripts.test_comprehensive.config import (
    API_BASE_URL, API_TIMEOUT, USER_PREFIXES,
    CONCURRENT_USERS, REQUEST_INTERVAL_MS, REQUEST_INTERVAL_JITTER,
    MAX_RETRIES, RETRY_DELAY_SEC, MAX_TOTAL_TOKENS, REQUIRED_SERVICES
)
from scripts.test_comprehensive.data import (
    SHORT_TERM_PREFERENCES, LONG_TERM_INTROS, CASUAL_QUERIES,
    EXTRACT_QUERIES, CROSS_INTENT_FIRST, CROSS_INTENT_SECOND,
    CREATION_QUERIES, CLARIFY_QUERIES, HOTSPOT_QUERIES,
    DIAGNOSIS_QUERIES, GENERATOR_QUERIES, get_user_id, get_random_item
)
from scripts.test_comprehensive.validators import Validators, TestResult


class ComprehensiveTester:
    """综合测试运行器"""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=API_TIMEOUT)
        self.validators = Validators()
        self.results = {}
        self.total_tokens = 0
        self.total_requests = 0
        self.start_time = None
        self.end_time = None
    
    async def close(self):
        await self.client.aclose()
    
    async def call_api(self, payload: dict, retries: int = MAX_RETRIES) -> dict:
        """调用API，带重试"""
        url = f"{self.base_url}/api/v1/analyze-deep/raw"
        
        for attempt in range(retries):
            try:
                response = await self.client.post(url, json=payload)
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"  [WARN] API返回 {response.status_code}: {response.text[:100]}")
            except Exception as e:
                print(f"  [ERROR] API调用失败: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(RETRY_DELAY_SEC)
        
        return {"success": False, "error": "API调用失败"}
    
    async def sleep_random(self):
        """随机延迟"""
        delay = (REQUEST_INTERVAL_MS + random.randint(-REQUEST_INTERVAL_JITTER, REQUEST_INTERVAL_JITTER)) / 1000
        await asyncio.sleep(max(0.1, delay))

    # ==================== 启动前检查 ====================

    def _check_services_running(self) -> bool:
        """检查 Docker 服务是否均已启动"""
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"  [FAIL] 无法执行 docker 命令: {e}")
            return False
        if result.returncode != 0:
            print(f"  [FAIL] docker ps 失败: {result.stderr or result.stdout}")
            return False

        lines = (result.stdout or "").strip().splitlines()
        running = {}
        for line in lines:
            parts = line.split("\t", 1)
            if len(parts) >= 2:
                name, status = parts[0].strip(), parts[1].strip().lower()
                running[name] = "up" in status or "healthy" in status or "running" in status

        ok = True
        for name in REQUIRED_SERVICES:
            if running.get(name):
                print(f"  [OK] {name}")
            else:
                print(f"  [FAIL] {name} 未运行")
                ok = False
        return ok

    async def _check_api_ready(self) -> bool:
        """检查 API 调用是否正常"""
        url = f"{self.base_url}/api/v1/analyze-deep/raw"
        payload = {"user_id": "preflight_check", "raw_input": "你好"}
        try:
            response = await self.client.post(url, json=payload)
            if response.status_code != 200:
                print(f"  [FAIL] API 返回 {response.status_code}: {response.text[:80]}")
                return False
            data = response.json()
            if data.get("success") is not True:
                print(f"  [FAIL] API success=False: {data.get('error', data)}")
                return False
            print(f"  [OK] API 调用正常 (data 长度={len(str(data.get('data', '')))}")
            return True
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            print(f"  [FAIL] API 调用异常: {err_msg}")
            return False

    async def run_preflight_checks(self) -> bool:
        """执行启动前检查：服务 + API，全部通过返回 True"""
        print("\n" + "=" * 60)
        print("启动前检查")
        print("=" * 60)
        print("1. Docker 服务状态:")
        if not self._check_services_running():
            print("\n[终止] 部分服务未启动，请先执行: docker compose --env-file .env.prod -f docker-compose.prod.yml up -d")
            return False
        print("\n2. API 调用:")
        if not await self._check_api_ready():
            print("\n[终止] API 不可用，请确认服务已启动且健康")
            return False
        print("\n[通过] 所有检查通过，开始测试\n")
        sys.stdout.flush()
        return True

    # ==================== 记忆系统测试 ====================
    
    async def test_short_term_memory(self) -> TestResult:
        """短期记忆测试：5轮对话"""
        result = TestResult("短期记忆")
        print("\n" + "="*50)
        print("测试: 短期记忆（5轮对话）")
        print("="*50)
        
        users = 10
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["short_term"], user_idx)
            session_id = None
            
            print(f"\n[用户 {user_idx}/{users}] {user_id}")
            sys.stdout.flush()
            
            # 5轮对话
            for round_idx in range(1, 6):
                # 每轮使用不同的偏好话题
                preference = SHORT_TERM_PREFERENCES[(user_idx + round_idx - 2) % len(SHORT_TERM_PREFERENCES)]
                
                # 第一轮设置偏好，后续轮次询问
                if round_idx == 1:
                    query = preference
                else:
                    # 询问之前说过什么
                    query = "我刚才说什么了？"
                
                payload = {
                    "user_id": user_id,
                    "raw_input": query,
                    "session_id": session_id or ""
                }
                
                response = await self.call_api(payload)
                
                # 验证
                if self.validators.check_api_success(response):
                    result.add_success(tokens=300)
                    
                    # 提取 session_id
                    if not session_id:
                        session_id = self.validators.extract_session_id(response)
                    
                    # 检查记忆
                    if round_idx > 1:
                        content = str(response.get("data", ""))
                        # 检查是否记住了之前的偏好
                        recall_keywords = ["科技", "数码", "美食", "时尚", "职场", "旅游", "健康", "教育", "音乐", "家居", "汽车"]
                        if any(kw in content for kw in recall_keywords):
                            print(f"  轮{round_idx}: PASS - 记住偏好")
                        else:
                            print(f"  轮{round_idx}: 可能未记住（需人工确认）")
                else:
                    result.add_failure(f"轮{round_idx}失败")
                    print(f"  轮{round_idx}: FAIL")
                
                await self.sleep_random()
            
            self.total_requests += 5
        
        print(f"\n短期记忆结果: {result.summary()}")
        return result
    
    async def test_long_term_memory(self) -> TestResult:
        """长期记忆测试：跨会话"""
        result = TestResult("长期记忆")
        print("\n" + "="*50)
        print("测试: 长期记忆（跨会话）")
        print("="*50)
        
        users = 10
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["long_term"], user_idx)
            
            # 第一轮：自我介绍
            brand_name, industry = LONG_TERM_INTROS[user_idx - 1]
            intro_query = f"我叫{brand_name}，我是做{industry}的"
            
            print(f"\n[用户 {user_idx}/{users}] {user_id}")
            sys.stdout.flush()
            print(f"  第一轮: {intro_query}")
            
            payload1 = {"user_id": user_id, "raw_input": intro_query}
            response1 = await self.call_api(payload1)
            
            if self.validators.check_api_success(response1):
                result.add_success(tokens=400)
                print(f"  第一轮: PASS")
            else:
                result.add_failure("第一轮失败")
                print(f"  第一轮: FAIL")
            
            await asyncio.sleep(1)  # 等待持久化
            
            # 第二轮：询问我是谁
            query2 = "我是谁？"
            payload2 = {"user_id": user_id, "raw_input": query2}
            response2 = await self.call_api(payload2)
            
            if self.validators.check_api_success(response2):
                result.add_success(tokens=400)
                
                content = str(response2.get("data", ""))
                if self.validators.check_long_term_memory(content, brand_name, industry):
                    print(f"  第二轮: PASS - 记住{brand_name}/{industry}")
                else:
                    print(f"  第二轮: 可能未记住（需人工确认）")
            else:
                result.add_failure("第二轮失败")
                print(f"  第二轮: FAIL")
            
            await self.sleep_random()
        
        print(f"\n长期记忆结果: {result.summary()}")
        return result
    
    async def test_context_window(self) -> TestResult:
        """上下文窗口测试：多轮连续"""
        result = TestResult("上下文窗口")
        print("\n" + "="*50)
        print("测试: 上下文窗口（4轮对话）")
        print("="*50)
        
        users = 5
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["context"], user_idx)
            query_template, brand, product = CROSS_INTENT_FIRST[(user_idx - 1) % len(CROSS_INTENT_FIRST)]
            
            session_id = None
            keywords_remember = []
            
            print(f"\n[用户 {user_idx}/{users}] {user_id}")
            sys.stdout.flush()
            
            # 4轮对话
            queries = [
                query_template,
                "目标人群是年轻人",
                "强调性价比",
                "我之前说了什么？"
            ]
            
            for round_idx, query in enumerate(queries, 1):
                payload = {
                    "user_id": user_id,
                    "raw_input": query,
                    "session_id": session_id or ""
                }
                
                response = await self.call_api(payload)
                
                if self.validators.check_api_success(response):
                    result.add_success(tokens=400)
                    
                    if not session_id:
                        session_id = self.validators.extract_session_id(response)
                    
                    # 记录关键词
                    if round_idx <= 3:
                        keywords_remember.extend([brand, product, "年轻人", "性价比"])
                    
                    print(f"  轮{round_idx}: PASS")
                else:
                    result.add_failure(f"轮{round_idx}失败")
                    print(f"  轮{round_idx}: FAIL")
                
                await self.sleep_random()
            
            self.total_requests += 4
        
        print(f"\n上下文窗口结果: {result.summary()}")
        return result
    
    async def test_tag_update(self) -> TestResult:
        """标签更新测试"""
        result = TestResult("标签更新")
        print("\n" + "="*50)
        print("测试: 标签更新")
        print("="*50)
        
        users = 10
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["tag"], user_idx)
            
            # 第一轮：设置标签
            tag1 = SHORT_TERM_PREFERENCES[user_idx - 1]
            payload1 = {"user_id": user_id, "raw_input": tag1}
            response1 = await self.call_api(payload1)
            
            if self.validators.check_api_success(response1):
                result.add_success(tokens=300)
                print(f"  用户{user_idx}-1: PASS")
            else:
                result.add_failure(f"用户{user_idx}-1失败")
                print(f"  用户{user_idx}-1: FAIL")
            
            await self.sleep_random()
            
            # 第二轮：追加标签
            tag2 = SHORT_TERM_PREFERENCES[(user_idx + 5) % len(SHORT_TERM_PREFERENCES)]
            payload2 = {"user_id": user_id, "raw_input": tag2}
            response2 = await self.call_api(payload2)
            
            if self.validators.check_api_success(response2):
                result.add_success(tokens=300)
                print(f"  用户{user_idx}-2: PASS")
            else:
                result.add_failure(f"用户{user_idx}-2失败")
                print(f"  用户{user_idx}-2: FAIL")
            
            await self.sleep_random()
        
        print(f"\n标签更新结果: {result.summary()}")
        return result
    
    # ==================== 意图识别测试 ====================
    
    async def test_casual_classify(self) -> TestResult:
        """闲聊分类测试"""
        result = TestResult("闲聊分类")
        print("\n" + "="*50)
        print("测试: 闲聊分类")
        print("="*50)
        
        users = 15
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["casual"], user_idx)
            query, expected = CASUAL_QUERIES[user_idx - 1]
            
            payload = {"user_id": user_id, "raw_input": query}
            response = await self.call_api(payload)
            
            if self.validators.check_api_success(response):
                result.add_success(tokens=200)
                
                # 检查意图是否匹配（只做参考，不强制）
                actual_intent = response.get("intent", "")
                print(f"  [{query[:10]}...] -> {actual_intent}")
            else:
                result.add_failure(f"查询失败: {query}")
                print(f"  [{query[:10]}...]: FAIL")
            
            await self.sleep_random()
        
        print(f"\n闲聊分类结果: {result.summary()}")
        return result
    
    async def test_self_extract(self) -> TestResult:
        """自定义提取测试"""
        result = TestResult("自定义提取")
        print("\n" + "="*50)
        print("测试: 自定义提取")
        print("="*50)
        
        users = 10
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["extract"], user_idx)
            query, expected_brand, expected_industry = EXTRACT_QUERIES[user_idx - 1]
            
            payload = {"user_id": user_id, "raw_input": query}
            response = await self.call_api(payload)
            
            if self.validators.check_api_success(response):
                result.add_success(tokens=250)
                
                # 检查是否提取到了信息
                sd = response.get("structured_data", {})
                extracted_brand = sd.get("brand_name", "")
                extracted_topic = sd.get("topic", "")
                
                print(f"  [{query[:15]}...]")
                print(f"    提取: brand={extracted_brand}, topic={extracted_topic}")
            else:
                result.add_failure(f"查询失败: {query}")
                print(f"  [{query[:15]}...]: FAIL")
            
            await self.sleep_random()
        
        print(f"\n自定义提取结果: {result.summary()}")
        return result
    
    async def test_cross_intent(self) -> TestResult:
        """交叉意图测试"""
        result = TestResult("交叉意图")
        print("\n" + "="*50)
        print("测试: 交叉意图")
        print("="*50)
        
        users = 10
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["cross"], user_idx)
            
            # 第一轮：设置品牌+话题
            query_template, brand, product = CROSS_INTENT_FIRST[user_idx - 1]
            query1 = f"推广{brand}的{product}"
            
            payload1 = {"user_id": user_id, "raw_input": query1}
            response1 = await self.call_api(payload1)
            
            if self.validators.check_api_success(response1):
                result.add_success(tokens=400)
                print(f"  用户{user_idx}-1: PASS")
            else:
                result.add_failure(f"用户{user_idx}-1失败")
                print(f"  用户{user_idx}-1: FAIL")
            
            await self.sleep_random()
            
            # 第二轮：追加信息
            query2 = CROSS_INTENT_SECOND[user_idx - 1]
            payload2 = {"user_id": user_id, "raw_input": query2}
            response2 = await self.call_api(payload2)
            
            if self.validators.check_api_success(response2):
                result.add_success(tokens=400)
                print(f"  用户{user_idx}-2: PASS")
            else:
                result.add_failure(f"用户{user_idx}-2失败")
                print(f"  用户{user_idx}-2: FAIL")
            
            await self.sleep_random()
        
        print(f"\n交叉意图结果: {result.summary()}")
        return result
    
    # ==================== 全流程测试 ====================
    
    async def test_full_creation(self) -> TestResult:
        """完整创作流程测试"""
        result = TestResult("完整创作")
        print("\n" + "="*50)
        print("测试: 完整创作流程")
        print("="*50)
        
        users = 10
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["full"], user_idx)
            query = CREATION_QUERIES[user_idx - 1]
            
            payload = {"user_id": user_id, "raw_input": query}
            response = await self.call_api(payload)
            
            if self.validators.check_api_success(response):
                result.add_success(tokens=1500)
                
                # 检查是否有生成内容
                if self.validators.check_generation_response(response):
                    print(f"  [{query[:20]}...]: PASS - 有生成内容")
                else:
                    print(f"  [{query[:20]}...]: 可能无内容（需确认）")
            else:
                result.add_failure(f"查询失败: {query}")
                print(f"  [{query[:20]}...]: FAIL")
            
            await self.sleep_random()
        
        print(f"\n完整创作结果: {result.summary()}")
        return result
    
    async def test_clarify_flow(self) -> TestResult:
        """澄清流程测试"""
        result = TestResult("澄清流程")
        print("\n" + "="*50)
        print("测试: 澄清流程")
        print("="*50)
        
        users = 5
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["clarify"], user_idx)
            query = CLARIFY_QUERIES[user_idx - 1]
            
            payload = {"user_id": user_id, "raw_input": query}
            response = await self.call_api(payload)
            
            if self.validators.check_api_success(response):
                result.add_success(tokens=1200)
                
                # 检查是否触发了澄清
                if self.validators.check_clarification(response):
                    print(f"  [{query}]: PASS - 触发澄清")
                else:
                    print(f"  [{query}]: 可能未触发澄清")
            else:
                result.add_failure(f"查询失败: {query}")
                print(f"  [{query}]: FAIL")
            
            await self.sleep_random()
        
        print(f"\n澄清流程结果: {result.summary()}")
        return result
    
    # ==================== 插件测试 ====================
    
    async def test_hotspot_plugins(self) -> TestResult:
        """热点插件测试"""
        result = TestResult("热点插件")
        print("\n" + "="*50)
        print("测试: 热点插件")
        print("="*50)
        
        users = 3
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["hotspot"], user_idx)
            
            for query, plugin_type in HOTSPOT_QUERIES:
                payload = {"user_id": user_id, "raw_input": query}
                response = await self.call_api(payload)
                
                if self.validators.check_api_success(response):
                    result.add_success(tokens=600)
                    
                    if self.validators.check_plugin_response(response, plugin_type):
                        print(f"  [{query[:15]}...]: PASS")
                    else:
                        print(f"  [{query[:15]}...]: 可能无插件输出")
                else:
                    result.add_failure(f"查询失败")
                    print(f"  [{query[:15]}...]: FAIL")
                
                await self.sleep_random()
        
        print(f"\n热点插件结果: {result.summary()}")
        return result
    
    async def test_diagnosis_plugins(self) -> TestResult:
        """诊断插件测试"""
        result = TestResult("诊断插件")
        print("\n" + "="*50)
        print("测试: 诊断插件")
        print("="*50)
        
        users = 3
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["diagnosis"], user_idx)
            
            for query, plugin_type in DIAGNOSIS_QUERIES:
                payload = {"user_id": user_id, "raw_input": query}
                response = await self.call_api(payload)
                
                if self.validators.check_api_success(response):
                    result.add_success(tokens=800)
                    
                    if self.validators.check_plugin_response(response, plugin_type):
                        print(f"  [{query[:15]}...]: PASS")
                    else:
                        print(f"  [{query[:15]}...]: 可能无插件输出")
                else:
                    result.add_failure(f"查询失败")
                    print(f"  [{query[:15]}...]: FAIL")
                
                await self.sleep_random()
        
        print(f"\n诊断插件结果: {result.summary()}")
        return result
    
    async def test_generator_plugins(self) -> TestResult:
        """生成插件测试"""
        result = TestResult("生成插件")
        print("\n" + "="*50)
        print("测试: 生成插件")
        print("="*50)
        
        users = 4
        for user_idx in range(1, users + 1):
            user_id = get_user_id(USER_PREFIXES["generator"], user_idx)
            
            for query, plugin_type in GENERATOR_QUERIES:
                payload = {"user_id": user_id, "raw_input": query}
                response = await self.call_api(payload)
                
                if self.validators.check_api_success(response):
                    result.add_success(tokens=1000)
                    
                    if self.validators.check_generation_response(response):
                        print(f"  [{query}]: PASS")
                    else:
                        print(f"  [{query}]: 可能无生成内容")
                else:
                    result.add_failure(f"查询失败")
                    print(f"  [{query}]: FAIL")
                
                await self.sleep_random()
        
        print(f"\n生成插件结果: {result.summary()}")
        return result
    
    # ==================== 阶段报告 ====================
    
    def _save_partial_report(self, phase_name: str, phase_index: int):
        """每阶段完成后输出并保存部分测试报告，防止长时间无输出被误判卡死"""
        duration = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        total_requests = sum(r.requests for r in self.results.values())
        total_successes = sum(r.successes for r in self.results.values())
        total_failures = sum(r.failures for r in self.results.values())
        total_tokens = sum(r.token_estimate for r in self.results.values())
        overall_rate = (total_successes / total_requests * 100) if total_requests > 0 else 0

        report = {
            "phase": phase_name,
            "phase_index": phase_index,
            "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_minutes": round(duration / 60, 1),
            "status": "partial",
            "total_requests": total_requests,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "overall_rate": round(overall_rate, 1),
            "total_tokens": total_tokens,
            "results": {name: r.summary() for name, r in self.results.items()},
        }

        output_dir = Path(__file__).parent
        partial_file = output_dir / "test_results_partial.json"
        with open(partial_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print("\n" + "=" * 60)
        print(f"【阶段 {phase_index}/4】{phase_name} - 部分测试报告")
        print("=" * 60)
        print(f"  已完成请求: {total_requests}  成功: {total_successes}  失败: {total_failures}")
        print(f"  成功率: {overall_rate:.1f}%  Token估算: {total_tokens}  已用时: {duration/60:.1f} 分钟")
        print(f"  报告已保存: {partial_file}")
        print("=" * 60 + "\n")
        sys.stdout.flush()

    # ==================== 主测试 ====================
    
    async def run_intent_only(self):
        """只运行意图识别测试（闲聊分类、自定义提取、交叉意图）"""
        if not await self.run_preflight_checks():
            return None

        self.start_time = datetime.now()
        print("\n" + "="*60)
        print("AI 营销助手 - 意图识别测试")
        print("="*60)
        print(f"API地址: {self.base_url}")
        print(f"开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # 意图识别测试
        self.results["闲聊分类"] = await self.test_casual_classify()
        self.results["自定义提取"] = await self.test_self_extract()
        self.results["交叉意图"] = await self.test_cross_intent()

        self.end_time = datetime.now()
        await self.close()

        return self.print_summary()

    async def run_all_tests(self):
        """运行所有测试"""
        if not await self.run_preflight_checks():
            return None

        self.start_time = datetime.now()
        print("\n" + "="*60)
        print("AI 营销助手 - 综合测试开始")
        print("="*60)
        print(f"API地址: {self.base_url}")
        print(f"开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # 记忆系统测试
        self.results["短期记忆"] = await self.test_short_term_memory()
        self.results["长期记忆"] = await self.test_long_term_memory()
        self.results["上下文窗口"] = await self.test_context_window()
        self.results["标签更新"] = await self.test_tag_update()
        self._save_partial_report("记忆系统", 1)

        # 意图识别测试
        self.results["闲聊分类"] = await self.test_casual_classify()
        self.results["自定义提取"] = await self.test_self_extract()
        self.results["交叉意图"] = await self.test_cross_intent()
        self._save_partial_report("意图识别", 2)

        # 全流程测试
        self.results["完整创作"] = await self.test_full_creation()
        self.results["澄清流程"] = await self.test_clarify_flow()
        self._save_partial_report("全流程", 3)

        # 插件测试
        self.results["热点插件"] = await self.test_hotspot_plugins()
        self.results["诊断插件"] = await self.test_diagnosis_plugins()
        self.results["生成插件"] = await self.test_generator_plugins()
        self._save_partial_report("插件", 4)

        self.end_time = datetime.now()
        await self.close()

        return self.print_summary()
    
    def print_summary(self) -> dict:
        """打印测试汇总"""
        duration = (self.end_time - self.start_time).total_seconds()
        
        print("\n" + "="*60)
        print("测试汇总")
        print("="*60)
        
        total_requests = 0
        total_successes = 0
        total_failures = 0
        total_tokens = 0
        
        print(f"\n{'场景':<15} {'请求':<8} {'成功':<8} {'失败':<8} {'成功率':<10} {'Token':<10}")
        print("-" * 60)
        
        for name, result in self.results.items():
            total_requests += result.requests
            total_successes += result.successes
            total_failures += result.failures
            total_tokens += result.token_estimate
            
            print(f"{name:<15} {result.requests:<8} {result.successes:<8} {result.failures:<8} {result.success_rate:<10.1f}% {result.token_estimate:<10}")
        
        print("-" * 60)
        overall_rate = (total_successes / total_requests * 100) if total_requests > 0 else 0
        print(f"{'总计':<15} {total_requests:<8} {total_successes:<8} {total_failures:<8} {overall_rate:<10.1f}% {total_tokens:<10}")
        
        print(f"\n总Token估算: {total_tokens}")
        print(f"测试时长: {duration/60:.1f} 分钟")
        print(f"结束时间: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return {
            "total_requests": total_requests,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "overall_rate": overall_rate,
            "total_tokens": total_tokens,
            "duration_minutes": duration / 60,
            "results": {name: result.summary() for name, result in self.results.items()}
        }


async def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description="综合测试运行器")
    parser.add_argument("--intent", action="store_true", help="只运行意图识别测试")
    args = parser.parse_args()

    tester = ComprehensiveTester()

    if args.intent:
        summary = await tester.run_intent_only()
    else:
        summary = await tester.run_all_tests()

    if summary is None:
        sys.exit(1)

    # 保存结果到文件
    output_file = Path(__file__).parent / "test_results.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
