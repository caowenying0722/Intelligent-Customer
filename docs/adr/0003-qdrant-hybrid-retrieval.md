# ADR 0003：Qdrant Hybrid Retrieval 与 RRF

## 决策

保留 Chroma + 本地 BM25 作为可复现 baseline，新增 Qdrant 1.18.3 与 `qdrant-client==1.18.0` 生产 adapter。查询必须同时提供 `tenant_id` 和 `index_version`，并可附加 document version、product model、language 和 effective date 条件。Dense 与 sparse 使用命名向量，经 Qdrant Universal Query API 的参数化 RRF 融合；应用层可选 Cross-Encoder adapter 再排序。

不直接相加 dense 与 sparse 原始分数，因为两路分数尺度和分布不一致；RRF 只使用稳定排名。当前离线 sparse baseline 是仓库实现的 BM25；生产 Qdrant sparse collection 应使用带 IDF modifier 的 sparse vector 配置，向量化器作为可注入依赖管理，不能把关键词计数宣传成 BM25。

## 安全与降级

- tenant/index filter 在 backend 内强制，调用方不能关闭；返回 payload 再次核对 scope，错误结果失败关闭。
- 所有 Qdrant 调用有客户端 timeout 和应用层有界等待；readiness 失败关闭。
- Cross-Encoder 不可用时使用确定性 evidence reranker，并写入 `rerank_degraded=true`；未配置重排时写入 `rerank_applied=false`。
- Prometheus/报告不记录 query、tenant、document ID 或正文。

## 验证边界

真实 Qdrant 容器测试覆盖 dense+sparse、RRF、tenant/index 和业务 metadata filter。五路离线消融只使用 3 条冻结 retrieval regression 样本、hash-ngram dense proxy 与本地 BM25，`model_calls=0`；报告中的数值和本机延迟不能外推为生产质量或性能提升。
