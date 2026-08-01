# ADR 0001：工程化升级策略

- 状态：Accepted
- 日期：2026-08-01
- 决策者：仓库维护者（以本 ADR 作为当前实施基线）

## 背景

仓库当前是 Streamlit 直接调用 LangGraph Agent 的本地 Demo。RAG、模型、工具和评测已经有可复用实现，但依赖不可复现、导入存在副作用、会话仅在内存、Agent 无代码级上限，且缺少 API、持久化、安全、可观测性和 CI。`todo.md` 描述的终态跨度很大，如果同时重写 UI、Agent、数据库、向量库和部署，失败时无法判断是业务回归、框架版本、数据迁移还是基础设施问题。

## 决策

### 不一次性重写

采用“稳定接口 + 兼容 adapter + 小步替换”。先给现有 Agent/RAG 包一层可测试协议和 application service，再逐步替换 transport、repository、retriever 和 provider。

理由：

- 当前 BM25、Chroma、Prompt、工具和评测代码仍可作为行为 baseline。
- 一次重写会丢失回归参照，也无法可靠归因质量变化。
- 当前工作区已有用户未提交修改，大范围移动会增加冲突和误覆盖风险。
- 每个阶段都需要独立验收和回滚；可逆性比目录“看起来整洁”更重要。

### 采用模块化单体，而不是立即拆微服务

FastAPI、应用服务、Agent、RAG、repository、security 和 observability 先放在一个有清晰边界的代码库中。运行时允许 API 与 Celery Worker 分进程，但共享版本化协议和数据模型。

理由：

- 当前团队规模、流量和领域边界没有证据支持微服务成本。
- 会话、Agent run、工具审批和知识版本具有强一致关联，过早拆分会引入分布式事务和复杂运维。
- 模块化单体仍可通过依赖倒置、独立测试和进程边界为未来拆分保留选择。

触发重新评估的条件：明确的独立扩缩容需求、不同发布节奏、团队所有权边界或经实测确认的资源隔离瓶颈。

### 保留 Streamlit，但增加 FastAPI

Streamlit 保留为演示客户端，核心业务迁到 application service，FastAPI 成为稳定服务入口。迁移期允许 Streamlit 通过配置选择进程内兼容模式，目标默认通过 HTTP/SSE 调用 API。

理由：

- Streamlit 对作品展示和人工验证有价值，无需丢弃。
- 它不适合作为认证、会话持久化、错误契约、负载治理和多客户端集成边界。
- API-first 能让自动化测试、压测、Worker、其他前端和部署独立演进。

### 优先建设评测、持久化和可观测性

基础质量/评测先于检索算法扩展；会话持久化先于复杂 Agent；request ID 和基础日志随 API 同步建立，完整 tracing/metrics 在关键边界稳定后补全。

理由：

- 历史重排曾存在来源文件名泄漏；当前 baseline 已移除该特征，但仍需要冻结 regression set 才能证明后续 Qdrant/Cross-Encoder 改进。
- 没有持久化/checkpoint，Agent 中断、审批和服务重启恢复无法成立。
- 没有可观测性，超时、重试、fallback、检索和工具故障无法定位，也不能产生可信延迟/成本数据。

### 暂不引入 Kafka

首个异步入库实现选择 Celery + Redis，因为任务量、顺序语义、长期事件保留和多消费者需求尚未证明需要 Kafka。Kafka 会增加 broker 运维、schema 治理、消费位点和幂等复杂度。

若未来需要高吞吐事件流、可重放审计日志、多个独立消费者或跨系统事件契约，再单独 ADR 评估 Kafka。

### 暂不引入 GraphRAG

现有知识库规模和问题类型以 FAQ、故障排查、维护和选购为主；当前首先要解决的是无泄漏 baseline、tenant filter、hybrid retrieval、重排和索引版本。没有证据表明实体关系图能带来可测收益。

只有在版本化数据集显示大量多跳/关系查询且普通 hybrid pipeline 达到瓶颈后，才以独立实验评估 GraphRAG。

### 暂不引入复杂多智能体

当前单 Agent 已缺少确定性上限、状态恢复、权限和工具幂等。增加 supervisor/worker 或自治多 Agent 会扩大成本、循环、可观测性和安全面，而没有已验证业务需求。

优先把单 Agent 改造成显式、有界、可恢复的 LangGraph 工作流。只有出现边界清晰、可独立评测的角色分工时才评估多 Agent。

## 后果

正面影响：

- 保留现有可运行 baseline，质量变化可以成对比较。
- 每阶段变更范围小、可回滚、可测试。
- API、数据库、向量库和 provider 可通过协议替换。
- 项目叙述能明确区分当前能力和目标能力。

代价：

- 迁移期会短暂存在旧目录、兼容 adapter 和两种 Streamlit 调用模式。
- 模块边界需要额外协议与 contract tests。
- 目标架构落地速度看似慢于一次性脚手架，但失败定位和回滚成本更低。

## 被否决的方案

1. 一次性生成全套 FastAPI/PostgreSQL/Qdrant/Celery/OTel 代码：缺少稳定 baseline，风险不可分离。
2. 立即拆微服务：没有组织/负载证据，运维和一致性成本过高。
3. 删除 Streamlit：损失已有演示入口，且不是 API 服务化的必要条件。
4. 直接删除 Chroma/BM25：会失去消融 baseline，无法证明新检索器收益。
5. 先做“高级”多 Agent/GraphRAG：与当前最严重的安全、可复现和持久化问题无关。

## 验证方式

- 每个迁移阶段必须有自动化测试、验收标准和回滚策略。
- README 中的当前能力必须能映射到代码和测试；目标能力只能写在架构/路线图中。
- 任何质量或性能数字必须能追溯到包含 commit、dirty state、dataset version 和配置的 artifact。
- 默认 CI 不调用真实付费模型。
