# PostgreSQL 备份与恢复

仓库现在提供 `scripts/postgres_backup.py` 的受控 dump/verify/restore 边界。
它不负责对象存储、加密密钥或保留策略；这些仍由部署平台提供。密码通过
`PGPASSWORD` 传给 PostgreSQL 客户端，不进入命令行、日志或错误消息。
未配置 `DATABASE_URL` 时，应用仍可能使用内存会话；这类内存会话不构成备份对象。

## 创建和验证归档

```bash
python scripts/postgres_backup.py dump \
  --database-url "$DATABASE_URL" \
  --output output/backup/intelligent-customer.dump \
  --timeout 300
python scripts/postgres_backup.py verify \
  --backup output/backup/intelligent-customer.dump
```

归档使用 PostgreSQL custom format，并带 `--no-owner --no-privileges`，便于在
隔离目标恢复。输出目录不应提交 Git，应由加密对象存储和访问控制接管。

## 恢复演练

默认恢复不清理目标对象，适合空的临时数据库；只有明确指定
`--allow-destructive-restore` 才会传递 `--clean --if-exists`：

```bash
python scripts/postgres_backup.py restore \
  --database-url "$ISOLATED_DATABASE_URL" \
  --backup output/backup/intelligent-customer.dump
```

恢复后必须按顺序执行 `alembic upgrade head`、`GET /health/ready`、API 跨实例
会话/checkpoint 查询和租户隔离 smoke。恢复失败时保留旧实例，不切换 active 数据库。

工具对 `pg_dump`/`pg_restore` 设置统一 wall-clock timeout；超时会返回安全错误并
清理未完成 dump。它不把一次本地演练扩大为备份 SLA、RPO/RTO 或生产容量证明。
