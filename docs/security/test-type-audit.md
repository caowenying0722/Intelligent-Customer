# 测试类型门禁审计

2026-08-02 实际执行：

```bash
python -m mypy tests
```

结果：失败，44 个诊断，分布在 19 个测试文件。主要类别是：

- `threading.Event.set()`、`list.append()`、`time.sleep()` 被 lambda mock 直接返回，Mypy 报 `func-returns-value`；
- worker/repository 查询返回 `Optional`，测试没有在每个断言前收窄；
- `FakeModel`、`ModelRequest` 和 RRF `key_fn` 的测试替身与生产 Protocol/schema 不一致；
- 动态字典和测试夹具的 `object` 类型没有显式收窄。

当前 CI 的源码门禁仍执行：

```bash
python -m mypy agent rag model evaluation utils scripts src/app app.py
```

该命令实际通过 96 个生产源码文件；测试运行由 pytest、coverage 和行为回归负责。不能把“源码 Mypy 通过”扩大解释为“测试 Mypy 通过”。

目标 67 已完成第一批低风险收窄：将模型 gateway/cache/quota/idempotency 测试中 `list.append(...) or result` 的 lambda 替换为有明确返回值的 fake provider。相关行为测试通过，`python -m mypy tests` 的诊断从 44 项降至 33 项、分布在 14 个文件；剩余主要是 ingestion Optional、Event/sleep callback、schema/Protocol 和 RRF key 类型。当前仍不把测试目录纳入 CI 类型门禁，后续继续分批收窄并单独评估维护成本。
