# 入库 Job claim / lease 审计

## 当前可证明的状态机

持久化 `ingestion_jobs` 使用 `(tenant_id, idempotency_key)` 唯一约束。重建 route 的顺序是：

```text
数据库插入 queued（唯一 claim）
  → 进程内 IngestionJobManager 提交同一 job_id
  → running / completed / failed / cancelled
```

如果同 tenant/idempotency key 已存在，API 直接返回持久化 job，不启动第二个 operation。进程在插入 queued 和提交本地 worker 之间崩溃时，应用启动 recovery 会重新提交 queued job；进程重启时已是 `running` 的 job 会由 `fail_orphaned_jobs()` 安全置为 failed，不会被重复执行。

## 已执行回归

```text
python -m pytest -q tests/test_ingestion_recovery.py tests/test_ingestion_api_persistence.py tests/test_ingestion_end_to_end.py tests/test_ingestion_jobs.py
14 passed
```

覆盖：queued job 重启恢复、running orphan 失败、同一持久化 idempotency key 复用、tenant 隔离、取消和 API/document/job 闭环。

## 明确限制

- 当前没有 heartbeat、lease expiry、fencing token 或跨进程 worker ownership；唯一约束只保护 job claim，不保证外部 parser/embedding/index side effect exactly-once。
- worker 在数据库连接失联后继续运行时，不能仅凭进程内状态阻止旧 worker 写回；生产部署需要数据库原子状态跃迁加租约/版本号，并为每个外部副作用提供幂等键。
- 不能把 `ThreadPoolExecutor` timeout 或 `future.cancel()` 解释为强杀同步线程；超时后的残余线程必须由可中止的 provider/client 和下一阶段的 lease fencing 处理。

因此当前结论是 at-least-once + 持久化唯一 claim + 启动恢复，不是分布式 exactly-once。
