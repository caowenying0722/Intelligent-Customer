# PostgreSQL / 容器集成验收记录

## 实测命令（2026-08-02）

```text
docker info
结果：超时（124 秒），Docker Desktop daemon 无响应

docker compose config --quiet
结果：通过

docker compose --profile observability config --quiet
结果：通过

python -m pytest -q tests/test_docker_config.py tests/test_migrations.py
结果：5 passed
```

## 结论

Alembic migration、SQLAlchemy model/index 声明和 Compose 静态配置可检查；当前机器无法访问 Docker daemon，因此没有执行 PostgreSQL 容器启动、真实迁移、API readiness、跨容器 job recovery 或并发锁 smoke。SQLite migration 结果不能替代 PostgreSQL 隔离/锁语义验收。

Docker Desktop 恢复后必须重新执行：

1. PostgreSQL 容器启动与 healthcheck；
2. `alembic upgrade head` 和 downgrade smoke；
3. API `DATABASE_URL` readiness、会话/文档/job 重启恢复；
4. 两个 worker 对同一 tenant/idempotency key 的 claim/lease 竞态；
5. Compose observability API scrape/OTLP 端到端传输。
