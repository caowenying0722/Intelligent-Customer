import os
import ssl
from abc import ABC, abstractmethod
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from model.anthropic_compatible import AnthropicCompatibleChatModel
from model.cache import ModelCache
from model.gateway import CacheBackend, ModelGateway
from model.quota import TenantQuota
from model.redis_cache import RedisCacheAdapter
from model.runtime_config import ModelRuntimeConfig
from utils.settings import Settings, get_settings


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
    def __init__(
        self,
        settings: Settings | None = None,
        rag_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.settings = settings
        self.rag_config = rag_config

    def generator(self) -> BaseChatModel:
        settings = self.settings or get_settings()
        if self.rag_config is None:
            from utils.config_handler import rag_conf

            config: Mapping[str, Any] = rag_conf
        else:
            config = self.rag_config
        runtime_config = ModelRuntimeConfig.from_settings(settings)
        if settings.resolved_model_provider == "anthropic":
            return AnthropicCompatibleChatModel(
                model_name=settings.anthropic_model
                or settings.anthropic_default_sonnet_model
                or config["chat_model_name"],
                base_url=settings.anthropic_base_url,
                api_key=settings.anthropic_api_key_value or "EMPTY",
                timeout=runtime_config.request_timeout_seconds,
                verify=runtime_config.requests_verify,
            )

        model_kwargs: dict[str, Any] = {
            "model": config["chat_model_name"],
            "base_url": config["chat_base_url"],
            "api_key": settings.openai_compatible_api_key_value or "EMPTY",
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
    def __init__(self, rag_config: Mapping[str, Any] | None = None) -> None:
        self.rag_config = rag_config

    def generator(self) -> Embeddings:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        from langchain_huggingface import HuggingFaceEmbeddings

        if self.rag_config is None:
            from utils.config_handler import rag_conf

            config: Mapping[str, Any] = rag_conf
        else:
            config = self.rag_config
        model_name = config["embedding_model_path"]
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


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    return ChatModelFactory().generator()


@lru_cache(maxsize=1)
def get_embedding_model() -> Embeddings:
    return LazyEmbeddings()


def build_chat_gateway(
    model: BaseChatModel | None = None,
    *,
    provider: str = "default",
    runtime: ModelRuntimeConfig | None = None,
    settings: Settings | None = None,
    max_concurrency: int = 8,
    cache: CacheBackend | None = None,
    redis_client: object | None = None,
) -> ModelGateway:
    """Adapt an explicitly selected chat model behind the bounded gateway."""
    selected = model if model is not None else get_chat_model()
    selected_settings = settings or get_settings()
    config = runtime or ModelRuntimeConfig.from_settings(selected_settings)
    concurrency = (
        selected_settings.model_max_concurrency
        if settings is not None
        else max_concurrency
    )
    selected_cache = cache
    if selected_cache is None and settings is not None:
        selected_cache = (
            RedisCacheAdapter.from_settings(redis_client, selected_settings)
            if redis_client is not None
            else ModelCache.from_settings(selected_settings)
        )
    quota = (
        TenantQuota.from_settings(selected_settings) if settings is not None else None
    )
    return ModelGateway(
        {provider: selected.invoke},
        timeout_seconds=config.request_timeout_seconds,
        max_retries=config.max_retries,
        max_concurrency=concurrency,
        failure_threshold=selected_settings.model_failure_threshold,
        cooldown_seconds=selected_settings.model_cooldown_seconds,
        rate_limit_per_second=selected_settings.model_rate_limit_per_second,
        cache=selected_cache,
        quota=quota,
    )


def clear_model_caches() -> None:
    get_chat_model.cache_clear()
    get_embedding_model.cache_clear()
