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

当 `create_app(chat_agent=...)` 且设置 `DATABASE_URL` 时，应用工厂会创建 SQLAlchemy repository 并在 lifespan 结束时释放 engine；未设置时使用可测试的内存 repository。数据库表必须先由 Alembic migration 创建。

健康检查：

- `GET /health/live`：只确认进程可响应，不访问昂贵依赖。
- `GET /health/ready`：执行注入的 readiness 检查；失败返回 `503` 和 `{"status":"not_ready"}`。

所有响应写入 `x-request-id`。客户端可传入该请求头，否则由服务生成 UUID。模型、向量库和会话依赖不会在模块导入或默认应用工厂中构造。

错误响应统一为 `{"code": "...", "message": "...", "request_id": "..."}`；422、HTTP 异常和未处理异常都不会返回堆栈或供应商原始内容。

当前聊天边界：

- `POST /api/v1/chat` 接收严格的 `{"message": "...", "conversation_id": "..."}` schema；省略 ID 会创建新的内存会话。
- `ChatApplicationService` 通过注入的 Agent 执行，并用 `asyncio.wait_for` 设置服务级 timeout。
- Agent 异常只映射为稳定的 `chat_failed`/`chat_timeout` 错误，不返回堆栈或供应商原始响应。
- 默认应用未注入 Agent 时返回 `503 chat_unavailable`。
- 当前会话 repository 是线程安全的进程内实现；服务重启会丢失数据，阶段三替换为 PostgreSQL。
- 可注入原生异步 Agent runner；任务取消会原样传播，不会被转换成 `chat_failed`。同步 Agent 仍通过受控线程兼容，底层调用本身可能无法强制中止。
- `POST /api/v1/chat/stream` 返回 `text/event-stream`，事件顺序为 `metadata`、零个或多个 `token`、最多一个 `completed`；失败使用 `error` envelope。
- `GET /api/v1/conversations/{conversation_id}` 返回当前进程内会话消息；不存在时返回 `404 conversation_not_found`。
- 会话 API 从 `x-tenant-id` 读取租户上下文，默认仅用于本地开发的 `local`；不同租户不能读取或追加彼此会话。

SSE、取消传播和持久化会话将在后续独立目标中加入。
