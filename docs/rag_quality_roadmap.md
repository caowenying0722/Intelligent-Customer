# 智扫通 Pro 魔改路线：RAG 质量工程

## 第一阶段目标

把原始客服 Demo 升级为可评测、可解释、可消融对比的售后 RAG 系统。第一阶段聚焦三个能力：

- 扩大候选召回后进行证据重排序，减少相似但无关的片段进入生成上下文。
- 回答必须带资料编号引用，让客服答案能追溯到知识库证据。
- 增加低置信度守门，知识库证据不足时不强行编答案。

## 当前已落地

- `config/chroma.yml` 增加 `candidate_k`、`rerank_enabled`、`rerank_top_k`、`low_confidence_threshold`；默认在候选扩召回后仍只保留 3 条证据，保证 baseline 与改造版证据预算一致。
- `rag/reranker.py` 增加轻量证据重排序器，包含业务来源路由、原始排名保守保留和来源多样性选择，便于本地先做消融实验。
- `rag/rag_service.py` 支持召回后重排序、证据编号格式化和低置信度提示。
- `prompts/rag_summarize.txt` 要求答案关键结论绑定资料编号。
- `scripts/compare_rag_ablation.py` 支持一键运行 baseline 与 rerank 版本对比。
- `evaluation/comparison.py` 自动生成 `comparison.json` 和 `comparison.md`，直接展示指标提升百分点。
- BM25 评测路径也支持候选扩召回和重排序，可在缺少向量库依赖时做轻量 smoke test。
- `evaluation/extractive_answer.py` 支持不调用大模型的抽取式证据答案，用于验证检索改造是否能传导到答案关键词覆盖、引用覆盖和上下文重合指标。
- `evaluation/local_metrics.py` 增加本地 `answer_relevancy_proxy` 和 `factual_correctness_proxy`。这两个指标用于无模型评审环境下观察趋势，不替代 RAGAS 的正式 `answer_relevancy` 与 `factual_correctness(mode=f1)`。
- `rag/guardrails.py` 增加客服域外问题守门，对手机、空调、退货、医疗等非知识库问题返回低置信度转人工提示。
- `data/evaluation/rag_eval_dataset.jsonl` 已从 8 条扩展到 28 条，覆盖故障、维护、选购、拖地、耗材和域外拒答场景。

## 当前 smoke 结果

在缺少本地向量库依赖时，先使用 BM25 路径验证消融链路：

```bash
python scripts/compare_rag_ablation.py --retriever bm25 --no-generate --output output/evaluation_ablation_bm25_diverse
```

28 条样本下，使用抽取式答案验证“证据选择 -> 答案质量”的传导：

```bash
python scripts/compare_rag_ablation.py --retriever bm25 --no-generate --answer-mode extractive --output output/evaluation_ablation_bm25_proxy_latest
```

`baseline_bm25` 对比 `bm25_rerank_evidence` 的结果：

- `answer_keyword_accuracy`: 0.796429 -> 0.813775，提升 1.73 个百分点。
- `answer_relevancy_proxy`: 0.724886 -> 0.739799，提升 1.49 个百分点。
- `factual_correctness_proxy`: 0.920358 -> 0.925883，提升 0.55 个百分点。
- `answer_citation_coverage`: 0.817262 -> 0.835119，提升 1.79 个百分点。
- `answer_context_overlap`: 0.816768 -> 0.824312，提升 0.75 个百分点。
- `answer_similarity`: 0.376932 -> 0.389013，提升 1.21 个百分点。
- `source_recall`: 0.577381 -> 0.678571，提升 10.12 个百分点。
- `retrieval_mrr`: 0.839286 -> 0.857143，提升 1.79 个百分点。
- `low_confidence_accuracy`: 1.000000 -> 1.000000，域外问题守门全部命中。
- `retrieval_precision`: 0.797619 -> 0.785714，下降 1.19 个百分点。

24 条域内样本下，仅验证检索/证据选择链路时：

- `source_recall`: 0.673611 -> 0.791667，提升 11.81 个百分点。
- `retrieval_mrr`: 0.979167 -> 1.000000，提升 2.08 个百分点。
- `retrieval_recall`: 0.868056 -> 0.879960，提升 1.19 个百分点。
- `retrieval_precision`: 0.930556 -> 0.916667，下降 1.39 个百分点。

这个 smoke 结果证明检索/证据选择链路可以传导到本地答案质量代理指标。正式 `answer_relevancy`、`factual_correctness(mode=f1)` 仍建议在安装完整 hybrid 依赖、配置模型 API 后运行 RAGAS 产出。

## RAGAS 正式指标链路

当前已将 RAGAS 轻量依赖安装到项目目录 `.local_deps`，并让评测脚本自动加载该目录。若需要在新机器复现，可运行：

```bash
python -m pip install --target .local_deps -r requirements-ragas-lite.txt
```

RAGAS 默认指标已调整为：

- `answer_relevancy`
- `factual_correctness(mode=f1)`
- `context_precision`
- `context_recall`
- `faithfulness`

已执行 1 条样本 smoke：

```bash
python scripts/evaluate_rag.py --retriever bm25 --answer-mode extractive --limit 1 --run-ragas --ragas-metrics "answer_relevancy,factual_correctness(mode=f1)" --output output/evaluation_ragas_no_key_check
```

结果证明 RAGAS 能被导入并进入评测流程，但当前环境未配置评审模型 API Key，DeepSeek 接口返回 401，因此报告中记录：

```text
RAGAS returned no finite metric values. Check judge LLM API key, base URL, network access, and metric compatibility.
```

配置 `.env` 后即可继续跑正式指标：

```bash
LLM__PROVIDER=anthropic
ANTHROPIC_AUTH_TOKEN=your_anthropic_compatible_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-flash
```

注意：`.env` 中的 URL 要写纯文本，例如 `https://api.deepseek.com/anthropic`，不要写成 Markdown 链接。

正式运行前可以先做预检：

```bash
python scripts/preflight_ragas.py
```

如果不想手动编辑 `.env`，可以使用交互式初始化脚本：

```bash
python scripts/setup_private_env.py
python scripts/setup_private_env.py --from-current-env
```

脚本会通过隐藏输入读取 `ANTHROPIC_AUTH_TOKEN`，并写入本地 `.env`。`.env` 已在 `.gitignore` 中，不会进入版本库。

预检通过后，如确认可以把评测内容发送到外部评审模型，可运行正式 RAGAS 消融。默认 `minimal` 模式只为目标指标发送问题、答案和参考答案，不发送检索上下文；`full` 模式或上下文类指标才会发送检索上下文。

```bash
python scripts/run_ragas_ablation.py --ack-external-judge --ragas-data-mode minimal --ragas-eval-mode per_sample
python scripts/run_ragas_ablation.py --ack-external-judge --ragas-data-mode full --ragas-eval-mode per_sample
```

该命令会依次执行 RAGAS 预检、baseline/rerank 消融和面试版指标摘要生成。默认 `per_sample` 模式会逐条样本调用 RAGAS，单条失败只记录为局部失败，不会把整批 baseline/improved 指标全部打空。

面试版摘要会优先展示正式 `answer_relevancy` 和 `factual_correctness(mode=f1)`；如果评审模型 Key 未配置或 RAGAS 未返回有效值，则摘要会明确降级为本地 proxy 指标，避免把代理指标误当正式 RAGAS 分数。

## 建议汇报指标

- `answer_relevancy`
- `factual_correctness(mode=f1)`
- `answer_relevancy_proxy`
- `factual_correctness_proxy`
- `answer_keyword_accuracy`
- `answer_citation_coverage`
- `answer_citation_validity`
- `low_confidence_accuracy`
- `context_recall`
- `retrieval_precision`
- `source_recall`

## 实验命令

```bash
python scripts/compare_rag_ablation.py --no-generate
python scripts/compare_rag_ablation.py --run-ragas
python scripts/validate_quality_goal.py --comparison output/evaluation_ablation_bm25_proxy_latest/comparison/comparison.json
```

当前验收状态：重排序、引用、低置信度、评测集、消融对比和 `answer_keyword_accuracy` 提升已通过；正式 `answer_relevancy` 与 `factual_correctness(mode=f1)` 仍需在 `.env` 配置完成后运行 `python scripts/run_ragas_ablation.py`，并在 baseline/rerank 对比中取得正向提升。

提交或对外展示前建议运行：

```bash
python scripts/scan_secrets.py
python scripts/run_quality_pipeline.py --ack-external-judge
python scripts/validate_quality_goal.py --comparison output/evaluation_ablation_ragas/comparison/comparison.json --strict
```

`scan_secrets.py` 默认跳过本地 `.env`、`.local_deps/` 和 `output/`，用于检查源码、配置与文档中是否误写入 API Key。

没有本地向量库或 embedding 依赖时，可先跑轻量链路验证：

```bash
python scripts/compare_rag_ablation.py --retriever bm25 --no-generate
python scripts/compare_rag_ablation.py --retriever bm25 --no-generate --answer-mode extractive
```

如果只想跑单版本：

```bash
python scripts/evaluate_rag.py --disable-rerank
python scripts/evaluate_rag.py --candidate-k 8 --rerank-top-k 3
```

## 第二阶段建议

- 在完整环境中运行 `python scripts/compare_rag_ablation.py --run-ragas`，拿到 `answer_relevancy` 和 `factual_correctness(mode=f1)` 的正式提升数字。
- 将轻量重排序器替换为 `bge-reranker-v2-m3` 或同类 cross-encoder reranker。
- 扩充评测集到 80-150 条，并按故障、保养、选购、拖地、报告生成分桶统计。
- 增加工单字段：问题分类、紧急程度、是否转人工、工单摘要、建议动作。
- 在 Streamlit 页面展示证据片段、来源文件、重排序分数和低置信度原因。
