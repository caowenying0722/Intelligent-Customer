import os
import ssl
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from model.anthropic_compatible import AnthropicCompatibleChatModel
from model.runtime_config import ModelRuntimeConfig
from utils.config_handler import rag_conf
from utils.env_loader import load_env_file


def load_project_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_env_file(env_path)


load_project_env()

# 配置 HuggingFace 离线模式，避免本地模型加载时卡在远程 metadata 检查
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 自动将 DeepSeek/Moonshot API Key 映射为 OPENAI_API_KEY（ChatOpenAI 读取的变量名）
_deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
_moonshot_key = os.environ.get("MOONSHOT_API_KEY", "")
if _deepseek_key and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = _deepseek_key
elif _moonshot_key and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = _moonshot_key


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Embeddings | BaseChatModel:
        pass


def resolve_huggingface_local_path(model_name: str) -> str:
    if os.path.exists(model_name):
        return model_name

    if "/" not in model_name:
        return model_name

    cache_root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    repo_dir = cache_root / "hub" / f"models--{model_name.replace('/', '--')}"
    snapshots_dir = repo_dir / "snapshots"
    if not snapshots_dir.exists():
        return model_name

    preferred_commit = None
    main_ref = repo_dir / "refs" / "main"
    if main_ref.exists():
        preferred_commit = main_ref.read_text(encoding="utf-8").strip()

    candidate_dirs = []
    if preferred_commit:
        candidate_dirs.append(snapshots_dir / preferred_commit)
    candidate_dirs.extend(
        sorted(
            snapshots_dir.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True
        )
    )

    for candidate_dir in candidate_dirs:
        if not candidate_dir.is_dir():
            continue
        if (candidate_dir / "modules.json").exists() or (
            candidate_dir / "config.json"
        ).exists():
            return str(candidate_dir)

    return model_name


class ChatModelFactory(BaseModelFactory):
    def generator(self) -> BaseChatModel:
        provider = os.environ.get("LLM__PROVIDER", "").lower()
        anthropic_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get(
            "ANTHROPIC_API_KEY"
        )
        runtime_config = ModelRuntimeConfig.from_env()
        if provider == "anthropic" or anthropic_key:
            return AnthropicCompatibleChatModel(
                model_name=os.environ.get("ANTHROPIC_MODEL")
                or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
                or rag_conf["chat_model_name"],
                base_url=os.environ.get(
                    "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
                ),
                api_key=anthropic_key or "EMPTY",
                timeout=runtime_config.request_timeout_seconds,
                verify=runtime_config.requests_verify,
            )

        model_kwargs: dict[str, Any] = {
            "model": rag_conf["chat_model_name"],
            "base_url": rag_conf["chat_base_url"],
            "api_key": os.environ.get("OPENAI_API_KEY") or "EMPTY",
            "request_timeout": runtime_config.request_timeout_seconds,
            "max_retries": runtime_config.max_retries,
        }
        if runtime_config.ca_bundle is not None:
            tls_context = ssl.create_default_context(
                cafile=str(runtime_config.ca_bundle)
            )
            model_kwargs["http_client"] = httpx.Client(
                verify=tls_context,
                timeout=runtime_config.request_timeout_seconds,
            )
            model_kwargs["http_async_client"] = httpx.AsyncClient(
                verify=tls_context,
                timeout=runtime_config.request_timeout_seconds,
            )

        return ChatOpenAI(**model_kwargs)


class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Embeddings:
        from langchain_huggingface import HuggingFaceEmbeddings

        model_name = rag_conf["embedding_model_path"]
        local_model_name = resolve_huggingface_local_path(model_name)
        return HuggingFaceEmbeddings(
            model_name=local_model_name,
            model_kwargs={"local_files_only": True},
            encode_kwargs={"normalize_embeddings": True},
        )


class LazyEmbeddings(Embeddings):
    def __init__(self) -> None:
        self._model: Embeddings | None = None

    @property
    def model(self) -> Embeddings:
        if self._model is None:
            self._model = EmbeddingsFactory().generator()
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.model.embed_query(text)


chat_model = ChatModelFactory().generator()

embed_model = LazyEmbeddings()
