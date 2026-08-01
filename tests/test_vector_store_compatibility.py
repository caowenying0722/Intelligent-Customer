from __future__ import annotations

import os
import unittest
import uuid
from unittest.mock import patch

from langchain_core.documents import Document

from evaluation.hash_embeddings import HashNgramEmbeddings
from rag.vector_store import VectorStoreService
from utils.config_handler import chroma_conf


class VectorStoreCompatibilityTest(unittest.TestCase):
    def test_chroma_round_trip_with_local_embeddings(self) -> None:
        collection_name = f"compat-{uuid.uuid4().hex}"

        with (
            patch.dict(os.environ, {"ANONYMIZED_TELEMETRY": "False"}),
            patch.dict(
                chroma_conf,
                {
                    "collection_name": collection_name,
                    "persist_directory": None,
                    "retrieval_type": "vector",
                    "candidate_k": 2,
                    "k": 2,
                },
            ),
        ):
            service = VectorStoreService(
                embedding_model=HashNgramEmbeddings(dimensions=32)
            )
            documents = [
                Document(
                    page_content="机器人无法连接 WiFi，需要重启路由器。",
                    metadata={"source": "compat-fixture"},
                )
            ]

            ids = service.vector_store.add_documents(documents)
            stored_documents = service._get_all_documents()
            results = service.get_retriever().invoke("WiFi 连接")
            service.vector_store.delete_collection()

        self.assertEqual(len(ids), 1)
        self.assertEqual(len(stored_documents), 1)
        self.assertEqual(stored_documents[0].metadata["source"], "compat-fixture")
        self.assertEqual(results[0].metadata["source"], "compat-fixture")


if __name__ == "__main__":
    unittest.main()
