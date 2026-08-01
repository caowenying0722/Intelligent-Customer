# Schema claim 一致性审计

2026-08-02 复核了 SQLAlchemy `IngestionJobRow`、Alembic `0008→0010` 和 SQLite migration smoke：

- 最终 `ingestion_jobs.document_id` 在 `0009` 后允许为空，支持没有 document 的 index rebuild job；ORM model 与最终 schema 一致。
- `ux_ingestion_jobs_tenant_idempotency` 在 migration 和 ORM model 中都是 `(tenant_id, idempotency_key)` 唯一索引。
- `ix_ingestion_jobs_tenant_status_created` 支持 tenant/status/created 查询；document tenant/hash 也保持唯一约束。
- `tests/test_migrations.py` 现在同时检查数据库 inspector 的 `unique`、列顺序和 ORM index 定义，避免只检查索引名称。

测试数据库是 SQLite，只验证 migration artifact、唯一约束元数据和基本行为；它不能证明 PostgreSQL 的锁等待、隔离级别、并发 deadlock 或跨 worker lease fencing。生产发布仍需 PostgreSQL 容器/CI 集成测试。
