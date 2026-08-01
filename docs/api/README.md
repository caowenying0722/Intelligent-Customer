# FastAPI 服务边界

当前阶段先提供不依赖真实模型、Chroma 或网络资源的应用工厂：

```python
from src.app.main import create_app

app = create_app()
```

本地启动入口：

```text
python -m src.app.server
```

应用生命周期支持注入可关闭资源；退出时按逆序调用 `close()` 或 `aclose()`，默认应用不创建外部资源。

配置数据库的文档入库服务会先停止接收新任务、取消尚未开始的任务并等待运行中的 worker 写入终态，再释放 SQLAlchemy engine，避免后台线程与 SQLite/PostgreSQL 资源关闭竞争。入库 operation 仍必须对外部调用设置独立 timeout，避免优雅关闭被不可控的外部调用拖住。

当 `create_app(chat_agent=...)` 且设置 `DATABASE_URL` 时，应用工厂会创建 SQLAlchemy repository、将数据库连接和 Alembic 当前 revision 作为 readiness 检查，并在 lifespan 结束时释放 engine；未设置时使用可测试的内存 repository。数据库表必须先由 Alembic migration 创建。

数据库连接池默认 `pool_size=5`、`max_overflow=10`、池等待 30 秒、连接超时 10 秒、事务隔离 `READ COMMITTED`；这些值由 Settings 校验，SQLite 不套用 PostgreSQL 专用池参数。

API 集成测试会先执行 Alembic upgrade，再用两个独立 app 实例验证会话重启恢复；默认 CI 仍使用本地 SQLite，不需要启动付费或外部服务。

健康检查：

- `GET /health/live`：只确认进程可响应，不访问昂贵依赖。
- `GET /health/ready`：执行注入的 readiness 检查；失败返回 `503` 和 `{"status":"not_ready"}`。

所有响应写入 `x-request-id`。客户端可传入该请求头，否则由服务生成 UUID。模型、向量库和会话依赖不会在模块导入或默认应用工厂中构造。

API access logger 输出 JSON 事件，仅含 method、status_code、duration_ms、request_id 和 trace_id；请求头、query、prompt、正文和供应商原始响应不会写入访问日志，超长或非法 request ID 只记录为 `invalid`。

错误响应统一为 `{"code": "...", "message": "...", "request_id": "..."}`；422、HTTP 异常和未处理异常都不会返回堆栈或供应商原始内容。

当前聊天边界：

- `POST /api/v1/chat` 接收严格的 `{"message": "...", "conversation_id": "...", "expected_version": 0}` schema；省略 ID 会创建新的内存会话。
- `ChatApplicationService` 通过注入的 Agent 执行，并用 `asyncio.wait_for` 设置服务级 timeout。
- 非流式 Chat 会从当前 tenant 的 conversation repository 读取最近最多 20 条、总计最多 8000 字符的历史；实现 `run_with_history(message, history)` 的 Agent 会收到结构化历史，ModelGateway 会把同样的有界上下文纳入请求/缓存键。旧的单消息 Agent 保持兼容但不会自动获得历史；SSE 历史上下文仍是后续目标。
- `REQUEST_TIMEOUT_SECONDS`（默认 30 秒，范围 0-600）由 Settings 校验，并用于 `create_app(chat_agent=...)` 自动构造的 Chat 服务；显式注入 `chat_service` 时由调用方决定 timeout。
- 同步 Agent 的 timeout 只终止请求等待，不强制杀死底层线程；外部调用必须自行设置 timeout。异步 Agent/SSE runner 收到客户端取消时传播 `CancelledError`，不会映射成 `chat_failed`。
- Agent 异常只映射为稳定的 `chat_failed`/`chat_timeout` 错误，不返回堆栈或供应商原始响应。
- 默认应用未注入 Agent 时返回 `503 chat_unavailable`。
- 当前会话 repository 默认是线程安全的进程内实现；设置 `DATABASE_URL` 后可切换 SQLAlchemy/Alembic repository，并由 readiness/lifespan 管理连接和重启恢复。
- 可注入原生异步 Agent runner；任务取消会原样传播，不会被转换成 `chat_failed`。同步 Agent 仍通过受控线程兼容，底层调用本身可能无法强制中止。
- `POST /api/v1/chat/stream` 返回 `text/event-stream`，事件顺序为 `metadata`、零个或多个 `token`、最多一个 `completed`；失败使用 `error` envelope。
- SSE 生成器在 metadata 或 token 之间检查客户端断开；断开后直接结束，不补发 completed/error。该路径有真实 APIRoute body-iterator 回归测试；底层同步模型线程仍只能靠 provider 自身 timeout 停止。
- `GET /api/v1/conversations/{conversation_id}` 返回当前进程内会话消息；不存在时返回 `404 conversation_not_found`。
- 会话响应包含单调递增的 `version`；写入方可用 expected version 检测过期状态，避免静默覆盖。
- stale `expected_version` 返回 `409 conversation_conflict`，客户端应重新读取会话后重试。
- 未配置 authenticator 的开发模式从 `x-tenant-id` 读取租户上下文，默认仅用于本地开发的 `local`；配置 JWT 后 tenant 由 token 提供，若请求头存在则必须与 token 一致。
- `x-user-id` 记录会话归属，默认本地开发用户为 `local`；`agent_runs` 表为后续 Agent 执行审计预留 tenant/conversation/status 字段。
- Agent run API：`POST /api/v1/conversations/{id}/runs` 创建 queued run，`PATCH /api/v1/runs/{id}` 更新状态，`GET /api/v1/runs/{id}` 查询；所有路径按 tenant 隔离。
- run 状态跃迁受限为 `queued→running→completed/failed/cancelled`；终态不可回退，非法跃迁返回 `409 run_state_conflict`。
- `GET /api/v1/runs` 支持 `status`、`created_after`、`created_before`、`limit`（1-100）和 `offset` 分页，并始终按 tenant 过滤和创建时间倒序返回。
- run 查询返回 `created_at/started_at/completed_at/duration_ms`，用于审计执行耗时；未开始的 queued run 的耗时为 null。
- 非流式 Chat 响应返回 `run_id`；执行自动记录 queued/running/completed 或 failed/cancelled，失败原因保存在 run 记录中。
- `Idempotency-Key`（或请求体 `idempotency_key`）按 tenant 去重；重复提交返回 `409 idempotency_reused` 和原 run ID。

文档上传先校验并原子落盘，再创建有界入库 job；同 tenant 内容 hash 去重，持久化 rebuild job 命中同一 tenant/idempotency key 时复用已有 job，不重复调用 operation。该保护仍是 at-least-once，不宣称跨进程 exactly-once；真实 parser/embedding/index operation 仍必须自行设计可重入副作用。删除正在处理的文档后，worker 完成不会将其恢复为 `active`。

配置 authenticator 后，认证成功、无效 token、租户范围不匹配和角色拒绝会写入结构化安全审计事件；事件只保留固定原因、tenant 和 actor hash，不记录 token、subject 原文或请求正文。

完整 PostgreSQL/Redis/Celery/Qdrant 生产部署、人工审批和 exactly-once 业务副作用控制仍是后续独立目标。
