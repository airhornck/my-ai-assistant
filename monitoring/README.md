# 监控服务说明

## 1. 启动监控（与主应用一起）

在生产 Compose 中已包含 Prometheus 与 Grafana，与 app 同网段，按需启动：

```bash
# 在项目根目录
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

# 仅启动基础服务 + 监控（不启动 memory-optimizer 可去掉该服务）
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d app prometheus grafana
```

## 2. 访问与配置

| 服务       | 地址               | 说明 |
|------------|--------------------|------|
| Prometheus | http://localhost:9090 | 抓取 `app:8000/metrics`，可查指标与简单查询 |
| Grafana    | http://localhost:3000  | 默认账号 `admin` / 密码 `admin`，首次登录可改密码 |

- **Prometheus**：`monitoring/prometheus.yml` 中已配置抓取 `app:8000/metrics`，无需改即可用。
- **Grafana**：已通过 `monitoring/grafana/provisioning/datasources/datasource.yml` 自动添加名为 `Prometheus` 的数据源（地址 `http://prometheus:9090`），启动后即可在 Grafana 里选该数据源做图表。

## 3. 常用指标（app 暴露）

- `http_requests_total`：按 method、path 的请求总数  
- `http_request_duration_seconds`：请求耗时直方图  

在 Grafana 中新建 Panel，数据源选 Prometheus，例如：

- 请求 QPS：`rate(http_requests_total[5m])`
- 延迟 P99：`histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))`

## 4. 仅本地/开发环境跑监控

若 app 用 `uvicorn` 跑在主机（如 8000），Prometheus 在 Docker 里无法用 `app:8000`，需改成本机地址：

- 将 `monitoring/prometheus.yml` 中 `targets: ["app:8000"]` 改为 `targets: ["host.docker.internal:8000"]`（Mac/Windows）或宿主机 IP。
- 或单独起 Prometheus 于主机并配置 `localhost:8000`。
