from __future__ import annotations

import unittest
from concurrent.futures import Future
from threading import Event
from typing import cast
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableLambda

from rag.rag_service import RagSummarizeService
from rag.vector_store import VectorStoreService
from src.app.observability.tracing import ApiTracer
from utils.config_handler import chroma_conf


class FakeRetriever:
    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.invoke_count = 0

    def invoke(self, query: str) -> list[Document]:
        self.invoke_count += 1
        return self.documents


class FakeVectorStore:
    def __init__(self) -> None:
        self.load_count = 0
        self.get_retriever_count = 0
        self.retriever = FakeRetriever(
            [Document(page_content="机器人无法连接 WiFi", metadata={})]
        )

    def load_document(self) -> None:
        self.load_count += 1

    def get_retriever(self) -> FakeRetriever:
        self.get_retriever_count += 1
        return self.retriever


class BlockingVectorStore(FakeVectorStore):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def load_document(self) -> None:
        self.load_count += 1
        self.started.set()
        self.release.wait(timeout=2)


class RagServiceInitializationTest(unittest.TestCase):
    def build_service(self, vector_store: FakeVectorStore) -> RagSummarizeService:
        fake_model: object = RunnableLambda(lambda _: "回答")
        return RagSummarizeService(
            print_prompts=False,
            vector_store=cast(VectorStoreService, vector_store),
            model=cast(BaseChatModel, fake_model),
        )

    def test_constructor_does_not_load_documents(self) -> None:
        vector_store = FakeVectorStore()

        self.build_service(vector_store)

        self.assertEqual(vector_store.load_count, 0)
        self.assertEqual(vector_store.get_retriever_count, 0)

    def test_retriever_docs_loads_documents_once(self) -> None:
        vector_store = FakeVectorStore()
        service = self.build_service(vector_store)

        with patch.dict(chroma_conf, {"rerank_enabled": False, "k": 2}):
            first = service.retriever_docs("WiFi")
            second = service.retriever_docs("WiFi")

        self.assertEqual(first, vector_store.retriever.documents)
        self.assertEqual(second, vector_store.retriever.documents)
        self.assertEqual(vector_store.load_count, 1)
        self.assertEqual(vector_store.get_retriever_count, 1)
        self.assertEqual(vector_store.retriever.invoke_count, 2)

    def test_retriever_docs_records_bounded_metrics(self) -> None:
        vector_store = FakeVectorStore()
        service = self.build_service(vector_store)

        with patch.dict(chroma_conf, {"rerank_enabled": False, "k": 2}):
            service.retriever_docs("WiFi")

        snapshot = service.metrics.snapshot()
        self.assertEqual(snapshot["retrievals"], 1)
        self.assertEqual(snapshot["failures"], 0)
        self.assertEqual(snapshot["empty_retrievals"], 0)
        self.assertEqual(snapshot["candidate_sum"], 1)
        service.close()

    def test_retriever_docs_records_safe_rag_spans(self) -> None:
        vector_store = FakeVectorStore()
        tracer = ApiTracer(max_spans=8)
        service = RagSummarizeService(
            print_prompts=False,
            vector_store=cast(VectorStoreService, vector_store),
            model=cast(BaseChatModel, RunnableLambda(lambda _: "回答")),
            tracer=tracer,
        )

        with patch.dict(chroma_conf, {"rerank_enabled": False, "k": 2}):
            service.retriever_docs("private query")

        names = [item["name"] for item in tracer.exporter.snapshot()]
        self.assertIn("retrieval.dense", names)
        self.assertNotIn("private query", str(tracer.exporter.snapshot()))
        service.close()
        tracer.close()

    def test_background_loading_is_single_flight(self) -> None:
        vector_store = BlockingVectorStore()
        service = self.build_service(vector_store)

        first = service.start_document_loading()
        second = service.start_document_loading()

        self.assertIsInstance(first, Future)
        self.assertIs(first, second)
        self.assertTrue(vector_store.started.wait(timeout=1))
        vector_store.release.set()
        assert first is not None
        first.result(timeout=1)
        self.assertEqual(vector_store.load_count, 1)
        service.close()

    def test_background_loading_timeout_is_reported(self) -> None:
        vector_store = BlockingVectorStore()
        service = RagSummarizeService(
            print_prompts=False,
            vector_store=cast(VectorStoreService, vector_store),
            model=cast(BaseChatModel, RunnableLambda(lambda _: "回答")),
            document_load_timeout_seconds=0.01,
        )

        with self.assertRaisesRegex(TimeoutError, "configured timeout"):
            service.ensure_documents_loaded()
        vector_store.release.set()
        service.close()

    def test_readiness_is_non_blocking_and_turns_ready_after_loading(self) -> None:
        vector_store = BlockingVectorStore()
        service = self.build_service(vector_store)

        self.assertFalse(service.check_ready())
        future = service.start_document_loading()
        self.assertFalse(service.check_ready())
        vector_store.release.set()
        assert future is not None
        future.result(timeout=1)

        self.assertTrue(service.check_ready())
        service.close()

    def test_readiness_fails_closed_when_loading_errors(self) -> None:
        class FailingVectorStore(FakeVectorStore):
            def load_document(self) -> None:
                raise RuntimeError("private loading detail")

        service = self.build_service(FailingVectorStore())
        future = service.start_document_loading()
        assert future is not None
        with self.assertRaisesRegex(RuntimeError, "private loading detail"):
            future.result(timeout=1)

        self.assertFalse(service.check_ready())
        service.close()


if __name__ == "__main__":
    unittest.main()
