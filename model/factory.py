from abc import ABC, abstractmethod
from typing import Optional
import os

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_huggingface import HuggingFaceEmbeddings
from utils.config_handler import rag_conf

# 让 Streamlit 直接启动时也能读取项目根目录的 .env。
load_dotenv()

# Moonshot 使用 OpenAI 兼容协议，ChatOpenAI 默认读取 OPENAI_API_KEY。
_moonshot_key = os.environ.get("MOONSHOT_API_KEY", "")
if _moonshot_key and not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = _moonshot_key


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        pass


class ChatModelFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        provider = os.environ.get("LLM__PROVIDER", "").strip().lower()

        if provider in {"anthropic", "claude"}:
            api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "LLM__PROVIDER=anthropic，但未配置 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY"
                )

            return ChatAnthropic(
                model=os.environ.get("ANTHROPIC_MODEL") or rag_conf["chat_model_name"],
                api_key=api_key,
                base_url=os.environ.get("ANTHROPIC_BASE_URL") or None,
            )

        return ChatOpenAI(
            model=rag_conf["chat_model_name"],
            base_url=rag_conf["chat_base_url"],
        )


class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        return HuggingFaceEmbeddings(
            model_name=rag_conf["embedding_model_path"],
        )


chat_model = ChatModelFactory().generator()

embed_model = EmbeddingsFactory().generator()
