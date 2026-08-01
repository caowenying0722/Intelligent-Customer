# 技术债清单

严重度含义：Blocker 会阻止安全运行或可靠复现；High 会造成显著安全、数据或可用性风险；Medium 会限制维护、验证或演进；Low 是局部质量或文档问题。

| 编号 | 问题 | 严重度 | 影响 | 证据文件 | 推荐方案 | 所属阶段 | 状态 |
|---|---|---|---|---|---|---|---|
| TD-001 | 曾全局关闭 HTTPS 证书校验 | Blocker | 同进程所有默认 HTTPS context 可遭中间人攻击，模型和文档数据可能泄露 | `model/factory.py`、`model/runtime_config.py` | 已删除全局 monkey patch；默认验证证书，仅允许显式 CA bundle，并覆盖默认/自定义/非法配置测试 | 1 | 已完成 |
| TD-002 | Python 3.13 下 requirements 无法解析 | High | 默认 shell 与支持环境不一致；Python 3.13 不属于支持矩阵 | `.python-version`、`requirements*.txt`、`scripts/check_environment.py` | `.python-version` 固定 Python 3.10；`requirements.lock` 和 `requirements-dev.lock` 由 pip-compile 生成，Python 3.10 clean dry-run 通过 | 1 | 已完成（支持矩阵外环境仍不支持） |
| TD-003 | Agent 请求没有全流程 deadline 或取消传播 | High | 步骤与工具次数已受限，但单次慢工具/模型仍可长期占用 Worker | `agent/react_agent.py`、`utils/settings.py` | 已接入 Settings 驱动的 recursion/tool-call 上限和安全终止；阶段 2 application service 增加 deadline/cancellation 并测试 | 1/2/4 | 部分完成 |
| TD-004 | 首次 RAG 工具检索仍可能等待入库 | High | import 和 RAG service 构造已无 Chroma 入库副作用；首次检索会等待有界后台任务，服务层 readiness/API 状态仍待阶段二统一 | `agent/tools/agent_tools.py`、`rag/rag_service.py`、`rag/vector_store.py` | `start_document_loading()` 单飞启动后台加载，`ensure_documents_loaded()` 有显式超时并传播失败；阶段二接入 lifespan/readiness | 1/2/6 | 阶段一完成，阶段二边界待接入 |
| TD-005 | 启发式重排使用来源文件名，来源名同时是评测标签 | High | 形成相关性捷径，污染 source recall/MRR 与 README 提升结论 | `rag/reranker.py:49-97`、`evaluation/local_metrics.py:27-44` | 删除来源名特征；冻结独立 regression set；保留无泄漏 baseline 并重跑消融 | 1/5/10 | 待处理 |
| TD-006 | 用户位置和 ID 随机生成，报告工具无认证和租户校验 | High | 任意用户可能读取随机他人记录；无法形成可审计身份链 | `agent/tools/agent_tools.py:45-55,116-125` | 从认证 tenant/user context 注入；repository 默认强制 tenant；增加跨租户拒绝测试 | 3/9 | 待处理 |
| TD-007 | 中间件若启用会记录完整工具参数和消息正文 | High | Prompt、PII、报告参数或文档内容进入日志 | `agent/tools/middleware.py:19-20,40-42` | 结构化日志白名单、字段脱敏和长度限制；安全测试不得出现敏感字段 | 8/9 | 待处理 |
| TD-008 | 模型错误包含完整供应商响应正文 | High | 上游错误可能带请求片段或敏感信息，被 API/日志继续传播 | `model/anthropic_compatible.py:240-241` | 定义安全错误类型，仅保留状态码/请求 ID；原始响应受控采样且脱敏 | 2/7/9 | 待处理 |
| TD-009 | FastAPI 持久化会话和完整错误映射尚未实现 | High | 当前聊天 API 仍是内存边界，SSE 对同步 Agent 的取消只能在适配器层停止等待 | `src/app/main.py`、`src/app/application/chat.py`、`src/app/domain/conversations.py` | 应用工厂、request ID、健康检查、严格 schema、fake Agent、timeout 错误映射、基础 SSE、线程安全内存 repository 和原生异步取消边界已完成；继续增加 PostgreSQL repository | 2/3 | 部分完成 |
| TD-010 | 会话只存在 Streamlit 内存，且历史消息不传回 Agent | High | 刷新/重启丢失状态，所谓多轮只展示不推理，无法横向扩容 | `app.py:12-18,26-43`、`agent/react_agent.py:48-53` | 先定义 conversation repository，再用内存实现兼容，后续 PostgreSQL + checkpoint | 2/3/4 | 待处理 |
| TD-011 | Chroma persist path 曾相对当前工作目录 | Medium | 从不同 cwd 启动曾会创建/读取不同数据库 | `utils/config_handler.py`、`utils/path_tool.py`、`config/chroma.yml` | 所有业务路径现由 schema loader 相对项目根解析为绝对路径，并覆盖非根 cwd 测试 | 1 | 已完成 |
| TD-012 | 入库 MD5 记录和向量写入非原子，异常被吞后继续 | Medium | 崩溃/并发下可能重复或遗漏；调用者不知道部分失败 | `rag/vector_store.py:73-136` | 显式任务状态、内容哈希唯一约束、批次幂等、分类错误和有限重试 | 6 | 待处理 |
| TD-013 | 业务 YAML 仍在首次相关模块加载时读取 | Medium | schema、范围、URL 和路径已 fail-fast，但配置生命周期尚未统一到应用 composition root | `utils/settings.py`、`utils/config_handler.py` | 安全类型化 YAML 与兼容 dict 已完成；阶段 2 应用工厂显式加载并注入配置 | 1/2 | 部分完成 |
| TD-014 | middleware 模块未接线且未做脱敏 | Medium | 死代码产生虚假能力印象；若直接启用会泄露完整消息和工具参数 | `agent/tools/middleware.py` | 当前 LangChain 版本下可导入；后续重写为脱敏结构化事件并接线，或删除；增加行为测试 | 1/4/8 | 部分完成 |
| TD-015 | 系统提示词要求输出“真实思考过程” | Medium | 泄露内部推理/策略，增加提示注入和数据暴露面 | `prompts/main_prompt.txt:51-53` | 改成简短用户可见状态，不要求 chain-of-thought；工具审计使用结构化事件 | 4/9 | 待处理 |
| TD-016 | 评测报告不记录 commit、dirty state、dataset version 或延迟 | Medium | 结果不可追溯、不可复现，无法做 CI 回归与性能比较 | `evaluation/runner.py:155-190` | 增加 run manifest、数据哈希、配置快照、逐样本耗时和错误分类 | 10 | 待处理 |
| TD-017 | 引用有效性只验证编号范围，不验证证据支持 | Medium | 无依据回答也可得到 1.0 citation validity | `evaluation/local_metrics.py:100-133` | 区分格式有效、引用覆盖和 entailment/人工标签；加入错误引用样本 | 10 | 待处理 |
| TD-018 | 核心主链缺少自动化测试 | Medium | 74 个测试通过但源码分支覆盖率仅 41%，仍不能证明完整 Agent、RAG 和入库交互可靠 | `tests/`、`pyproject.toml` | 分层新增 unit/integration/contract/evaluation 测试；默认 fake model；基于高风险模块逐步提高门禁 | 1/2/10 | 部分完成 |
| TD-019 | 静态检查和覆盖率尚未接入 CI 门禁 | Medium | 本地全仓 Ruff/格式/Mypy 已清零且 Coverage 有真实基线，但远端提交仍不会自动阻止回归 | `pyproject.toml`、`requirements-dev.txt`、无 `.github/workflows` | 阶段 10 将相同命令固化到 CI；覆盖率先补核心测试再设置合理阈值 | 1/10 | 部分完成 |
| TD-020 | 评测输出含问题、答案、参考答案、召回全文和绝对路径，过去未被忽略 | Medium | 可能误提交用户/知识库数据和本机信息 | `evaluation/runner.py:95-106,175-217`、`.gitignore` | 忽略 `output/`（本轮完成）；后续增加脱敏 artifact profile 与保留策略 | 1/9/10 | 部分完成 |
| TD-021 | README 仓库地址曾与 Git remote 不一致 | Low | 推送到了错误目标或克隆命令与开发 remote 不一致 | `README.md:19,122,277`、本地 `origin` | 用户已确认并将 `origin` 修正为 `caowenying0722/Intelligent-Customer` | 1/11 | 已完成 |
| TD-022 | QUICKSTART 包含开发者个人绝对路径 | Low | 其他机器按文档命令无法启动 | `QUICKSTART.md:107,116` | 改成从仓库根目录运行的相对命令 | 1 | 本轮完成 |
| TD-023 | `listdir_with_allowed_type` 在目录无效时返回后缀 tuple | Medium | 调用方会把 `txt/pdf` 当文件路径，错误含糊 | `utils/file_handler.py:28-37` | 返回空 tuple 或抛专用配置错误；增加不存在目录测试 | 1 | 待处理 |
| TD-024 | 模拟“流式”通过阻塞 sleep 逐字符输出 | Medium | 占用 Streamlit 执行线程，不支持上游取消/背压/TTFT | `app.py:32-41` | FastAPI SSE 传稳定事件，Streamlit HTTP 客户端消费；取消传播到 Agent | 2 | 待处理 |
| TD-025 | 尚无结构化日志、trace 或 metrics | Medium | 故障无法按请求关联，无法观测模型/RAG/工具耗时 | `utils/logger_handler.py:14-50`、`src/app/main.py` | API middleware 已注入并回传 request ID；后续 OTel + Prometheus，控制标签基数 | 2/8 | 部分完成 |
| TD-026 | 默认模型和 RAG 仍使用进程内缓存实例 | Medium | import-time 单例已删除且核心构造器可注入，但尚无 API composition root 或生命周期关闭钩子 | `model/factory.py`、`agent/react_agent.py`、`rag/rag_service.py` | 在 FastAPI 应用工厂集中创建/关闭依赖；adapter/interface 继续分离 | 1/2/7 | 部分完成 |
| TD-027 | 低置信度与域外判断是少量硬编码关键词 | Low | 容易误拒答或漏过，不能作为通用安全 guardrail | `rag/guardrails.py:10-27` | 保留为明确 baseline；用版本化策略、可测试分类器和人工升级路径演进 | 5/9/10 | 待处理 |
| TD-028 | 当前运行依赖仍有 3 条已知漏洞记录，涉及 3 个直接或传递包 | Blocker | 剩余直接或传递依赖漏洞会阻止依赖安全门禁通过 | `requirements.txt`、`requirements.lock`、`python -m pip_audit -r requirements.txt` | 已完成 PDF、UI、LangChain/LangGraph 和 ML 栈迁移；锁文件保留受影响版本，不使用 ignore 掩盖；等待上游修复或替换依赖前，发布门禁必须保持失败 | 1 | 外部阻塞，已记录风险 |
