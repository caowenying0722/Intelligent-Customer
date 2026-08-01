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

该命令实际通过 96 个生产源码文件；测试运行由 pytest、coverage 和行为回归负责。不能把“源码 Mypy 通过”扩大解释为“测试 Mypy 通过”。后续若要纳入测试类型门禁，应按上述类别分批收窄 mock/fixture 类型，并单独评估维护成本。
