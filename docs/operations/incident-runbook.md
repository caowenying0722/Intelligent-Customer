# 事故处置手册

## API 无响应

1. 先检查 `GET /health/live`；它只证明进程可响应。
2. 再检查 `GET /health/ready`；失败表示注入的 readiness 检查未通过。
3. 保存 `x-request-id`、容器日志和最近一次 release tag，不要收集 Authorization、Cookie 或模型密钥。
4. 如果仅本地 API 容器异常，执行 `docker compose restart api`；无法恢复时停止服务并回滚到上一个已验证 tag。

## 模型或外部依赖异常

- 不在请求进程中手工重试付费调用；Model Gateway 已有 timeout/retry/circuit 边界。
- 默认 deterministic smoke 不依赖外部模型；先运行测试和 health，再决定是否启用 live provider。
- Chroma/RAGAS/DiskCache 当前存在已知安全 Blocker，禁止通过 ignore 规则绕过发布门禁。

## 发布回滚

回滚代码版本和容器镜像到同一中文阶段 tag；不要删除数据库 tenant 字段或迁移历史。当前 Compose 仅包含 API，完整多服务回滚流程尚未实现。
