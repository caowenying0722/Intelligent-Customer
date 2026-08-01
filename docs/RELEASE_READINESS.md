# Release Readiness

本报告只记录当前仓库实际执行过的门禁，不把配置存在或测试通过扩大解释为生产能力证明。

## 当前结果

| 检查 | 实际结果 | 说明 |
|---|---|---|
| `python -m pytest -q` | 通过：296 passed，25 subtests | 默认不调用付费模型 |
| `coverage run -m pytest -q && coverage report` | 通过：总覆盖率 58%，门槛 41% | 当前本地基线 |
| `python -m ruff format --check .` | 通过 | 207 个 Python 文件已格式化 |
| `python -m ruff check .` | 通过 | 全仓 lint |
| `python -m mypy agent rag model evaluation utils scripts src/app app.py` | 通过：94 个源码文件 | 测试动态 mock 不纳入源码类型门禁 |
| `python scripts/scan_secrets.py` | 通过 | 未发现疑似密钥 |
| `python -m pip check` | 通过 | 依赖元数据无破损 |
| `docker compose config --quiet` | 通过 | API 单服务 Compose 配置有效，镜像使用 `requirements.lock` |
| `/metrics/prometheus` 集成测试 | 通过：5 个测试 | 有界 HTTP/模型网关聚合指标，无 tenant/user/request/prompt 内容 |
| `python scripts/run_red_team_regression.py` | 通过：4/4 拒绝、0 漏检 | model_calls=0 |
| fake API load smoke | 通过：10 请求、并发 2、错误率 0 | 仅为本地 ASGI smoke，不是生产压测 |

## 发布阻塞

1. `pip-audit -r requirements.txt` 真实发现 3 个无修复版本漏洞：ChromaDB `CVE-2026-45829`、RAGAS `CVE-2026-6587`、DiskCache `CVE-2025-69872`。CI 必须继续失败，不使用 ignore。
2. `docker build --tag intelligent-customer-api:local .` 已执行，但当前 Docker Hub token 请求因网络连接失败，镜像构建未完成；不能宣称 Docker 镜像可发布。
3. 本机解释器是 Python 3.13，`scripts/check_environment.py` 按支持矩阵拒绝；远端 CI 使用 Python 3.10，仍需在 CI 上验证完整 clean install。

## 已知未完成

- Compose 目前只有 API；PostgreSQL、Redis、Qdrant、Worker、OpenTelemetry、Prometheus server、Grafana 和 trace backend 尚未纳入。API 已提供可抓取的 HTTP/模型网关 Prometheus 文本端点，但尚无 RAG/工具耗时指标。
- CI 已在依赖漏洞审计前加入 Docker build 步骤；远端 runner 的镜像构建结果仍待实际 workflow 运行确认。
- 尚未执行真实 Docker health、迁移、SSE 和后台 job 容器 smoke。
- hidden evaluation、真实 provider 评测和生产网络压测未执行。

## 结论

当前状态适合继续开发和本地验证，不满足无条件生产发布。解除发布阻塞至少需要依赖漏洞有可接受修复/替换方案、Python 3.10 clean CI 通过，以及 Docker build/health smoke 在可用网络或镜像代理环境中成功。
