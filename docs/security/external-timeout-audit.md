# 外部调用 timeout 审计

## 复核范围

2026-08-02 使用以下检索命令复核仓库 Python 调用点，没有把测试脚本的 timeout 误当成生产能力：

```text
rg -n "httpx\\.|requests\\.|urllib|urlopen|aiohttp|Client\\(|AsyncClient|Qdrant|grpc|invoke\\(|ainvoke\\(|timeout" --glob '*.py' .
```

结果按调用边界归类如下：

| 边界 | 实际机制 | 回归证据 |
|---|---|---|
| OpenAI-compatible 模型 | `model/factory.py` 为 sync/async httpx client 设置 `ModelRuntimeConfig.request_timeout_seconds`；Gateway 线程等待还有同值上限 | `tests/test_model_runtime_config.py`、`tests/test_model_gateway.py` |
| Anthropic-compatible 模型 | `model/anthropic_compatible.py` 的 `requests.post` 显式传 `timeout=self.timeout` | `tests/test_anthropic_compatible.py` |
| Model Gateway | semaphore acquire、provider future、重试次数和 circuit cooldown 均有边界；不对永久错误重试 | `tests/test_model_gateway.py` |
| Qdrant | client search/upsert/delete/health 调用通过 bounded future 等待，并把 timeout 传给支持该参数的 client 方法 | `tests/test_qdrant_backend.py` |
| RAG 本地加载/重排/索引重建 | 本地线程池 future 有 document-load、rerank、blue-green rebuild timeout；Chroma 当前为本地 embedded，不是远端网络调用 | `tests/test_rag_service_initialization.py`、`tests/test_reranker_adapter.py`、`tests/test_index_rebuild.py` |
| PostgreSQL | SQLAlchemy pool wait 与连接建立分别使用 `pool_timeout`/`connect_timeout`；SQLite 不套用 PostgreSQL 参数 | `tests/test_repository_factory.py` |
| OTLP trace exporter | endpoint 仅允许 http(s)，生产要求 HTTPS；gRPC exporter 使用 `otel_exporter_timeout_seconds` | `tests/test_otel_configuration.py` |
| 静态工具/天气 | 当前工具读取固定本地数据，没有隐式 HTTP 调用；如果接入真实天气 provider，必须新增显式 timeout 和独立测试 | `agent/tools/agent_tools.py`、`tests/test_tool_tracing.py` |

## 实测结果

```text
51 passed, 6 subtests passed
```

覆盖命令：

```text
python -m pytest -q tests/test_anthropic_compatible.py tests/test_model_runtime_config.py tests/test_model_gateway.py tests/test_qdrant_backend.py tests/test_otel_configuration.py tests/test_reranker_adapter.py tests/test_index_rebuild.py tests/test_repository_factory.py tests/test_rag_service_initialization.py
```

本审计没有发现需要立即补上的生产外部调用 timeout。线程池 timeout 只能停止等待，不能强杀已经运行的同步 Python/SDK 调用；调用方仍需选择可中止的 HTTP client/SDK 并在应用关闭时 drain 依赖资源。
