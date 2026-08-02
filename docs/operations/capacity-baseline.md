# 容量基线与边界

本页只记录可重复的 fake API smoke，不把本地 ASGI 结果解释为生产容量或真实模型
性能。生产压测仍需在目标 CPU/内存、网络、模型供应商和数据库规模下单独执行。

## 当前实测

命令：

```bash
python scripts/run_load_smoke.py --requests 100 --concurrency 10 \
  --output output/ci/capacity-baseline.json
```

2026-08-02 实际结果：100/100 请求完成，HTTP 200 为 100，错误率 0；fake Agent
吞吐 548.62 req/s，p50 15.84 ms，p95 25.66 ms。artifact 保存在被忽略的
`output/ci/capacity-baseline.json`，运行模式明确记录为 `fake`。

## 解释和限制

- 该脚本使用进程内 ASGI transport、fake Agent 和内存会话，不覆盖 Docker 网络、
  PostgreSQL/Qdrant 查询、OTLP、真实模型 token、限额或持久化写入。
- 该数字用于检测明显回归和确认请求/并发上限，不用于容量承诺、SLA 或成本估算。
- 生产上线前必须补充目标环境的固定请求集、模型/检索分层延迟、数据库与 Qdrant
  资源曲线、错误预算、持续时间和回滚阈值。
