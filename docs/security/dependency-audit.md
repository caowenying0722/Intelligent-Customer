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
