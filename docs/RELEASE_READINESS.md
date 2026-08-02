# Release Readiness

本报告只记录当前仓库实际执行过的门禁，不把配置存在或测试通过扩大解释为生产能力证明。

## 当前结果

| 检查 | 实际结果 | 说明 |
|---|---|---|
| `python -m pytest -q` | 通过：401 passed，6 skipped，26 subtests | 默认不调用付费模型；skip 为需显式 PostgreSQL/Qdrant URL 或新依赖的集成测试 |
| 容器集成测试 | 通过：5 passed | Python 3.10 API 镜像连接 PostgreSQL 16/Qdrant 1.18.3 |
| `python -m ruff format --check .` | 通过 | 265 个 Python 文件已格式化 |
| `python -m ruff check .` | 通过 | 全仓 lint |
| `python -m mypy agent rag model evaluation utils scripts src/app app.py` | 通过：104 个源码文件 | 生产源码类型门禁 |
| `python -m mypy tests` | 通过：116 个测试源码文件 | 独立测试类型门禁 |
| `python scripts/scan_secrets.py` | 通过 | 未发现疑似密钥 |
| `python -m pip check` | 通过 | 依赖元数据无破损；PyJWT 2.13.0 已显式锁定 |
| `python -m pip_audit -r requirements.txt` | 失败：3 个无修复漏洞 | `chromadb==1.3.7/PYSEC-2026-311`、`ragas==0.4.3/PYSEC-2026-3046`、`diskcache==5.6.3/PYSEC-2026-2447`；不使用 ignore |
| `python -m pip_audit -r requirements-api.lock` | 通过：No known vulnerabilities found | 精简 API 镜像锁独立审计；不代表完整离线 RAG 依赖无漏洞 |
| `python scripts/check_environment.py --requirements requirements-dev.txt` | 失败 | 当前解释器 Python 3.13，不符合仓库 Python 3.10 支持矩阵 |
| `docker info` | 通过 | Docker Desktop Engine 已恢复，数据盘位于 D 盘 |
| `docker compose config --quiet` | 通过 | PostgreSQL、migration、API 配置有效；API 镜像使用精简 `requirements-api.lock` |
| `docker compose --profile observability config --quiet` | 通过 | 配置有效；Collector/Prometheus/Grafana 实际容器也已完成端到端健康验收 |
| Grafana dashboard/profile config | 通过 | PromQL/datasource/只读端口静态测试通过，真实 `/api/health` 返回 database ok |
| `python -m compileall -q agent evaluation model rag scripts src app.py` | 通过 | 近期 server/RAG metrics 改动无语法导入错误 |
| `python -c "import app; ... build_server_app"` | 通过 | 普通 app import 不加载真实 Agent，server composition root 可导入 |
| Collector/Prometheus/Grafana health smoke | 通过：4 个组件均 ok | 包含 API、真实 scrape target 和 OTLP trace batch，不再只是隔离容器 smoke |
| `/metrics/prometheus` 集成测试 | 通过：8 个测试 | 有界 HTTP/模型网关聚合指标，生产 token 保护，无 tenant/user/request/prompt 内容 |
| W3C/HTTP/Agent/LLM/SSE/RAG/Tool/Worker/OTLP | 通过 | 当前进程线程池捕获 parent context；生产拒绝明文 OTLP；开发 Compose 已执行真实 Collector gRPC 传输 |
| Worker Prometheus 聚合指标 | 通过：4 个测试 | 队列/活动/等待/处理/重试/终态聚合，无 job/tenant 标签 |
| API 访问日志脱敏 | 通过：2 个测试 | 仅 method/status/duration/request_id/trace_id；不记录 Authorization/Cookie/query/prompt/正文 |
| Prompt 输出安全边界 | 通过：2 个测试 | 只允许简短进度说明，不要求输出隐藏推理、系统提示或策略细节 |
| 模型供应商错误脱敏 | 通过：2 个测试 | 错误只保留状态码/白名单 request ID；成功响应不保存 raw 正文 |
| 重排评测泄漏回归 | 通过：2 个测试 | 来源文件名不参与评分、来源多样性选择或重复判定 |
| 引用支持代理回归 | 通过：2 个测试 | 分离编号 validity 与 lexical support；不宣称 entailment 或人工事实标签 |
| Chat 历史上下文 | 通过：2 个测试 | 非流式/SSE history-aware Agent 收到同 tenant 最近消息；带 conversation_id 的 SSE 完成后写回消息 |
| Chat run 错误脱敏 | 通过：1 个测试 | Agent 异常正文不进入 `agent_runs.error` 查询结果 |
| Streamlit HTTP/SSE and local compatibility | 通过：8 个测试 | SSE 解析、会话 ID、请求超时和 local/http 配置均有 fake/纯函数回归；默认仍是进程内演示模式 |
| RAG readiness boundary | 通过：3 个测试 | 后台单飞加载状态、加载失败和 FastAPI lifespan/readiness 失败关闭；不等待未界定的启动时间 |
| API server composition root | 通过：2 个测试 | `build_server_app()` 注入 fake Agent 后可完成 API chat；entrypoint 使用该组合根，默认真实 Agent 只在显式 server 启动时构造 |
| Agent/RAG dependency injection | 通过：2 个测试 | 显式 RAG service 绑定 `rag_summarize` 工具并参与 readiness；默认全局工具兼容路径保持不变 |
| RAG retrieval metrics | 通过：2 个测试 | 固定无标签计数/候选数/空结果/失败/延迟桶，暴露 JSON 与 Prometheus；不记录 query/document/tenant |
| Agent tool middleware wiring | 通过：3 个测试 | ToolNode sync/async monitor wrapper 接线和真实 fake ToolNode 执行均验证日志参数/消息脱敏 |
| VectorStore ingestion state | 通过：2 个测试 | MD5 marker append/fsync 和有界 `DocumentLoadSummary`；跨存储原子性仍未完成 |
| Evaluation artifact privacy | 通过：1 个测试 | 默认 redacted profile 不输出问题/答案/上下文/来源路径；full 仅显式受控调试 |
| Versioned RAG guardrail | 通过：3 个测试 | `out-of-scope-v1` deterministic baseline，可注入但不宣称通用安全 |
| Chat timeout/cancellation regression | 通过：2 个测试 | fake Agent 验证同步线程超时边界和异步 SSE runner 取消传播 |
| SSE disconnect regression | 通过：1 个测试 | 真实 APIRoute body-iterator 在 metadata 后断开，不发送 token/completed/error |
| REQUEST_TIMEOUT_SECONDS wiring | 通过：1 个测试 | auto-built Chat service 读取配置并保持 504/chat_timeout contract |
| 外部调用 timeout audit | 通过：51 passed，6 subtests | 模型、Qdrant、OTLP、数据库池、RAG/重排/索引重建均有边界；静态天气无外部调用 |
| 入库删除/任务并发幂等 | 通过：1 个测试 | running operation 完成后不会把已删除文档 resurrect 为 active |
| Blue/Green validation timeout safety | 通过：1 个测试 | 未完成 candidate validation 时 active alias 保持不变 |
| 持久化 rebuild idempotency reuse | 通过：1 个测试 | 已存在 tenant/idempotency key 时复用持久化 job，不重复调用 operation |
| Persistent claim-before-worker | 通过：持久化 route 测试 | rebuild 先写唯一 job，再提交进程内 worker；进程崩溃后的 queued job 由 recovery 处理 |
| Job claim/recovery audit | 通过 | queued 恢复、取消、租户隔离、持久化幂等、heartbeat/lease/fencing 与过期 reclaim 已测试 |
| Schema claim consistency | 通过：migration + 真实 PostgreSQL | 当前 head `0012_add_ingestion_job_leases`，SQLite smoke 与 PostgreSQL 锁/并发集成均执行 |
| PostgreSQL/container integration | 通过 | PostgreSQL healthy、migration exit 0、API healthy，live/ready/OpenAPI 200；真实 checkpoint/审批重启及 `SKIP LOCKED` 双 worker claim 测试通过 |
| Qdrant hybrid integration | 通过 | Qdrant 1.18.3 healthy；真实 dense+sparse/RRF、tenant/index/version/business filter 集成测试通过；API readiness 200 |
| 五路 retrieval ablation | 通过 | baseline/dense/sparse/RRF/RRF+reranker 使用 3 条冻结样本、model_calls=0 生成本地报告；只作为 proxy，不宣称生产提升 |
| Observability stack E2E | 通过 | API/Collector/Prometheus/Grafana health 均 ok；Prometheus target up；Collector debug exporter 收到真实 API trace batches |
| `python scripts/run_red_team_regression.py` | 通过：4/4 拒绝、0 漏检 | model_calls=0 |
| fake API load smoke | 通过：10 请求、并发 2、错误率 0 | 仅为本地 ASGI smoke，不是生产压测 |
| `python scripts/run_deterministic_regression.py --output output/ci/target73-deterministic.json` | 通过：3/3 样本，model_calls=0 | retrieval-regression-v1；recall@1=0.5、recall@3/5/10=1.0、MRR=1.0；artifact commit=`aac459e`、dirty=true |
| `python -m evaluation.quality_gate --summary output/ci/target73-deterministic.json --config config/evaluation_quality_gate.yml` | 通过 | 质量门禁实际消费 target73 artifact；不代表真实 provider 或生产质量 |
| `python scripts/run_red_team_regression.py --output output/ci/target73-red-team.json` | 通过：4/4 拒绝、0 漏检 | red-team-prompt-injection-v1；model_calls=0 |
| `python scripts/run_load_smoke.py --requests 10 --concurrency 2 --output output/ci/target73-load.json` | 通过：10 完成、0 错误 | fake 模式；error_rate=0、throughput_rps=305.25、p50=3.98ms、p95=16.11ms；仅本地 smoke，不作生产性能结论 |

## 发布阻塞

1. `pip-audit -r requirements.txt` 真实发现 3 个无修复版本漏洞：ChromaDB `CVE-2026-45829`、RAGAS `CVE-2026-6587`、DiskCache `CVE-2025-69872`。本轮已复核可见最新版本仍无 fix；CI 必须继续失败，不使用 ignore。
2. 本机解释器是 Python 3.13，`scripts/check_environment.py` 按支持矩阵拒绝；精简 API 已在 Python 3.10 镜像构建和启动，完整开发依赖仍需远端 Python 3.10 CI clean install。

## 已知未完成

- Compose 当前包含 PostgreSQL、migration、Qdrant、精简 API 和可选 OpenTelemetry Collector/Prometheus/Grafana profile，health/scrape/OTLP 已实测。Redis/独立 Worker 和生产 trace backend 不在当前四里程碑闭环中，仍是后续扩展。
- CI 已在依赖漏洞审计前加入 Docker build 步骤；远端 runner 的镜像构建结果仍待实际 workflow 运行确认。
- 已执行真实 Docker health、迁移和 API readiness；SSE 与独立后台 Worker 容器 smoke 尚未完成。
- hidden evaluation、真实 provider 评测和生产网络压测未执行。

## 结论

当前状态已具备可复现的本地容器栈和发布门禁，但不满足无条件生产发布。解除发布阻塞仍需要完整依赖漏洞有可接受修复/替换方案、远端 Python 3.10 CI 实际通过，并完成生产备份恢复、容量和真实流量验证。
