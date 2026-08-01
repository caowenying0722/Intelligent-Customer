# 🚀 Intelligent-Customer-Service 项目启动指南

## ✅ 环境配置完成

Conda 环境 `ics` 已成功创建并配置！

### 已安装的关键组件
- Python 3.10
- LangChain 0.3.7 和相关组件
- LangGraph 0.2.50（工作流编排）
- Streamlit 1.40.1（Web UI）
- ChromaDB 0.5.15（向量数据库）
- Torch 2.12.0 和 Transformers（本地模型支持）
- Sentence Transformers（文本嵌入）

### 依赖验证
所有依赖已成功安装，无任何版本冲突（pip check: No broken requirements）

---

## ⚙️ 项目配置

### 1. 配置 API Key（必需步骤）

项目可以使用 Moonshot/Kimi、DeepSeek OpenAI-compatible 接口，或 DeepSeek 的 Anthropic-compatible 网关。当前 RAGAS 评审链路推荐使用 Anthropic-compatible 配置，便于复现 `answer_relevancy` 与 `factual_correctness(mode=f1)`。

#### 获取 API Key：
1. 按所选模型服务商创建 API Key。
2. 本地评测不需要 Key；正式 RAGAS 评测建议写入项目根目录 `.env`。

#### 设置环境变量（两种方式）：

**方式1：通过系统环境变量（推荐）**
```bash
# Windows (PowerShell)
$env:LLM__PROVIDER = "anthropic"
$env:ANTHROPIC_AUTH_TOKEN = "<your token>"
$env:ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
$env:ANTHROPIC_MODEL = "deepseek-v4-flash"

# Windows (CMD)
set LLM__PROVIDER=anthropic
set ANTHROPIC_AUTH_TOKEN=<your token>

# Linux/Mac
export LLM__PROVIDER=anthropic
export ANTHROPIC_AUTH_TOKEN="<your token>"
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_MODEL="deepseek-v4-flash"
```

**方式2：编辑 .env 文件**
```bash
# 复制 .env.example 为 .env
cp .env.example .env

# 编辑 .env 文件并填入你的 API Key
LLM__PROVIDER=anthropic
ANTHROPIC_AUTH_TOKEN=<your token>
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-flash
```

也可以用隐藏输入创建 `.env`：

```bash
python scripts/setup_private_env.py
python scripts/preflight_ragas.py
```

### 2. 验证配置
```bash
# 激活环境
conda activate ics

# 验证 RAGAS 评审环境，输出只显示变量名，不显示 Key 明文
python scripts/preflight_ragas.py
```

---

## 🚀 启动应用

### 方式1：手动启动
```bash
# 激活 conda 环境
conda activate ics

# 在仓库根目录启动 Streamlit 应用
python -m streamlit run app.py
```

### 方式2：通过 PowerShell（推荐）
```powershell
# 在仓库根目录激活环境并启动
conda activate ics; python -m streamlit run app.py
```

---

## 📊 运行 RAG 评测

### 1. 快速跑本地评测指标
```bash
python scripts/evaluate_rag.py
```

默认读取 `data/evaluation/rag_eval_dataset.jsonl`，并输出：
- 检索命中率、召回率、准确率、MRR、来源召回率
- 答案关键词准确率、答案 F1、答案相似度、上下文覆盖度

报告保存在：
```bash
output/evaluation/时间戳/
```

### 2. 只跑前几条样例
```bash
python scripts/evaluate_rag.py --limit 3
```

### 3. 只检查检索召回
```bash
python scripts/evaluate_rag.py --no-generate --no-ragas
```

该模式不调用大模型生成答案，适合先验证知识库分块、向量检索和混合检索参数。

### 4. 开启 RAGAS 评测
```bash
python scripts/evaluate_rag.py --run-ragas --ack-external-judge --ragas-metrics "answer_relevancy,factual_correctness(mode=f1)" --ragas-data-mode minimal --ragas-eval-mode per_sample
```

RAGAS 会调用配置的大模型 API 进行评判，必须显式传入 `--ack-external-judge` 表示你确认允许评测内容发送到外部评审模型。默认 `minimal` 模式只为目标指标发送问题、答案和参考答案，不发送检索上下文；`per_sample` 模式会逐条评测，单条失败不会拖垮整批报告。

正式消融对比建议运行：

```bash
python scripts/run_ragas_ablation.py --ack-external-judge --ragas-data-mode minimal --ragas-eval-mode per_sample
```

当前重点展示指标包括：
- answer_relevancy
- factual_correctness(mode=f1)
- answer_keyword_accuracy
- answer_citation_coverage
- low_confidence_accuracy

如需调整评测集、输出目录或 RAGAS 指标，可编辑 `config/evaluation.yml`。

---

## 🌐 访问应用

应用启动后，会自动在浏览器中打开，或手动访问：
- **本地地址**: http://localhost:8501
- **网络地址**: http://你的IP:8501

---

## 📝 快速测试

应用启动成功后，可以尝试以下问题来验证功能：

### 普通问答
```
扫地机器人有哪些主要功能？
如果机器人无法正常回充，该如何处理？
怎样清洁滚刷？
```

### 报告生成
```
请根据用户数据生成一份个性化使用报告。
```

### 工具调用
```
我的扫地机器人在什么时间出现了故障？
```

---

## 🔧 项目配置文件说明

### 关键配置文件

| 文件 | 说明 |
|------|------|
| `config/rag.yml` | RAG 和模型配置（API 端点、模型名称等） |
| `config/chroma.yml` | 向量数据库配置 |
| `config/prompts.yml` | 提示词模板路径配置 |
| `config/agent.yml` | Agent 行为配置 |
| `config/evaluation.yml` | RAG 评测集、RAGAS 指标、数据模式和运行模式 |

### 当前 RAG 配置
```yaml
chat_model_name: deepseek-chat
chat_base_url: https://api.deepseek.com/v1
embedding_model_path: BAAI/bge-m3
```

如果 `.env` 中设置了 `LLM__PROVIDER=anthropic` 和 `ANTHROPIC_AUTH_TOKEN`，项目会优先使用 Anthropic-compatible 网关。

---

## 📚 知识库文档

项目包含的知识库文档位于 `data/` 目录：
- `扫地机器人100问2.txt` - 产品常见问题
- `扫拖一体机器人100问.txt` - 扫拖一体产品问题
- `故障排除.txt` - 故障排查指南
- `维护保养.txt` - 维护保养指南
- `选购指南.txt` - 购买指南
- `external/records.csv` - 外部数据记录

---

## 🛠️ 故障排查

### 问题1: "ModuleNotFoundError: No module named 'xxx'"
**解决方案**：
```bash
conda activate ics
pip list  # 验证所有依赖是否已安装
```

### 问题2: "OPENAI_API_KEY 未设置"
**解决方案**：
1. 检查 `.env` 中的 `ANTHROPIC_AUTH_TOKEN` 或 OpenAI-compatible Key 是否正确设置
2. 重新启动终端/IDE 以加载新的环境变量
3. 使用 `python scripts/preflight_ragas.py` 验证设置

### 问题3: Streamlit 端口被占用
**解决方案**：
```bash
streamlit run app.py --server.port=8502
```

### 问题4: 模型下载缓慢/超时
**解决方案**：
- 预下载 `bge-m3` 模型到本地 cache
- 增加 API 请求超时时间
- 检查网络连接

---

## 📊 项目架构概览

```
┌─────────────────────────────────────────┐
│     Streamlit Web UI (app.py)           │
├─────────────────────────────────────────┤
│         ReactAgent (LangGraph)          │
│  ┌──────────────┬──────────┬──────────┐ │
│  │  RAG Tools   │ External │  Report  │ │
│  │              │  Tools   │Generator │ │
│  └──────────────┴──────────┴──────────┘ │
├─────────────────────────────────────────┤
│  LLM (OpenAI/Anthropic-compatible)       │
├─────────────────────────────────────────┤
│      Chroma Vector DB / Knowledge Base   │
└─────────────────────────────────────────┘
```

---

## 📞 获取帮助

- 项目源仓库: https://github.com/lhh737/LangChain-ReAct-Agent
- DeepSeek 文档: https://api-docs.deepseek.com/
- LangChain 文档: https://python.langchain.com/
- Streamlit 文档: https://docs.streamlit.io/

---

## ✨ 下一步

1. ✅ 配置 API Key
2. ✅ 运行 Streamlit 应用
3. 📝 提问并测试功能
4. 🔧 根据需要调整提示词（`prompts/` 目录）
5. 📚 补充或更新知识库文档（`data/` 目录）

祝你使用愉快！ 🎉
