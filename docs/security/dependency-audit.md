# 依赖安全门禁记录

## 最近一次实测

命令：

```bash
python -m pip_audit -r requirements.txt --format json --output output/pip-audit.json
```

旧基线结果：失败，发现 3 个无可用修复版本的漏洞：

- `chromadb==1.3.7`：`CVE-2026-45829`，远程 API 在启用不安全远程模型代码执行参数时存在代码注入风险；
- `ragas==0.4.3`：`CVE-2026-6587`，多模态 faithfulness 工具链存在 SSRF 风险；
- `diskcache==5.6.3`：`CVE-2025-69872`，默认 pickle 序列化在攻击者可写缓存目录时可能导致代码执行。

该结果促成了本轮替换：默认运行依赖移除 ChromaDB/LangChain-Chroma、RAGAS/Datasets，随之不再安装 DiskCache；本地 baseline 改为标准库 SQLite，生产检索继续使用 Qdrant。仓库仍不使用 pip-audit ignore 规则掩盖结果。

`python -m pip check` 已通过；本机 `scripts/check_environment.py` 仅因解释器为 Python 3.13 而失败，仓库支持矩阵固定 Python 3.10。远端 CI 使用 Python 3.10，不能用本机 3.13 结果替代 CI 验收。

## 版本复核（2026-08-02）

已实际执行 `python -m pip index versions chromadb`、`ragas` 和 `diskcache`：

- ChromaDB 最新可见版本为 `1.5.9`，但当前 `CVE-2026-45829` advisory 覆盖 `1.0.0` 及以上，pip-audit 没有 fix version；仅升级到 1.5.9 不能证明风险解除。
- RAGAS 最新可见版本仍为 `0.4.3`，`CVE-2026-6587` 没有可用升级版本。
- DiskCache 最新可见版本仍为 `5.6.3`，`CVE-2025-69872` 没有可用升级版本。

本轮已修改默认依赖与锁文件，并增加 SQLite baseline 回归。RAGAS 仍可通过隔离的
`requirements-ragas-lite.txt` 显式安装，但不属于默认运行环境；启用前必须完成
数据出境审批和单独依赖审计。

另外，本轮审计发现认证代码直接依赖 PyJWT，但此前只存在于开发机间接环境；已将无当前已知漏洞的 `PyJWT==2.13.0` 显式加入 runtime/dev lock，避免 clean install 缺包。

## 本轮替换验收（2026-08-02）

实际执行：

```bash
python -m pip_audit -r requirements.txt --format json --output output/ci/current-pip-audit-after-vector.json
```

实际结果：命令返回 0，`No known vulnerabilities found`。输出中的默认依赖集合不再包含
上述三个漏洞包；可选 RAGAS 文件仍作为独立外发评测风险管理，不被默认 CI 安装。
