# 检索重排的评测泄漏边界

`LightweightEvidenceReranker` 只使用 query、文档正文和原始检索排名计算确定性分数。来源文件名、路径和 `expected_sources` 不参与相关性分数、来源多样性选择或重复文档判定；重复判定只使用正文和稳定文档身份字段。

评测阶段仍可以读取 `expected_sources` 计算离线 `source_recall`，因为那是结果标签而不是检索输入。该指标不能证明模型理解了来源，也不能单独作为排序质量提升结论；冻结 regression set 和无模型 deterministic smoke 用于保持可追溯基线。

真实 Cross-Encoder 适配器仍必须只接收 query 与候选文档内容，并在模型不可用时显式标记 deterministic fallback，不得把来源文件名或评测标签拼入输入。
