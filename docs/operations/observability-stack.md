# 可观测性栈验收

启动命令：

```powershell
$env:OTEL_EXPORTER_OTLP_ENDPOINT='http://otel-collector:4317'
docker compose --profile observability up -d
python scripts/check_observability_stack.py
```

2026-08-02 实测结果：API、Collector、Prometheus、Grafana 和 Jaeger 均返回 `ok`；Prometheus `api:8000/metrics/prometheus` target 为 `up` 且 `lastError` 为空；Collector debug + Jaeger exporter 在触发 API 请求后记录 `Traces` batches，Jaeger `/api/traces?service=intelligent-customer-service` 可查询到真实 span。该检查不调用真实模型。

Collector 官方镜像为 distroless，不包含 `wget`/`curl`/shell。Compose healthcheck 使用镜像内 `/otelcol-contrib components` 做进程镜像自检，HTTP readiness 由 `check_observability_stack.py` 对 13133 health extension 单独验证。关闭时 FastAPI lifespan 调用 tracer provider shutdown，BatchSpanProcessor 会在退出前 flush 有界队列。

当前限制：Jaeger 是本地 Badger backend，未配置生产级认证、跨节点高可用、保留策略或远端归档；Prometheus/Grafana 是本地开发配置；指标是进程内聚合，重启归零；不得把 tenant、conversation、query、document 或正文加入 Prometheus labels/trace attributes。
