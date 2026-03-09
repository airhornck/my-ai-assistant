import requests
API_URL = "http://localhost:8001/api/v1/analyze-deep/raw"

cases = [
    ("帮我生成小红书、抖音、B站的推广文案", "多平台"),
    ("帮我写一个B站视频脚本", "单脚本"),
    ("制定一个推广策略", "策略"),
]

print("测试结果:")
for msg, desc in cases:
    r = requests.post(API_URL, json={"user_id": "test", "raw_input": msg}, timeout=180)
    result = r.json()
    data = result.get('data', '')[:150]
    print(f"\n{desc}: {data[:80]}...")
