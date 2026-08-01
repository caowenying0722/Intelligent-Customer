# 本地可观测性 Compose profile

基础 `compose.yaml` 默认只启动 API。需要本地 Collector 和 Prometheus 时显式启用 profile：

```text
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 docker compose --profile observability up -d
```

profile 包含：

- `otel-collector`：接收 OTLP gRPC trace，开发环境输出到 `debug` exporter；
- `prometheus`：抓取 API 的 `/metrics/prometheus`。

`deploy/observability/grafana/` 同时提供 Prometheus datasource 和 API overview dashboard provisioning artifact。当前 profile 尚未启动 Grafana 容器，避免在没有明确管理员凭据策略时引入默认账号；dashboard 的 PromQL 只引用仓库已有的有界指标。

镜像版本固定在 Compose 文件中，首次启动仍需要拉取外部镜像；本仓库未宣称当前网络下镜像已成功拉取或健康运行。执行 `docker compose --profile observability config --quiet` 可先验证静态配置。

该 profile 面向本地开发。API 生产环境要求 `METRICS_TOKEN`，当前 Prometheus 示例没有注入认证 header，因此生产部署必须通过受控网络、反向代理或专用 Prometheus authentication 配置保护抓取端点。Collector 的 `debug` exporter 也不是生产 trace backend。
