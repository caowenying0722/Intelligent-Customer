# 事故处置手册

## API 无响应

1. 先检查 `GET /health/live`；它只证明进程可响应。
2. 再检查 `GET /health/ready`；失败表示注入的 readiness 检查未通过。
3. 保存 `x-request-id`、容器日志和最近一次 release tag，不要收集 Authorization、Cookie 或模型密钥。
4. 如果仅本地 API 容器异常，执行 `docker compose restart api`；无法恢复时停止服务并回滚到上一个已验证 tag。

## 认证或租户越权告警

1. 保存 request ID、租户哈希和审计事件类型，不保存 Authorization、Cookie、JWT 原文或请求正文。
2. 先确认生产 `JWT_SECRET`、issuer、audience 配置一致；轮换密钥时按租户/客户端窗口执行，
   不把新密钥写入仓库或日志。
3. `customer` 只能访问自身租户的读取/聊天边界；文档、索引、取消和 run 状态变更需要
   `service_agent` 或 `admin`，审批决策需要 `approver` 或 `admin`。
4. 发现跨租户 200 响应时立即停止写操作，保留 PostgreSQL 备份和审计记录，回滚到最近中文 tag。

## 模型或外部依赖异常

- 不在请求进程中手工重试付费调用；Model Gateway 已有 timeout/retry/circuit 边界。
- 默认 deterministic smoke 不依赖外部模型；先运行测试和 health，再决定是否启用 live provider。
- 默认运行依赖已移除 Chroma/RAGAS/DiskCache；RAGAS 只能从隔离的可选依赖文件显式启用，
  并需要数据出境确认。若发现旧 Chroma 数据目录，不要直接挂载到生产进程，按 ADR-0002
  的隔离导出和重新 embedding 流程迁移。

## 发布回滚

回滚代码版本和容器镜像到同一中文阶段 tag；不要删除数据库 tenant 字段或迁移历史。数据库
恢复使用 `scripts/postgres_backup.py` 的 verify 后再执行，默认不会执行 destructive restore。
