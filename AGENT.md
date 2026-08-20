你现在是该项目的首席后端架构师和代码审计负责人。

请在当前仓库中完成一次深入审计，并为“工程级 Agentic RAG 智能客服平台”制定可执行的分阶段改造计划。

## 核心要求

先检查真实工作区，不要根据我的描述或 README 猜测项目已经具备某项能力。

不要立即进行大规模业务重构。本任务以审计、建立基线、补充工程文档和制定计划为主。只允许修复会阻止审计和测试运行的轻微配置、路径或文档问题。

不要覆盖或回滚工作区中已有的未提交修改。

## 第一步：检查仓库现状

检查并记录：

1. 当前 Git 分支、提交状态和未提交文件。
2. 完整目录结构。
3. Python 版本和依赖管理方式。
4. 应用启动入口。
5. Agent、RAG、模型调用、工具调用、评测、测试、配置和 UI 模块。
6. 当前是否存在：

   * FastAPI；
   * PostgreSQL；
   * Redis；
   * Celery；
   * Qdrant；
   * LangGraph checkpoint；
   * 用户和会话持久化；
   * JWT/RBAC；
   * 多租户隔离；
   * OpenTelemetry；
   * Prometheus；
   * Docker Compose；
   * CI；
   * 压测；
   * RAG 回归数据集。
7. README 描述是否和实际代码一致。
8. 是否存在：

   * 硬编码本地路径；
   * 硬编码密钥；
   * 错误仓库地址；
   * 失效脚本；
   * 未使用依赖；
   * 假指标；
   * 只在内存中保存的关键状态；
   * 阻塞式 I/O 被放入异步路径；
   * 无限制 Agent 循环或重试；
   * 评价集泄漏；
   * 文件名作为相关性捷径；
   * 不能复现的评测结果。

## 第二步：运行现有项目基线

在不使用真实付费 API 的前提下，尽可能执行现有的：

* 安装或依赖检查；
* 单元测试；
* 集成测试；
* lint；
* formatter check；
* 类型检查；
* 密钥扫描；
* 本地评测；
* 应用导入或启动检查。

不要声称未执行的命令已经通过。

记录每条命令：

* 命令内容；
* 成功或失败；
* 失败原因；
* 是否属于代码问题、环境问题或缺少凭证；
* 后续解决方案。

如果仓库缺少统一命令，提出后续引入 `Makefile`、`justfile` 或脚本入口的方案，但本阶段不要大规模增加工具。

## 第三步：创建或更新工程文档

创建下列文件；若已存在，则基于真实代码更新，不要覆盖有效内容：

### `docs/CURRENT_STATE.md`

包括：

* 当前架构；
* 核心调用链；
* 已实现功能；
* 关键技术债；
* 安全风险；
* 测试现状；
* 可观测性现状；
* 部署现状；
* 数据持久化现状；
* 当前项目最可能被面试官质疑的问题。

### `docs/ARCHITECTURE.md`

同时描述：

1. 当前架构；
2. 目标架构；
3. 两者之间的迁移路径。

目标架构至少考虑：

* FastAPI API 层；
* Streamlit 薄客户端；
* LangGraph 显式状态工作流；
* PostgreSQL；
* LangGraph Postgres checkpoint；
* Redis；
* Celery；
* Qdrant hybrid retrieval；
* Cross-Encoder reranker；
* Model Gateway；
* JWT/RBAC；
* tenant isolation；
* OpenTelemetry；
* Prometheus/Grafana；
* 自动化评测和 CI；
* Docker Compose。

加入 Mermaid 架构图，但确保 Mermaid 语法有效。

### `docs/adr/0001-engineering-upgrade-strategy.md`

记录：

* 为什么不一次性重写；
* 为什么采用模块化单体而不是立即拆微服务；
* 为什么保留 Streamlit 但增加 FastAPI；
* 为什么优先建设评测、持久化和可观测性；
* 暂不引入 Kafka、GraphRAG 和复杂多智能体的理由。

### `docs/exec-plans/active/000-engineering-upgrade.md`

把改造拆成独立、可回滚、可验证的阶段：

1. 基础质量和项目规范；
2. FastAPI 服务化；
3. PostgreSQL 会话持久化；
4. LangGraph checkpoint 和人工审批；
5. Qdrant 混合检索和重排；
6. 异步文档入库；
7. Model Gateway、缓存、限流和降级；
8. 可观测性；
9. 安全和多租户；
10. 评测 CI；
11. Docker Compose、压测和发布文档。

对每个阶段写明：

* 目标；
* 涉及模块；
* 不应该修改的范围；
* 数据迁移风险；
* 测试方案；
* 验收标准；
* 回滚策略；
* 依赖阶段；
* 预期可用于面试讲解的技术点。

### `docs/TECH_DEBT.md`

用表格记录：

* 编号；
* 问题；
* 严重度；
* 影响；
* 证据文件；
* 推荐方案；
* 所属阶段；
* 当前状态。

## 第四步：输出推荐目录结构

基于现有代码给出渐进式目录迁移方案，不要假设必须一次移动所有文件。

建议目标结构可参考但不必机械照搬：

```text
src/
  app/
    api/
    application/
    domain/
    infrastructure/
    agent/
    rag/
    evaluation/
    security/
    observability/
    workers/
tests/
  unit/
  integration/
  contract/
  evaluation/
docs/
scripts/
deploy/
```

说明哪些现有模块暂时保留兼容层，哪些模块后续迁移。

## 第五步：建立可量化基线

从现有代码和评测结果中提取能够真实复现的基线：

* 测试数量和通过率；
* 评测数据集数量；
* Recall@K；
* MRR；
* source recall；
* citation validity；
* 平均响应延迟；
* p95 延迟；
* 每请求 token；
* 每请求成本。

无法获得的指标必须写为“尚未测量”，不得填写估计结果。

## 验收标准

完成前确认：

* 没有大规模改动业务逻辑；
* 文档内容对应真实代码；
* 没有编造项目已有能力；
* 没有编造测试和指标；
* 当前问题按严重度排序；
* 后续每个阶段都可以被独立执行和验收；
* `git diff` 中没有无关文件。

## 最终回复格式

最终回复必须包含：

1. 当前项目一句话评价；
2. 最严重的五个问题；
3. 已执行的命令及结果；
4. 创建或修改的文件；
5. 推荐实施顺序；
6. 第一阶段开始前的阻塞项；
7. 当前工作区是否适合继续自动修改；
8. 未解决问题和风险。

现在开始检查实际仓库并完成任务，不要只给建议。
