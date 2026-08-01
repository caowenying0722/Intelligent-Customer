# Trace context 传播

API 边界支持 W3C `traceparent` 的最小传播基线：请求携带合法上下文时沿用 trace ID 并生成新的服务端 span ID；缺失、格式非法或全零 ID 会生成新的 trace。服务端把新的 `traceparent` 写入响应头，并将 `trace_id`/上下文存入 `request.state`，供后续 Agent、RAG、模型和工具 instrumentation 使用。

当前实现已创建 API `http.request`、应用服务 `agent.run`/`agent.stream`、Gateway `llm.generate`、RAG `retrieval.dense`/`retrieval.rerank`、工具 `tool.*` 和当前进程 Worker `worker.ingestion` OpenTelemetry SDK span，并写入有界内存 exporter 供本地诊断测试；exporter 只保留 span 名称和 ID，不保留属性。提交到进程内线程池的任务会捕获 parent context；服务重启后恢复的持久化任务没有原始 context，会从新的 root span 开始。它仍不连接 OTLP Collector 或 trace backend，因此不能宣称已完成生产全链路追踪。任何日志接入仍必须遵循现有脱敏规则，不记录 Authorization、Cookie、prompt 或文档正文。

可选配置 `OTEL_EXPORTER_OTLP_ENDPOINT` 后，API 会启用 OTLP gRPC BatchSpanProcessor；每次导出使用 `OTEL_EXPORTER_TIMEOUT_SECONDS` 上限，默认 endpoint 为空因此不会发起外部调用。endpoint 不接受凭据或 query；生产应使用 HTTPS，明文 HTTP 仅用于受控本地 Collector。
