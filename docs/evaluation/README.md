# 评测运行手册

默认 CI 只运行不调用模型和网络的 deterministic retrieval regression。

## 数据集清单

仓库的 RAG dev 集由
`data/evaluation/rag_eval_dataset.manifest.json` 描述。清单固定记录：

- `dataset_version` 和 `split`；
- 样本数与唯一 ID；
- 数据文件 SHA-256；
- 每条样本的 `metadata.category`。

修改数据文件后必须同步更新清单，并运行：

```bash
python -m evaluation.dataset_manifest
```

## 无模型回归与门禁

运行冻结 retrieval 数据集：

```bash
python scripts/run_deterministic_regression.py \
  --output output/ci/deterministic-summary.json
```

执行版本化阈值和 `require_model_free` 门禁：

```bash
python -m evaluation.quality_gate \
  --summary output/ci/deterministic-summary.json \
  --config config/evaluation_quality_gate.yml
```

报告会保存 Git commit/dirty state、dataset version/path/SHA-256、样本完整性、Recall/MRR/NDCG 和 `model_calls=0`。阈值是当前 deterministic baseline 的工程门槛，不代表生产质量或真实模型效果。

本地代理指标将引用拆成三层：`answer_citation_coverage` 统计回答句子是否带引用，`answer_citation_validity` 只检查编号是否落在候选文档范围内，`answer_citation_support` 用 query-independent 的词元重合估计引用句与对应文档是否有证据交集。最后一项是 deterministic lexical support proxy，不是 entailment、LLM-as-a-judge 或人工事实标签；错误引用样本由 `tests/test_citation_metrics.py` 覆盖。

每条评测样本还记录 `duration_ms` 和受限的 `error_type`（`timeout`、`upstream`、`invalid_output`、`unknown`）；summary 汇总错误数量和类别，不保存异常正文。单条样本失败会保留空 metrics 并继续生成报告，版本化 quality gate 通过 `require_no_errors: true` 把非零 `error_count` 拒绝为不可采信结果。

评测 artifact 默认使用 `artifact_profile: redacted`：`samples.jsonl` 和 `metrics.csv` 不写问题、回答、参考答案、上下文、来源路径或原始 metadata，只保留样本 ID、指标、耗时和错误类别。需要本地受控调试时显式传 `--artifact-profile full`；不得把 full artifact 提交或上传。

## Red-team 安全回归

Prompt Injection 数据集位于 `data/evaluation/red_team/`，由 manifest 固定版本和 SHA-256。执行：

```bash
python scripts/run_red_team_regression.py \
  --output output/ci/red-team-summary.json
```

该回归只调用确定性的 `PromptSafetyPolicy`，要求每个高风险样本都得到固定拒绝，任何漏检或无效样本都会返回非零退出码；它不替代真实模型的安全评测。

## 本地 RAG 评测与 RAGAS

`python scripts/evaluate_rag.py --no-generate --no-ragas` 可运行本地代理指标；这些指标必须标注为 proxy，不能命名为事实正确率。RAGAS 会把问题、回答、参考答案或检索上下文发送到配置的外部评审模型，只有显式确认外发和凭证存在时才允许运行；它不属于默认 CI 门禁。
