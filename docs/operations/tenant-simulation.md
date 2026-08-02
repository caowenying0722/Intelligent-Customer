# 多租户合成数据与付费模型模拟

## 目的

`scripts/run_tenant_simulation.py` 用确定性合成租户、知识文档和问题，验证租户过滤、
模型调用边界、延迟、错误和跨租户泄漏。所有 fixture 只使用 `tenant-XXX`、`.test` 邮箱、
合成 marker 和固定 seed，不读取真实客户数据。

默认是 dry-run，不触网：

```powershell
python scripts/run_tenant_simulation.py --output output/tenant-simulation/dry-run.json
```

## 付费模型运行

只有显式加 `--live` 才会读取当前 `.env` 的 Anthropic-compatible 配置。凭证只在进程内
传给 provider，不打印、不写报告、不进入 Git。建议先做小 smoke：

```powershell
python scripts/run_tenant_simulation.py `
  --live --tenants 1 --documents-per-tenant 5 --queries-per-tenant 5 `
  --max-calls 5 --max-workers 1 --max-retries 0 --max-output-tokens 128 `
  --output output/tenant-simulation/live-smoke.json
```

扩大批次示例：

```powershell
python scripts/run_tenant_simulation.py `
  --live --tenants 3 --documents-per-tenant 8 --queries-per-tenant 10 `
  --max-calls 30 --max-workers 4 --max-retries 0 --max-output-tokens 128 `
  --output output/tenant-simulation/live-30.json
```

所有调用均有总调用上限、并发上限、单次 timeout、有限 retry 和输出 token 上限。报告默认
只保存 query/prompt hash、租户 ID、检索文档 ID、状态、延迟、字符数、通过/泄漏结果；
`--include-responses` 只适用于本地合成数据诊断，不应在生产数据上使用。

## 指标解释

- `passed` 是合成答案词的确定性词项匹配，不是人工事实性或 RAGAS entailment。
- `leakage` 检查回复是否出现其他合成租户 ID/marker；`0` 只说明本次样本未观察到泄漏。
- `p50_latency_ms` / `p95_latency_ms` 来自实际 provider 调用。
- 兼容适配器当前不暴露 provider usage token，因此 `cost_measured=false`；美元成本必须
  以 provider 控制台账单为准，不得从本报告推算或编造。
- 报告写入 `output/`，该目录被 Git 忽略；提交前应检查报告没有被复制到文档或日志。

## 已验证批次

2026-08-02 使用 `.env` Anthropic-compatible 配置完成：

- 5 次 live smoke：5/5 通过，0 泄漏，P50 约 3295ms，P95 约 3551ms。
- 30 次 live 批次：30 次调用、29/30 通过、0 泄漏、0 provider error，P50 约 3353ms，
  P95 约 8753ms；单个失败样本保留在本地脱敏报告中，不被宣称为 100% 质量。

这些结果只代表当前合成 fixture、当前模型配置和当前时间窗口，不代表生产质量、SLA 或
真实客户数据安全认证。
