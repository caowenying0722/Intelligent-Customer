# 依赖安全门禁记录

## 最近一次实测

命令：

```bash
python -m pip_audit -r requirements.txt --format json --output output/pip-audit.json
```

结果：失败，发现 3 个无可用修复版本的漏洞：

- `chromadb==1.3.7`：`CVE-2026-45829`，远程 API 在启用不安全远程模型代码执行参数时存在代码注入风险；
- `ragas==0.4.3`：`CVE-2026-6587`，多模态 faithfulness 工具链存在 SSRF 风险；
- `diskcache==5.6.3`：`CVE-2025-69872`，默认 pickle 序列化在攻击者可写缓存目录时可能导致代码执行。

仓库不使用 pip-audit ignore 规则掩盖结果，因此该门禁仍是发布 Blocker。当前补偿控制是：Chroma 仅允许本地 embedded 模式、未启用远程模型代码执行；RAGAS 默认关闭且外部评审必须显式确认；DiskCache 不在当前 Model Gateway 默认路径中使用。补偿控制不能替代升级或替换依赖。

`python -m pip check` 已通过；本机 `scripts/check_environment.py` 仅因解释器为 Python 3.13 而失败，仓库支持矩阵固定 Python 3.10。远端 CI 使用 Python 3.10，不能用本机 3.13 结果替代 CI 验收。

## 版本复核（2026-08-02）

已实际执行 `python -m pip index versions chromadb`、`ragas` 和 `diskcache`：

- ChromaDB 最新可见版本为 `1.5.9`，但当前 `CVE-2026-45829` advisory 覆盖 `1.0.0` 及以上，pip-audit 没有 fix version；仅升级到 1.5.9 不能证明风险解除。
- RAGAS 最新可见版本仍为 `0.4.3`，`CVE-2026-6587` 没有可用升级版本。
- DiskCache 最新可见版本仍为 `5.6.3`，`CVE-2025-69872` 没有可用升级版本。

因此本轮没有修改锁文件或添加 pip-audit ignore。继续使用本地 embedded Chroma、关闭默认 RAGAS 外发评测、避免默认 DiskCache 路径，并把这三条漏洞保持为发布 Blocker；待上游修复或替换方案出现后再建立独立升级目标。
