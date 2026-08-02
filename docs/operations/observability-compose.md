# 本地可观测性 Compose profile

基础 `compose.yaml` 默认只启动 API。需要本地 Collector 和 Prometheus 时显式启用 profile：

```text
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 docker compose --profile observability up -d
```

profile 包含：

- `otel-collector`：接收 OTLP gRPC trace，同时输出受控 `debug` 摘要和 Jaeger OTLP exporter；
- `prometheus`：抓取 API 的 `/metrics/prometheus`；
- `grafana`：挂载 provisioning/dashboard artifact，仅绑定本机 `127.0.0.1:3000`，匿名只读用于本地查看；
- `jaeger`：带 `jaeger-data` Badger 持久卷的 trace backend，查询 UI 绑定本机 `127.0.0.1:16686`。

`deploy/observability/grafana/` 同时提供 Prometheus datasource 和 API overview dashboard provisioning artifact；dashboard 的 PromQL 只引用仓库已有的有界指标。Grafana profile 是本地只读展示，不创建初始管理员、不允许注册；生产必须关闭匿名模式并接入组织认证/secret。

镜像版本固定在 Compose 文件中，首次启动仍需要拉取外部镜像；`scripts/check_observability_stack.py`
会同时检查 API、Collector、Prometheus scrape、Grafana 和 Jaeger `/api/services`，并为每个
外部调用设置 timeout。Jaeger 数据保存在 `jaeger-data`，删除该卷即丢失 trace，生产环境
应替换为受管 trace backend 或配置备份/保留策略。

该 profile 面向本地和受控预发布。API 生产环境要求 `METRICS_TOKEN`，当前 Prometheus 示例没有注入认证 header，因此生产部署必须通过受控网络、反向代理或专用 Prometheus authentication 配置保护抓取端点。生产 API 还必须配置 `JWT_SECRET`、`JWT_ISSUER` 和 `JWT_AUDIENCE`；本地 Grafana 匿名只读设置不得直接复用到公网。
