from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter

from model.factory import chat_model
from rag.reranker import LightweightEvidenceReranker
from rag.simple_bm25 import SimpleBM25Retriever
from rag.tokenization import cjk_bm25_tokenizer
from utils.config_handler import chroma_conf
from utils.file_handler import listdir_with_allowed_type, pdf_loader, txt_loader
from utils.path_tool import get_abs_path
from utils.prompt_loader import load_rag_prompts


class BM25RagEvaluationService:
    def __init__(self):
        self.documents = self._load_documents()
        retrieval_k = chroma_conf.get("candidate_k", chroma_conf["k"])
        self.retriever = SimpleBM25Retriever(
            self.documents,
            preprocess_func=cjk_bm25_tokenizer,
            k=retrieval_k,
        )
        self.reranker = LightweightEvidenceReranker()
        self.prompt_template = PromptTemplate.from_template(load_rag_prompts())
        self.chain = self.prompt_template | chat_model | StrOutputParser()

    def _load_documents(self) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=chroma_conf["separators"],
            length_function=len,
        )
        file_paths = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )

        documents: list[Document] = []
        for file_path in file_paths:
            if file_path.endswith("txt"):
                documents.extend(txt_loader(file_path))
            elif file_path.endswith("pdf"):
                documents.extend(pdf_loader(file_path))

        return splitter.split_documents(documents)

    @staticmethod
    def format_context(context_docs: list[Document]) -> str:
        context = ""
        for index, doc in enumerate(context_docs, start=1):
            context += f"【参考资料{index}】: 参考资料：{doc.page_content} | 参考元数据：{doc.metadata}\n"
        return context

    def retriever_docs(self, query: str) -> list[Document]:
        docs = self.retriever.invoke(query)
        if chroma_conf.get("rerank_enabled", False):
            return self.reranker.rerank(
                query=query,
                docs=docs,
                top_k=chroma_conf.get("rerank_top_k", chroma_conf["k"]),
            )
        return docs[: chroma_conf["k"]]

    def summarize_with_docs(self, query: str, context_docs: list[Document]) -> str:
        return self.chain.invoke(
            {
                "input": query,
                "context": self.format_context(context_docs),
            }
        )
