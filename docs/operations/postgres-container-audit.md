# PostgreSQL / 容器集成验收记录

## 实测命令（2026-08-02）

```text
docker info
结果：通过；Docker Desktop Engine 已恢复，数据盘位于 D 盘

docker compose up -d --force-recreate migrate api
结果：PostgreSQL healthy，migration exit 0，API healthy

GET /health/live, GET /health/ready, GET /openapi.json
结果：均为 HTTP 200

TEST_POSTGRES_URL=... python -m pytest -q tests/test_postgres_checkpoint_integration.py
结果：4 passed；覆盖 checkpoint/审批跨重启恢复和双 worker 唯一 claim
```

## 结论

Alembic migration、SQLAlchemy model/index、PostgreSQL checkpoint、审批恢复、lease/fencing 和 Compose API 已在真实 PostgreSQL 16 容器中验收。当前 migration head 为 `0012_add_ingestion_job_leases`；API 镜像使用精简 `requirements-api.lock`，不包含 Torch/Chroma/sentence-transformers。

后续里程碑仍需执行：

1. Qdrant tenant/index-version filter 与 hybrid retrieval 集成；
2. Compose observability API scrape/OTLP 端到端传输；
3. 发布环境的备份恢复、滚动升级和长时间并发验证。
