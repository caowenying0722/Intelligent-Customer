# 技术债清单

严重度含义：Blocker 会阻止安全运行或可靠复现；High 会造成显著安全、数据或可用性风险；Medium 会限制维护、验证或演进；Low 是局部质量或文档问题。

| 编号 | 问题 | 严重度 | 影响 | 证据文件 | 推荐方案 | 所属阶段 | 状态 |
|---|---|---|---|---|---|---|---|
| TD-001 | 全局关闭 HTTPS 证书校验 | Blocker | 同进程所有默认 HTTPS context 可遭中间人攻击，模型和文档数据可能泄露 | `model/factory.py:13-14` | 删除全局 monkey patch；仅允许通过受控 CA bundle 配置处理企业代理，并增加 TLS 行为测试 | 1 | 待处理 |
| TD-002 | 当前 Python 3.13 下 requirements 无法解析，且全局包与 `.local_deps` 混用 | Blocker | 应用无法导入，测试环境与运行环境不一致，结果不可复现 | `requirements.txt:1-16`、`scripts/evaluate_rag.py:8-13` | 声明支持 Python 版本，建立干净 3.10/3.11 环境和锁文件；禁止运行时插入临时依赖目录 | 1 | 待处理 |
| TD-003 | Agent 没有代码级最大步骤、工具次数或总超时 | High | 恶意/异常模型可循环调用工具、耗尽成本和 Worker | `agent/react_agent.py:36-58`、`prompts/main_prompt.txt:8` | Settings 中定义上限；LangGraph 调用传 recursion limit；应用服务设置 deadline 并测试超限 | 1/2/4 | 待处理 |
| TD-004 | 导入工具模块即创建 RAG，并在构造时同步入库 | High | import/startup 可发生长耗时 I/O 和本地写入，多 Worker 竞态且 readiness 不可信 | `agent/tools/agent_tools.py:11`、`rag/rag_service.py:25-34`、`rag/vector_store.py:66-136` | 依赖注入 + 显式 lifespan 初始化；入库迁移到有界后台任务 | 1/2/6 | 待处理 |
| TD-005 | 启发式重排使用来源文件名，来源名同时是评测标签 | High | 形成相关性捷径，污染 source recall/MRR 与 README 提升结论 | `rag/reranker.py:49-97`、`evaluation/local_metrics.py:27-44` | 删除来源名特征；冻结独立 regression set；保留无泄漏 baseline 并重跑消融 | 1/5/10 | 待处理 |
| TD-006 | 用户位置和 ID 随机生成，报告工具无认证和租户校验 | High | 任意用户可能读取随机他人记录；无法形成可审计身份链 | `agent/tools/agent_tools.py:45-55,116-125` | 从认证 tenant/user context 注入；repository 默认强制 tenant；增加跨租户拒绝测试 | 3/9 | 待处理 |
| TD-007 | 中间件若启用会记录完整工具参数和消息正文 | High | Prompt、PII、报告参数或文档内容进入日志 | `agent/tools/middleware.py:19-20,40-42` | 结构化日志白名单、字段脱敏和长度限制；安全测试不得出现敏感字段 | 8/9 | 待处理 |
| TD-008 | 模型错误包含完整供应商响应正文 | High | 上游错误可能带请求片段或敏感信息，被 API/日志继续传播 | `model/anthropic_compatible.py:240-241` | 定义安全错误类型，仅保留状态码/请求 ID；原始响应受控采样且脱敏 | 2/7/9 | 待处理 |
| TD-009 | 没有 FastAPI、稳定 schema、错误映射、健康检查或 SSE | High | 无法形成 API-first 服务和可测试的客户端/服务边界 | `app.py:1-43` | 按执行计划引入应用工厂、v1 路由、application service、fake adapter 与协议测试 | 2 | 待处理 |
| TD-010 | 会话只存在 Streamlit 内存，且历史消息不传回 Agent | High | 刷新/重启丢失状态，所谓多轮只展示不推理，无法横向扩容 | `app.py:12-18,26-43`、`agent/react_agent.py:48-53` | 先定义 conversation repository，再用内存实现兼容，后续 PostgreSQL + checkpoint | 2/3/4 | 待处理 |
| TD-011 | Chroma persist path 相对当前工作目录，而非项目根目录 | Medium | 从不同 cwd 启动会创建/读取不同数据库 | `rag/vector_store.py:19-23`、`config/chroma.yml:2` | 由 Settings 解析为规范绝对路径；测试非根 cwd 启动 | 1 | 待处理 |
| TD-012 | 入库 MD5 记录和向量写入非原子，异常被吞后继续 | Medium | 崩溃/并发下可能重复或遗漏；调用者不知道部分失败 | `rag/vector_store.py:73-136` | 显式任务状态、内容哈希唯一约束、批次幂等、分类错误和有限重试 | 6 | 待处理 |
| TD-013 | YAML 配置在 import 时加载且无 schema/范围校验 | Medium | 错误类型、负数上限或无效 URL 到运行时才失败，测试难隔离 | `utils/config_handler.py:13-36` | 集中 Pydantic Settings，兼容读取现有 YAML，启动时 fail-fast | 1/2 | 待处理 |
| TD-014 | middleware 模块未接线且与锁定 LangChain API 不兼容 | Medium | 死代码产生虚假能力印象，直接 import 失败 | `agent/tools/middleware.py:3-8` | 在选定 LangChain/LangGraph 版本后重写并接线，或删除；增加 import test | 1/4 | 待处理 |
| TD-015 | 系统提示词要求输出“真实思考过程” | Medium | 泄露内部推理/策略，增加提示注入和数据暴露面 | `prompts/main_prompt.txt:51-53` | 改成简短用户可见状态，不要求 chain-of-thought；工具审计使用结构化事件 | 4/9 | 待处理 |
| TD-016 | 评测报告不记录 commit、dirty state、dataset version 或延迟 | Medium | 结果不可追溯、不可复现，无法做 CI 回归与性能比较 | `evaluation/runner.py:155-190` | 增加 run manifest、数据哈希、配置快照、逐样本耗时和错误分类 | 10 | 待处理 |
| TD-017 | 引用有效性只验证编号范围，不验证证据支持 | Medium | 无依据回答也可得到 1.0 citation validity | `evaluation/local_metrics.py:100-133` | 区分格式有效、引用覆盖和 entailment/人工标签；加入错误引用样本 | 10 | 待处理 |
| TD-018 | 核心主链缺少自动化测试 | Medium | 25 个测试通过仍不能证明 Agent、RAG、入库和 UI 可运行 | `tests/` | 分层新增 unit/integration/contract/evaluation 测试；默认 fake model | 1/2/10 | 待处理 |
| TD-019 | 无 formatter、lint、type check、coverage、依赖审计和 CI 配置 | Medium | 风格/类型/安全回归不受门禁控制 | 仓库根目录、无 `.github/workflows` | 先选 Ruff + Pyright/Mypy + pytest/coverage + pip-audit，再在 CI 固化 | 1/10 | 待处理 |
| TD-020 | 评测输出含问题、答案、参考答案、召回全文和绝对路径，过去未被忽略 | Medium | 可能误提交用户/知识库数据和本机信息 | `evaluation/runner.py:95-106,175-217`、`.gitignore` | 忽略 `output/`（本轮完成）；后续增加脱敏 artifact profile 与保留策略 | 1/9/10 | 部分完成 |
| TD-021 | README 仓库地址与当前 Git remote 不一致 | Medium | 克隆命令失效或归属叙述不准确 | `README.md:19,122,277`、`git remote -v` | 由用户确认目标公开仓库后修正；当前 README 有用户未提交修改，本轮不覆盖 | 1/11 | 待用户确认 |
| TD-022 | QUICKSTART 包含开发者个人绝对路径 | Low | 其他机器按文档命令无法启动 | `QUICKSTART.md:107,116` | 改成从仓库根目录运行的相对命令 | 1 | 本轮完成 |
| TD-023 | `listdir_with_allowed_type` 在目录无效时返回后缀 tuple | Medium | 调用方会把 `txt/pdf` 当文件路径，错误含糊 | `utils/file_handler.py:28-37` | 返回空 tuple 或抛专用配置错误；增加不存在目录测试 | 1 | 待处理 |
| TD-024 | 模拟“流式”通过阻塞 sleep 逐字符输出 | Medium | 占用 Streamlit 执行线程，不支持上游取消/背压/TTFT | `app.py:32-41` | FastAPI SSE 传稳定事件，Streamlit HTTP 客户端消费；取消传播到 Agent | 2 | 待处理 |
| TD-025 | 无 request ID、结构化日志、trace 或 metrics | Medium | 故障无法按请求关联，无法观测模型/RAG/工具耗时 | `utils/logger_handler.py:14-50` | API middleware 注入 request ID；后续 OTel + Prometheus，控制标签基数 | 2/8 | 待处理 |
| TD-026 | 模型和 RAG 使用全局单例，测试难替换 | Medium | import 顺序影响配置，无法为 API 测试注入 fake model | `model/factory.py:126-128`、`agent/tools/agent_tools.py:11` | 应用 composition root 创建依赖；adapter/interface 分离 | 1/2/7 | 待处理 |
| TD-027 | 低置信度与域外判断是少量硬编码关键词 | Low | 容易误拒答或漏过，不能作为通用安全 guardrail | `rag/guardrails.py:10-27` | 保留为明确 baseline；用版本化策略、可测试分类器和人工升级路径演进 | 5/9/10 | 待处理 |
