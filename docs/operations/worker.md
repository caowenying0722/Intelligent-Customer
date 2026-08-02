# Redis/Celery Worker 运维边界

默认 Compose 不启动 Redis 或 Celery，API 继续使用已有的有界进程内 worker。需要
跨进程消费时显式启用 `workers` profile：

```bash
docker compose --profile workers up -d --build
docker compose --profile workers ps
```

该 profile 包含 Redis 7.4 AOF 和独立 Python 3.10 worker。Worker 使用 JSON 序列化、
`acks_late`、`reject_on_worker_lost`、单预取、软/硬任务超时和有限重试；任务消息只
携带 `job_id`、`tenant_id`、幂等键、task type、版本化 payload 和 max attempts，不携带
文件正文、Prompt、凭证或模型响应。

任务执行先在 PostgreSQL 中按 job ID 精确 claim，再用 lease token/fence version 完成
或释放；重复投递不会跨租户取错任务。Redis 发布发生在持久化 job 提交之后；发布失败
保留 queued 记录，可由 worker 启动 sweep 或运维重试。交付语义仍为 at-least-once，
不宣称 exactly-once。

当前 worker 镜像只提供安全的任务注册边界。解析、embedding、蓝绿索引等业务 handler
必须在部署组合根显式注册；未注册 task type 会记录安全错误并失败关闭，不会执行任意
payload。真实 handler 接入前，不得把 profile smoke 当作完整入库能力或生产容量证明。

停止和回滚：

```bash
docker compose --profile workers stop worker redis
docker compose --profile workers down
```

不要直接删除 `redis-data` 或 PostgreSQL job 表；先确认 queued/running 状态并按
`docs/operations/backup-restore.md` 做数据库备份。
