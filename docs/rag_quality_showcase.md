# 智能客服 RAG 质量工程展示稿

## 一句话定位

把原本偏 Demo 的智能客服项目升级成一个可评测、可解释、可消融对比的售后 RAG 系统。重点不是只接一个大模型，而是能证明“检索证据更准、回答更可追溯、无依据问题不乱答”。

## 魔改前的问题

- 检索只取固定 top-k，容易把相似但不相关的片段直接交给大模型。
- 回答缺少资料编号引用，无法判断结论来自哪段知识库。
- 遇到知识库外的问题时缺少守门逻辑，容易编造客服话术。
- 项目效果主要靠人工试问，缺少 baseline/improved 的量化对比。

## 魔改后的能力

- 证据重排序：先扩大候选召回，再结合问题意图、来源路由、词面覆盖和原始排名做轻量重排序。
- 证据引用：上下文统一格式化为 `【资料N】`，提示词要求关键结论绑定资料编号。
- 低置信度守门：对手机、空调、退款、医疗等域外问题返回转人工提示。
- 评测闭环：内置 28 条评测集，覆盖故障、维护、选购、扫拖和域外拒答。
- 消融报告：一键生成 baseline 与 improved 的指标差异，直接输出提升百分点。

## 当前量化结果

报告路径：`output/evaluation_ablation_bm25_proxy_latest/comparison/comparison.json`

| 指标 | Baseline | Improved | 提升 |
|---|---:|---:|---:|
| source_recall | 0.577381 | 0.678571 | +10.12 个百分点 |
| answer_keyword_accuracy | 0.796429 | 0.813775 | +1.73 个百分点 |
| answer_relevancy_proxy | 0.724886 | 0.739799 | +1.49 个百分点 |
| factual_correctness_proxy | 0.920358 | 0.925883 | +0.55 个百分点 |
| answer_citation_coverage | 0.817262 | 0.835119 | +1.79 个百分点 |
| answer_citation_validity | 1.000000 | 1.000000 | 持平 |
| low_confidence_accuracy | 1.000000 | 1.000000 | 域外问题全部命中 |

这组结果可以作为第一阶段展示：重排序让正确来源召回提升明显，并且能传导到答案关键词覆盖、相关性代理指标和引用覆盖率。

## 可放简历的表述

- 将基础智能客服 Demo 改造成可评测 RAG 质量工程系统，新增证据重排序、资料编号引用、低置信度拒答和消融评测链路。
- 构建 28 条售后客服评测集，覆盖故障排查、维护保养、选购建议、扫拖功能和域外拒答场景。
- 在相同 top-3 上下文预算下，通过 candidate-k 扩召回 + rerank，使来源召回率提升 10.12 个百分点，答案关键词准确率提升 1.73 个百分点，引用覆盖率提升 1.79 个百分点。
- 增加低置信度守门，域外问题命中率达到 100%，降低客服机器人无依据强答风险。

## 复现实验

```bash
python scripts/compare_rag_ablation.py --retriever bm25 --no-generate --answer-mode extractive --output output/evaluation_ablation_bm25_proxy_latest
python scripts/summarize_quality_report.py --comparison output/evaluation_ablation_bm25_proxy_latest/comparison/comparison.json
```

完整环境安装向量库依赖并配置模型 API 后，可运行：

```bash
python -m pip install --target .local_deps -r requirements-ragas-lite.txt
python scripts/setup_private_env.py
python scripts/preflight_ragas.py
python scripts/compare_rag_ablation.py --retriever bm25 --answer-mode extractive --run-ragas --ack-external-judge --ragas-metrics "answer_relevancy,factual_correctness(mode=f1)" --ragas-data-mode minimal --ragas-eval-mode per_sample
python scripts/run_ragas_ablation.py --ack-external-judge
```

用于产出正式 `answer_relevancy` 与 `factual_correctness(mode=f1)` 指标。
默认 `minimal` 数据模式不会发送检索上下文；如果需要评估 context precision/recall，可改用 `--ragas-data-mode full`。默认 `per_sample` 运行模式会逐条样本调用 RAGAS，避免单条网络异常导致整批报告没有正式指标。

报告摘要由 `scripts/summarize_quality_report.py` 生成。它会优先展示正式 RAGAS 指标；如果正式指标尚未产出，则明确标记 `Official RAGAS metrics: not available`，并只把 `answer_relevancy_proxy`、`factual_correctness_proxy` 作为本地代理指标展示。
