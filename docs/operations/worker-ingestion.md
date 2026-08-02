# Celery 文档入库与蓝绿索引运行手册

## 能力边界

生产式链路为：FastAPI 验证上传并持久化 document/job → Redis → Celery worker →
解析/清洗/去重切分 → 本地确定性 dense+sparse embedding → Qdrant 候选集合 →
显式 rebuild 任务验证候选并切换租户级 active alias。

- 默认 embedding 为 `local-hash-v1`、64 维，不调用付费模型；它用于工程验收和可复现
  baseline，不代表语义检索质量。
- 仅支持 `parser-v1`、`chunker-v1` 和 `local-hash-v1`。任务中声明其他实现会永久
  失败，不会用另一模型冒充。
- TXT 必须是 UTF-8；PDF 由锁定的 `pypdf` 解析，最多 500 页；字节、字符、路径、
  内容哈希均在 worker 再校验。
- Qdrant collection 和 alias 使用 tenant/index 的 SHA-256 短摘要命名，不暴露租户名；
  payload 仍强制保存 tenant/index，检索必须同时过滤。
- Celery 是 at-least-once。chunk point ID 由 tenant/document/version/content hash 稳定生成，
  重复投递和部分批次重跑使用 upsert 收敛，不宣称 exactly-once。

## Docker 启动

在 PowerShell 中：

```powershell
$env:INGESTION_WORKER_BACKEND = "celery"
docker compose --profile workers up -d --build redis worker api
docker compose --profile workers ps
docker compose logs --tail 100 worker
```

`uploads-data` named volume 在 API 和 worker 之间共享。一次性的 `upload-init` 仅负责把
该卷交给镜像内非 root `app` 用户；API 和 worker 本身继续以非 root 运行。

不使用 Docker 时，`INGESTION_WORKER_BACKEND=local` 仍可在开发进程中执行同一业务
operation；这保留开发兼容性，但不提供进程隔离、worker lost 重投或跨进程容量扩展，
不能作为生产式异步验收。

## API 顺序

1. `POST /api/v1/documents`，必须提供 tenant 和 idempotency key。
2. 轮询 `GET /api/v1/jobs/{job_id}`，等待 document ingestion `completed`。
3. 同一 index version 的文档全部就绪后，调用 `POST /api/v1/indexes/rebuild`。
4. 轮询 rebuild job。只有候选集合存在且 point count 大于零才切换 alias。

候选验证失败不会修改 active alias；切换异常时协调器尝试恢复已知 previous collection。
当前 cleanup policy 保留为显式运维动作，不会在切换后自动删除旧集合。

## 故障判定

- 连接失败、超时、HTTP 429 和 5xx：可重试，指数退避上限 300 秒，并按 job ID 加稳定
  jitter。
- 格式、内容哈希、处理版本、鉴权类 4xx 和候选验证错误：永久失败。
- job error 只保存安全错误类别，不保存供应商响应正文或文档内容。
- 任务 soft/hard time limit、应用 cooperative timeout、lease/fencing 和最大尝试次数均有
  显式上限；同步库调用在 Python 中无法安全强杀，最终由 Celery hard limit 终止进程。

## 回滚

代码可回滚到上一中文 tag。运行时不要删除旧 collection：将租户 alias 原子指回已知
previous collection 即可恢复检索；随后停用 `workers` profile，并将
`INGESTION_WORKER_BACKEND` 设回 `local`。PostgreSQL job/document 记录和上传卷不应在
回滚时删除。
