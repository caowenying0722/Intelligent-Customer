# Trace context 传播

API 边界支持 W3C `traceparent` 的最小传播基线：请求携带合法上下文时沿用 trace ID 并生成新的服务端 span ID；缺失、格式非法或全零 ID 会生成新的 trace。服务端把新的 `traceparent` 写入响应头，并将 `trace_id`/上下文存入 `request.state`，供后续 Agent、RAG、模型和工具 instrumentation 使用。

当前实现已创建 API `http.request`、应用服务 `agent.run`/`agent.stream`、Gateway `llm.generate` 和 RAG `retrieval.dense`/`retrieval.rerank` OpenTelemetry SDK span，并写入有界内存 exporter 供本地诊断测试；exporter 只保留 span 名称和 ID，不保留属性。它仍不连接 OTLP Collector 或 trace backend，工具 span 仍待接入，因此不能宣称已完成全链路追踪。任何日志接入仍必须遵循现有脱敏规则，不记录 Authorization、Cookie、prompt 或文档正文。
