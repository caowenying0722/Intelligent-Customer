# Trace context 传播

API 边界支持 W3C `traceparent` 的最小传播基线：请求携带合法上下文时沿用 trace ID 并生成新的服务端 span ID；缺失、格式非法或全零 ID 会生成新的 trace。服务端把新的 `traceparent` 写入响应头，并将 `trace_id`/上下文存入 `request.state`，供后续 Agent、RAG、模型和工具 instrumentation 使用。

当前实现不创建 OpenTelemetry SDK span，也不连接 Collector、Exporter 或 trace backend；因此只能证明上下文可验证、可传播，不能宣称已完成端到端追踪。任何日志接入仍必须遵循现有脱敏规则，不记录 Authorization、Cookie、prompt 或文档正文。
