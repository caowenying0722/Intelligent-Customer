"""
总结服务类：用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型总结回复
"""

from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import nullcontext
from threading import Lock
from typing import Any

from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.retrievers import BaseRetriever

from model.factory import get_chat_model
from rag.guardrails import is_out_of_scope_query, low_confidence_response
from rag.reranker import LightweightEvidenceReranker
from rag.vector_store import VectorStoreService
from src.app.observability.tracing import get_current_tracer
from utils.config_handler import chroma_conf
from utils.prompt_loader import load_rag_prompts


def print_prompt(prompt):
    print("=" * 20)
    print(prompt.to_string())
    print("=" * 20)
    return prompt


class RagSummarizeService:
    def __init__(
        self,
        print_prompts: bool = True,
        vector_store: VectorStoreService | None = None,
        model: BaseChatModel | None = None,
        document_load_timeout_seconds: float = 300.0,
        tracer: Any | None = None,
    ):
        self.vector_store = (
            vector_store if vector_store is not None else VectorStoreService()
        )
        self.retriever: BaseRetriever | None = None
        self._documents_loaded = False
        self._document_load_future: Future[None] | None = None
        self._document_load_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="rag-document-load"
        )
        self._document_load_lock = Lock()
        self.document_load_timeout_seconds = document_load_timeout_seconds
        self.reranker = LightweightEvidenceReranker()
        self.prompt_text = load_rag_prompts()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = model if model is not None else get_chat_model()
        self.print_prompts = print_prompts
        self.tracer = tracer
        self.chain = self._init_chain()

    def _span(self, name: str):
        tracer = self.tracer or get_current_tracer()
        return tracer.start_span(name) if tracer is not None else nullcontext(None)

    def _init_chain(self):
        if self.print_prompts:
            return self.prompt_template | print_prompt | self.model | StrOutputParser()

        return self.prompt_template | self.model | StrOutputParser()

    def start_document_loading(self) -> Future[None] | None:
        """Start at most one bounded background ingestion task."""
        with self._document_load_lock:
            if self._documents_loaded:
                return None
            if self._document_load_future is None:
                self._document_load_future = self._document_load_executor.submit(
                    self._load_documents
                )
            return self._document_load_future

    def _load_documents(self) -> None:
        self.vector_store.load_document()
        self.retriever = self.vector_store.get_retriever()
        self._documents_loaded = True

    def ensure_documents_loaded(self) -> None:
        future = self.start_document_loading()
        if future is None:
            return
        try:
            future.result(timeout=self.document_load_timeout_seconds)
        except FutureTimeoutError as exc:
            raise TimeoutError(
                "RAG document loading exceeded its configured timeout"
            ) from exc

    def close(self) -> None:
        self._document_load_executor.shutdown(wait=False, cancel_futures=True)

    def retriever_docs(self, query: str) -> list[Document]:
        self.ensure_documents_loaded()
        if self.retriever is None:
            raise RuntimeError("RAG retriever was not initialized")

        with self._span("retrieval.dense") as span:
            docs = self.retriever.invoke(query)
            if span is not None:
                span.set_attribute("retrieval.status", "completed")
        if chroma_conf.get("rerank_enabled", False):
            with self._span("retrieval.rerank") as span:
                reranked = self.reranker.rerank(
                    query=query,
                    docs=docs,
                    top_k=chroma_conf.get("rerank_top_k", chroma_conf["k"]),
                )
                if span is not None:
                    span.set_attribute("retrieval.status", "completed")
                return reranked
        return docs[: chroma_conf["k"]]

    @staticmethod
    def format_context(context_docs: list[Document]) -> str:
        context = ""
        for counter, doc in enumerate(context_docs, start=1):
            source = (
                doc.metadata.get("source")
                or doc.metadata.get("file_path")
                or doc.metadata.get("path")
                or "未知来源"
            )
            score = doc.metadata.get("rerank_score", "")
            score_text = f" | 相关性分数：{score}" if score != "" else ""
            context += f"【资料{counter}】来源：{source}{score_text}\n内容：{doc.page_content}\n"

        return context

    @staticmethod
    def _max_rerank_score(context_docs: list[Document]) -> float:
        scores = [doc.metadata.get("rerank_score") for doc in context_docs]
        numeric_scores = [
            float(score) for score in scores if isinstance(score, (int, float))
        ]
        return max(numeric_scores, default=1.0)

    def summarize_with_docs(self, query: str, context_docs: list[Document]) -> str:
        if is_out_of_scope_query(query):
            return low_confidence_response()

        context = self.format_context(context_docs)
        with self._span("llm.generate") as span:
            answer = self.chain.invoke(
                {
                    "input": query,
                    "context": context,
                }
            )
            if span is not None:
                span.set_attribute("llm.status", "completed")
        threshold = chroma_conf.get("low_confidence_threshold", 0)
        if threshold and self._max_rerank_score(context_docs) < threshold:
            return f"知识库中没有找到足够可靠的依据，以下仅为低置信度参考：{answer}"
        return answer

    def rag_summarize_with_context(self, query: str) -> dict:
        context_docs = self.retriever_docs(query)
        answer = self.summarize_with_docs(query, context_docs)
        return {
            "query": query,
            "answer": answer,
            "documents": context_docs,
            "contexts": [doc.page_content for doc in context_docs],
        }

    def rag_summarize(self, query: str) -> str:
        context_docs = self.retriever_docs(query)
        return self.summarize_with_docs(query, context_docs)


if __name__ == "__main__":
    rag = RagSummarizeService()

    print(rag.rag_summarize("小户型适合哪些扫地机器人"))
