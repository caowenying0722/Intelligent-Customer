# API 容器本地运行

当前 Compose 基线只容器化 FastAPI API，使用 Python 3.10 slim、非 root 用户和 `/health/live` healthcheck；它不包含 PostgreSQL、Redis、Qdrant、Worker 或可观测性后端，不应被描述为完整生产编排。

校验配置：

```bash
docker compose config
```

构建并启动：

```bash
docker compose up --build -d
curl http://localhost:8000/health/live
docker compose down
```

默认 Compose 不注入模型密钥。需要真实模型时通过外部环境或 secret 管理注入，不要把 `.env` 复制进镜像。
