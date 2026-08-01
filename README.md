# 🤖 LangChain ReAct Agent 智能客服


## 项目概述

- 本项目聚焦于智能客服场景下的 Agent 应用实践，通过引入知识库检索、工具调用和动态提示词切换，实现对用户咨询、故障问答和使用报告生成等任务的支持。  
- 项目当前以扫地机器人为示例场景，后续也可扩展到其他垂直客服场景。
---

## 核心特性

#### 1. ReAct Agent 多工具调用
- 集成外部信息查询、用户信息获取等工具能力，支持 Agent 根据任务自动选择合适工具完成辅助推理。

#### 2. RAG 检索增强问答
- 基于向量数据库构建知识库检索能力，支持对扫地机器人相关文档进行召回与问答生成，提升回复准确性。

#### 3. 个性化报告生成
- 通过动态提示词切换，在普通问答模式与报告生成模式之间灵活切换，为用户生成定制化使用分析内容。

#### 4. Streamlit 流式对话界面
- 提供可交互的聊天界面，支持流式输出，便于展示完整的 Agent 问答过程与使用体验。

#### 5. 模块化工程结构
- 项目按 Agent、RAG、模型层、配置层、工具层等模块进行拆分，便于理解整体架构并支持后续扩展。

#### 6. RAG 真实评测系统
- 内置 `data/evaluation/rag_eval_dataset.jsonl` 评测集，覆盖故障排查、维护保养、选购建议和扫拖功能等真实知识库问题。
- 支持本地指标：检索命中率、检索召回率、检索准确率、MRR、来源召回率、答案关键词准确率、答案 F1、答案相似度和上下文覆盖度。
- 支持可选 RAGAS 指标：faithfulness、answer relevancy、context precision、context recall、answer correctness。

#### 7. 可量化 RAG 质量工程魔改
- 候选召回从 `k=3` 扩展到 `candidate_k=8`，再通过轻量证据重排序压回 `top_k=3`，在不增加上下文预算的前提下提升证据质量。
- 回答提示词强制输出 `【资料N】` 引用，并增加引用覆盖率、引用有效性、低置信度命中率等可解释指标。
- 对手机、空调、退款、医疗等知识库域外问题增加低置信度守门，避免客服机器人强答。
- 一键消融对比 baseline 与 rerank 版本，报告自动输出“提升百分点”，方便放到简历、答辩和项目展示中。

当前 28 条本地评测集 smoke 结果：

| 指标 | Baseline | Improved | 提升 |
|---|---:|---:|---:|
| source_recall | 0.577381 | 0.678571 | +10.12 个百分点 |
| answer_keyword_accuracy | 0.796429 | 0.813775 | +1.73 个百分点 |
| answer_relevancy_proxy | 0.724886 | 0.739799 | +1.49 个百分点 |
| factual_correctness_proxy | 0.920358 | 0.925883 | +0.55 个百分点 |
| answer_citation_coverage | 0.817262 | 0.835119 | +1.79 个百分点 |
| low_confidence_accuracy | 1.000000 | 1.000000 | +0.00 个百分点 |

> 注：`answer_relevancy_proxy` 与 `factual_correctness_proxy` 是无模型环境下的本地代理指标。正式 `answer_relevancy`、`factual_correctness(mode=f1)` 建议在完整依赖和 API Key 环境中运行 RAGAS 产出。

---
## 项目结构

```bash
.
├── agent/                       # Agent 核心逻辑
│   ├── react_agent.py           # ReAct智能体主逻辑
│   ├── tools/                   # 工具函数集合
│   └── middleware.py            # 中间件管理
├── assets/                      # README 展示图片等静态资源
├── config/                      # YAML 配置文件
│   ├── agent.yml                # 智能体配置
│   ├── chroma.yml               # 向量库配置
│   ├── prompts.yml              # 提示词配置
│   └── rag.yml                  # RAG配置
├── data/                        # 知识库文档与外部数据
├── model/                       # 模型工厂与模型初始化
│   └── factory.py               # 模型工厂
├── prompts/                     # 提示词模板
├── evaluation/                  # RAG评测模块
├── data/evaluation/             # RAG评测数据集
├── scripts/evaluate_rag.py      # RAG评测入口脚本
├── rag/                         # 检索增强相关模块
│   ├── rag_service.py           # 检索服务
│   └── vector_store.py          # 向量存储
├── utils/                       # 通用工具函数
│   ├── config_handler.py        # 配置加载
│   ├── file_handler.py          # 文件处理
│   ├── logger_handler.py        # 日志管理
│   ├── path_tool.py             # 路径工具
│   └── prompt_loader.py         # 提示词加载
├── app.py                       # Streamlit 应用入口
├── requirements.txt
└── README.md
```

## 工作流程


1. 用户在 Streamlit 页面输入问题

2. Agent 判断当前任务类型 -> 普通问答 / 报告生成

3. 普通问答场景下，调用 RAG 模块检索知识库内容

4. 特定任务场景下，调用外部工具或结构化数据进行辅助生成

5. 最终结果通过流式方式返回到前端界面

---
## 效果预览

### 1. 聊天界面展示
- 展示用户在前端输入问题后，系统返回问答结果的整体效果。

<img src="assets/chat1.png" width="700"/>

### 2. Agent 工具调用过程
- 展示 Agent 在任务处理中调用外部工具或执行中间推理的过程。
  
<img src="assets/chat2.png" width="700"/>

### 3. 报告生成示例
- 展示系统根据用户数据生成个性化分析报告的结果页面。

<img src="assets/chat3.png" width="700"/>


---


## 快速开始

### 环境要求
- Python 3.10 及以上
- 可用的大模型 API Key（如阿里云百炼）

### 运行前准备
- 安装项目依赖
- 配置模型 API Key
- 准备知识库文档与相关配置文件

---

## 安装步骤

- 克隆项目
```bash

git clone https://github.com/lhh737/LangChain-ReAct-Agent.git
```
- 安装依赖
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```
- 配置环境变量

- 在config目录下创建调整相应的 yml 配置文件
```bash
export DASHSCOPE_API_KEY="your-api-key"
```
- 启动应用
```bash
streamlit run app.py
```

- 运行 RAG 评测（默认只跑本地指标）
```bash
python scripts/evaluate_rag.py
```

- 运行 baseline 与重排序版本的消融对比
```bash
python scripts/compare_rag_ablation.py --retriever bm25 --no-generate --answer-mode extractive
```

- 若当前 Python 版本与完整向量库依赖冲突，可先把 RAGAS 轻量评测依赖安装到项目目录
```bash
python -m pip install --target .local_deps -r requirements-ragas-lite.txt
```

- 正式运行 RAGAS 前先做环境预检
```bash
python scripts/preflight_ragas.py
```

若使用 DeepSeek 的 Anthropic 兼容网关，在项目根目录 `.env` 中配置 `LLM__PROVIDER=anthropic`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL` 和 `ANTHROPIC_MODEL`。`.env` 已加入忽略列表，不会进入版本库；URL 请写纯文本，不要写 Markdown 链接格式。

也可以用交互式脚本初始化本地 `.env`，密钥不会显示在终端输出中：
```bash
python scripts/setup_private_env.py
```

如果已经在当前终端设置了 `ANTHROPIC_AUTH_TOKEN`，可以直接写入本地 `.env`：
```bash
python scripts/setup_private_env.py --from-current-env
```

- 将对比结果整理成面试展示摘要
```bash
python scripts/summarize_quality_report.py --comparison output/evaluation_ablation_bm25_proxy_latest/comparison/comparison.json
```

- 运行 RAGAS 评测（会调用配置的大模型 API）
```bash
python scripts/evaluate_rag.py --run-ragas --ack-external-judge --ragas-metrics "answer_relevancy,factual_correctness(mode=f1)" --ragas-data-mode minimal --ragas-eval-mode per_sample
python scripts/compare_rag_ablation.py --retriever bm25 --answer-mode extractive --run-ragas --ack-external-judge --ragas-metrics "answer_relevancy,factual_correctness(mode=f1)" --ragas-data-mode minimal --ragas-eval-mode per_sample
python scripts/run_ragas_ablation.py --ack-external-judge --ragas-data-mode minimal --ragas-eval-mode per_sample
```

`run_ragas_ablation.py` 会先执行预检，再跑 baseline/rerank 消融，最后自动打印面试展示摘要。
摘要会优先展示正式 `answer_relevancy` 与 `factual_correctness(mode=f1)`；如果当前只有本地代理指标，会明确标记正式 RAGAS 指标未产出。
注意：正式 RAGAS 会把评测内容发送到配置的外部评审模型，所以必须显式传入 `--ack-external-judge`。默认 `--ragas-data-mode minimal` 只为 `answer_relevancy` / `factual_correctness(mode=f1)` 发送问题、答案和参考答案；如使用 `full` 或上下文类指标，才会发送检索上下文。默认 `--ragas-eval-mode per_sample` 会逐条评测，降低单条网络失败对整批报告的影响。

- 验收 RAG 质量工程目标是否真正完成
```bash
python scripts/validate_quality_goal.py --comparison output/evaluation_ablation_bm25_proxy_latest/comparison/comparison.json
```

该脚本会检查重排序配置、证据引用、低置信度、评测集、消融设计、关键指标提升，以及正式 `answer_relevancy` / `factual_correctness(mode=f1)` 是否在对比报告中取得正向提升。

- 一键运行质量工程流水线
```bash
python scripts/run_quality_pipeline.py
```

该命令会先生成本地/proxy 消融报告；若 RAGAS 预检通过，会继续运行正式 RAGAS 消融和严格验收。
如需允许正式 RAGAS 外部评审，使用：
```bash
python scripts/run_quality_pipeline.py --ack-external-judge
```

- 提交或展示前检查是否误写入密钥
```bash
python scripts/scan_secrets.py
```

默认会跳过本地 `.env`、`.local_deps/` 和评测输出目录，用于检查源码、配置和文档中是否混入 API Key。

- 只验证检索召回，不调用大模型生成答案
```bash
python scripts/evaluate_rag.py --no-generate --no-ragas
```

评测报告会输出到 `output/evaluation/时间戳/`，包含：
- `summary.json`：平均指标汇总
- `metrics.csv`：逐问题指标表
- `samples.jsonl`：逐问题答案、召回文档和指标明细
---


## 支持的任务类型

- **知识库问答**：针对扫地机器人等相关文档进行检索与问答生成
- **工具辅助问答**：在需要外部信息时调用工具增强回复效果
- **报告生成**：根据输入数据与任务要求生成个性化分析报告
- **多场景提示词切换**：根据任务类型自动选择合适的提示词模板

---

## 配置说明

- 项目主要通过 YAML 文件进行配置管理，首次运行时，建议优先检查以下文件：

> `config/agent.yml` ：Agent 行为与任务流程相关配置

> `config/chroma.yml` ：向量数据库与检索存储配置

> `config/prompts.yml` ：不同任务场景下的提示词配置

> `config/rag.yml` ：RAG 检索参数配置


- 若只想完成最小化本地运行，建议先确保：
1. 已正确配置模型 API Key

2. `config/` 下必要的 YAML 文件已存在

3. `data/` 目录中已放入知识库文档
---
## 最小成功演示

- 应用启动后，可先尝试以下问题验证项目是否正常运行：

#### 普通问答
- 扫地机器人有哪些主要功能？
- 如果机器人无法正常回充，该如何处理？

#### 报告生成
- 请根据用户数据生成一份个性化使用报告。

如果以上问题能够正常返回内容，说明项目的基础问答与任务切换流程已经运行成功。

## 感谢与支持
- Black Horse
- Langchain / LangGraph
- Streamlit
- Chroma
- Kimi

