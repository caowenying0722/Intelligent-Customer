# 指标抓取

API 提供两个互补的指标接口：

- `GET /metrics`：兼容现有诊断工具的 JSON 聚合快照。
- `GET /metrics/prometheus`：Prometheus text exposition format，可直接配置为 scrape target。

Prometheus 接口只输出模型网关的聚合计数、缓存/用量聚合值和健康状态。唯一的标签是已配置的 provider 名称，并限制最多 32 个 provider series；不会输出 tenant、用户、会话、请求、prompt、文档正文或凭据。

接口不会主动探测上游模型，也不会执行重试。生产环境应通过网络策略限制指标端点的访问范围，并继续使用 `/health/ready` 判断是否接收流量。
