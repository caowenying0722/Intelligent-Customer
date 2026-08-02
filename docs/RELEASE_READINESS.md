# Release Readiness

本报告只记录当前仓库实际执行过的门禁，不把配置存在或测试通过扩大解释为生产能力证明。

## 当前结果

| 检查 | 实际结果 | 说明 |
|---|---|---|
| `python -m pytest -q --basetemp output/pytest-stage4-full` | 通过：427 passed，6 skipped，26 subtests | 当前工作区 Python 3.13 本地回归；默认不调用付费模型 |
| Python 3.10.20 锁定环境全量测试 | 待重新安装后复跑 | 当前 `ics` 环境存在历史 async-timeout/OTel 包冲突，不能冒充 clean-install 结果；锁文件已重新生成 |
| 容器集成测试 | 通过：5 passed | Python 3.10 API 镜像连接 PostgreSQL 16/Qdrant 1.18.3 |
| `python -m ruff format --check .` | 通过 | 278 个 Python 文件已格式化 |
| `python -m ruff check .` | 通过 | 全仓 lint |
| `python -m mypy agent rag model evaluation utils scripts src app.py` | 通过：113 个源码文件 | 生产源码类型门禁 |
| `python -m mypy tests` | 通过：119 个测试源码文件 | 独立测试类型门禁 |
| `python scripts/scan_secrets.py` | 通过 | 未发现疑似密钥 |
| `python -m pip check` | 通过 | 依赖元数据无破损；PyJWT 2.13.0 已显式锁定 |
| `python -m pip_audit -r requirements.txt --format json` | 通过：No known vulnerabilities found | 默认依赖已移除 ChromaDB/LangChain-Chroma/RAGAS/Datasets，DiskCache 不再被安装；可选 RAGAS 需隔离审计 |
| `python -m pip_audit -r requirements-worker.lock --format json` | 通过：No known vulnerabilities found | 可选 Celery/Redis worker lock；`pywin32` 使用 Windows marker，不进入 Linux worker image |
| `python -m pip_audit -r requirements-api.lock` | 通过：No known vulnerabilities found | 精简 API 镜像锁独立审计；不代表完整离线 RAG 依赖无漏洞 |
| `python scripts/check_environment.py --requirements requirements-dev.txt` | 当前 shell 失败；Python 3.10.20 环境通过 | 当前 shell 是 Python 3.13；受支持 `ics` 环境精确依赖检查通过 |
| GitHub Actions run `30739365944` | 通过：全量质量门禁成功 | 依赖审计、Compose/迁移、Qdrant readiness、PostgreSQL/Qdrant 集成、格式/Lint/Mypy、全量测试/覆盖率、确定性评测、质量门禁和完整依赖审计均通过；诊断发现的 `uvicorn` 缺口已修复 |
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
| JWT/RBAC/tenant boundary | 通过：定向 API 认证回归 | 生产组合根自动接入 JWT；跨租户请求 403；文档/索引/取消/run 变更需要 service_agent/admin，审批需要 approver/admin |
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
| Observability stack E2E | 通过 | API/Collector/Prometheus/Grafana/Jaeger health 均 ok；Prometheus target up；Collector debug + Jaeger exporter 收到真实 API trace，Jaeger API 可按 `intelligent-customer-service` 查询 |
| `python scripts/run_red_team_regression.py` | 通过：4/4 拒绝、0 漏检 | model_calls=0 |
| fake API load smoke | 通过：10 请求、并发 2、错误率 0 | 仅为本地 ASGI smoke，不是生产压测 |
| `python scripts/run_deterministic_regression.py --output output/ci/target73-deterministic.json` | 通过：3/3 样本，model_calls=0 | retrieval-regression-v1；recall@1=0.5、recall@3/5/10=1.0、MRR=1.0；artifact commit=`aac459e`、dirty=true |
| `python -m evaluation.quality_gate --summary output/ci/target73-deterministic.json --config config/evaluation_quality_gate.yml` | 通过 | 质量门禁实际消费 target73 artifact；不代表真实 provider 或生产质量 |
| `python scripts/run_red_team_regression.py --output output/ci/target73-red-team.json` | 通过：4/4 拒绝、0 漏检 | red-team-prompt-injection-v1；model_calls=0 |
| `python scripts/run_load_smoke.py --requests 10 --concurrency 2 --output output/ci/target73-load.json` | 通过：10 完成、0 错误 | fake 模式；error_rate=0、throughput_rps=305.25、p50=3.98ms、p95=16.11ms；仅本地 smoke，不作生产性能结论 |
| PostgreSQL backup/restore drill | 通过：60 个 dump 对象、恢复库 Alembic head `0012_add_ingestion_job_leases`、11 个 public tables | 使用临时数据库，演练后已删除；不宣称备份 SLA |
| fake capacity baseline | 通过：100 请求/并发 10、0 错误；548.62 req/s、p50 15.84 ms、p95 25.66 ms | 本地 fake ASGI smoke，不能替代生产压测 |
| Redis/Celery 真实入库与索引 | 通过 | Python 3.10 API/worker 镜像经 PostgreSQL、Redis、共享上传卷和 Qdrant 完成 document/index job；v1→v2 alias 原子切换成功，缺失候选失败时 alias 不变，`model_calls=0` |
| 多租户合成付费模型模拟 | 通过（受控本地运行） | 5 次 smoke 为 5/5、30 次批次为 29/30，均 0 泄漏；只使用合成 `.test` fixture，报告明确未测量美元成本，不代表生产质量 |

## 发布阻塞

1. 当前工作区已通过默认依赖安全门禁；可选 `requirements-ragas-lite.txt` 仍包含外发评测依赖，必须在隔离环境单独审计并获得数据出境确认。
2. 当前 shell 解释器是 Python 3.13；声明的 Python 3.10.20 环境需要清理历史包后按新锁文件重装，再复跑环境门禁。

## 已知未完成

- Compose 当前包含 PostgreSQL、migration、Qdrant、精简 API、可选 observability profile（Jaeger Badger）以及已实测的 workers profile；受管 trace backend/retention、真实语义 embedding 和容量验证仍是后续扩展。
- CI 已在依赖漏洞审计前加入 Docker build 步骤；远端 run `30732643961` 已确认镜像构建、Compose、测试和 artifact 流程成功。
- 已执行真实 Docker health、迁移、API readiness、PostgreSQL backup/restore、Redis/Celery 文档入库与蓝绿切换、Jaeger trace 查询；SSE 上游取消/背压仍未完成。
- hidden evaluation、真实 provider 评测和生产网络压测未执行。

## 结论

当前状态已具备可复现的本地容器栈、默认依赖安全门禁、备份恢复演练、可追溯 fake 容量基线、真实跨进程入库/蓝绿 worker、本地持久 trace backend 和生产 JWT/RBAC 边界，但不满足无条件生产发布。后续仍需受管 trace retention/认证、真实语义 embedding、clean Python 3.10 宿主环境及真实流量/provider 验证。
