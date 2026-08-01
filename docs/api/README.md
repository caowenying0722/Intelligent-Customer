# FastAPI 服务边界

当前阶段先提供不依赖真实模型、Chroma 或网络资源的应用工厂：

```python
from src.app.main import create_app

app = create_app()
```

健康检查：

- `GET /health/live`：只确认进程可响应，不访问昂贵依赖。
- `GET /health/ready`：执行注入的 readiness 检查；失败返回 `503` 和 `{"status":"not_ready"}`。

所有响应写入 `x-request-id`。客户端可传入该请求头，否则由服务生成 UUID。模型、向量库和会话依赖不会在模块导入或默认应用工厂中构造。

当前聊天边界：

- `POST /api/v1/chat` 接收严格的 `{"message": "..."}` schema。
- `ChatApplicationService` 通过注入的 Agent 执行，并用 `asyncio.wait_for` 设置服务级 timeout。
- Agent 异常只映射为稳定的 `chat_failed`/`chat_timeout` 错误，不返回堆栈或供应商原始响应。
- 默认应用未注入 Agent 时返回 `503 chat_unavailable`。
- `POST /api/v1/chat/stream` 返回 `text/event-stream`，事件顺序为 `metadata`、零个或多个 `token`、最多一个 `completed`；失败使用 `error` envelope。

SSE、取消传播和持久化会话将在后续独立目标中加入。
