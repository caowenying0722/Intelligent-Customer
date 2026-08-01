from __future__ import annotations

import unittest
from typing import cast
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableLambda

from rag.rag_service import RagSummarizeService
from rag.vector_store import VectorStoreService
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


if __name__ == "__main__":
    unittest.main()
