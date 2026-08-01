
"""
总结服务类：用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型总结回复
"""
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from rag.vector_store import VectorStoreService
from rag.guardrails import is_out_of_scope_query, low_confidence_response
from rag.reranker import LightweightEvidenceReranker
from utils.prompt_loader import load_rag_prompts
from langchain_core.prompts import PromptTemplate
from model.factory import chat_model
from utils.config_handler import chroma_conf


def print_prompt(prompt):
    print("="*20)
    print(prompt.to_string())
    print("="*20)
    return prompt


class RagSummarizeService(object):
    def __init__(self, print_prompts: bool = True):
        self.vector_store = VectorStoreService()
        self.vector_store.load_document()
        self.retriever = self.vector_store.get_retriever()
        self.reranker = LightweightEvidenceReranker()
        self.prompt_text = load_rag_prompts()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        self.print_prompts = print_prompts
        self.chain = self._init_chain()

    def _init_chain(self):
        if self.print_prompts:
            return self.prompt_template | print_prompt | self.model | StrOutputParser()

        return self.prompt_template | self.model | StrOutputParser()

    def retriever_docs(self, query: str) -> list[Document]:
        docs = self.retriever.invoke(query)
        if chroma_conf.get("rerank_enabled", False):
            return self.reranker.rerank(
                query=query,
                docs=docs,
                top_k=chroma_conf.get("rerank_top_k", chroma_conf["k"]),
            )
        return docs[: chroma_conf["k"]]

    @staticmethod
    def format_context(context_docs: list[Document]) -> str:
        context = ""
        counter = 0
        for doc in context_docs:
            counter += 1
            source = doc.metadata.get("source") or doc.metadata.get("file_path") or doc.metadata.get("path") or "未知来源"
            score = doc.metadata.get("rerank_score", "")
            score_text = f" | 相关性分数：{score}" if score != "" else ""
            context += f"【资料{counter}】来源：{source}{score_text}\n内容：{doc.page_content}\n"

        return context

    @staticmethod
    def _max_rerank_score(context_docs: list[Document]) -> float:
        scores = [doc.metadata.get("rerank_score") for doc in context_docs]
        numeric_scores = [float(score) for score in scores if isinstance(score, (int, float))]
        return max(numeric_scores, default=1.0)

    def summarize_with_docs(self, query: str, context_docs: list[Document]) -> str:
        if is_out_of_scope_query(query):
            return low_confidence_response()

        context = self.format_context(context_docs)
        answer = self.chain.invoke(
            {
                "input": query,
                "context": context,
            }
        )
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


if __name__ == '__main__':
    rag = RagSummarizeService()

    print(rag.rag_summarize("小户型适合哪些扫地机器人"))
