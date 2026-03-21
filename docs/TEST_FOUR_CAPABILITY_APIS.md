# 四个能力接口测试说明

以下为四个能力接口的单独测试方式。请先启动服务：`uvicorn main:app --reload --port 8000`。  
若刚修改过 `routers/capability_api.py`，请**重启服务**后再测，否则可能仍走旧逻辑（不返回 `need_clarification` 或未做澄清判断）。

## 1. 内容方向榜单

- **缺参（应返回 need_clarification + message）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/content-direction-ranking"
  ```
  预期：`"need_clarification": true`，且带 `message` 引导用户补充平台、品牌/行业。

- **带参（应返回定制数据）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/content-direction-ranking?platform=xiaohongshu&industry=美妆"
  ```
  预期：`"need_clarification": false`，`data.items` 为内容方向列表。

---

## 2. 案例库

- **缺参（应返回 need_clarification）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/case-library"
  ```

- **带参（应返回案例列表）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/case-library?industry=教育&page=1&page_size=5"
  ```

---

## 3. 内容定位矩阵

- **缺参（应返回 need_clarification）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/content-positioning-matrix"
  ```

- **带参（应返回矩阵与人设）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/content-positioning-matrix?industry=教育&brand_name=测试品牌"
  ```

---

## 4. 每周决策快照

- **缺参（应返回 need_clarification）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/weekly-decision-snapshot"
  ```

- **带参（需 user_id 或品牌/行业，可能较慢：会跑诊断+定位）**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/capabilities/weekly-decision-snapshot?user_id=test_user"
  ```

---

## 使用脚本批量测

```bash
# 仅测缺参时的澄清响应（快，不调 LLM/插件）
python scripts/test_four_capability_apis.py --quick

# 全量测试（含带参请求，可能因插件/LLM 较慢而超时）
python scripts/test_four_capability_apis.py
```

可通过环境变量指定服务地址：`BASE_URL=http://127.0.0.1:8000 python scripts/test_four_capability_apis.py --quick`。
