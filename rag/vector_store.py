import os

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from model.factory import get_embedding_model
from rag.simple_bm25 import RRFHybridRetriever, SimpleBM25Retriever, WeightedHybridRetriever
from rag.retrieval_types import build_chroma_scope_filter
from rag.tokenization import cjk_bm25_tokenizer
from utils.config_handler import chroma_conf
from utils.file_handler import (
    get_file_md5_hex,
    listdir_with_allowed_type,
    pdf_loader,
    txt_loader,
)
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class VectorStoreService:
    def __init__(self, embedding_model: Embeddings | None = None):
        if chroma_conf.get("storage_mode", "embedded") != "embedded":
            raise RuntimeError("only embedded Chroma storage mode is supported")
        self.vector_store = Chroma(
            collection_name=chroma_conf["collection_name"],
            embedding_function=(
                embedding_model
                if embedding_model is not None
                else get_embedding_model()
            ),
            persist_directory=chroma_conf["persist_directory"],
        )

        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=chroma_conf["separators"],
            length_function=len,
        )

    def _get_all_documents(
        self, *, tenant_id: str | None = None, index_version: str | None = None
    ) -> list[Document]:
        """从 Chroma 向量库中获取所有已存储的文档，用于构建 BM25 检索器"""
        scope_filter = build_chroma_scope_filter(
            tenant_id=tenant_id, index_version=index_version
        )
        get_kwargs: dict[str, object] = {"include": ["documents", "metadatas"]}
        if scope_filter is not None:
            get_kwargs["where"] = scope_filter
        chroma_data = self.vector_store.get(**get_kwargs)
        documents = []
        for content, metadata in zip(
            chroma_data["documents"], chroma_data["metadatas"]
        ):
            documents.append(Document(page_content=content, metadata=metadata))
        return documents

    def get_retriever(
        self, *, tenant_id: str | None = None, index_version: str | None = None
    ):
        scope_filter = build_chroma_scope_filter(
            tenant_id=tenant_id, index_version=index_version
        )
        retrieval_k = chroma_conf.get("candidate_k", chroma_conf["k"])
        search_kwargs: dict[str, object] = {"k": retrieval_k}
        if scope_filter is not None:
            search_kwargs["filter"] = scope_filter
        vector_retriever = self.vector_store.as_retriever(
            search_kwargs=search_kwargs
        )

        if chroma_conf.get("retrieval_type") == "hybrid":
            all_docs = self._get_all_documents(
                tenant_id=tenant_id, index_version=index_version
            )
            if not all_docs:
                logger.warning("[混合检索]向量库中暂无文档，降级为纯向量检索")
                return vector_retriever

            bm25_retriever = SimpleBM25Retriever(
                all_docs,
                preprocess_func=cjk_bm25_tokenizer,
                k=retrieval_k,
            )

            if chroma_conf.get("fusion_strategy", "weighted") == "rrf":
                return RRFHybridRetriever(
                    vector_retriever=vector_retriever,
                    keyword_retriever=bm25_retriever,
                    k=retrieval_k,
                    fusion_k=chroma_conf.get("rrf_k", 60),
                )
            return WeightedHybridRetriever(
                vector_retriever=vector_retriever,
                keyword_retriever=bm25_retriever,
                vector_weight=chroma_conf.get("vector_weight", 0.6),
                keyword_weight=chroma_conf.get("bm25_weight", 0.4),
                k=retrieval_k,
            )

        return vector_retriever

    def load_document(self):
        """
        从数据文件夹内读取数据文件，转为向量存入向量库
        要计算文件的MD5做去重
        :return: None
        """

        def check_md5_hex(md5_for_check: str):
            if not os.path.exists(get_abs_path(chroma_conf["md5_hex_store"])):
                # 创建文件
                open(
                    get_abs_path(chroma_conf["md5_hex_store"]), "w", encoding="utf-8"
                ).close()
                return False  # md5 没处理过

            with open(
                get_abs_path(chroma_conf["md5_hex_store"]), "r", encoding="utf-8"
            ) as f:
                for line in f:
                    line = line.strip()
                    if line == md5_for_check:
                        return True  # md5 处理过

                return False  # md5 没处理过

        def save_md5_hex(md5_for_check: str):
            with open(
                get_abs_path(chroma_conf["md5_hex_store"]), "a", encoding="utf-8"
            ) as f:
                f.write(md5_for_check + "\n")

        def get_file_documents(read_path: str):
            if read_path.endswith("txt"):
                return txt_loader(read_path)

            if read_path.endswith("pdf"):
                return pdf_loader(read_path)

            return []

        allowed_files_path: list[str] = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )

        for path in allowed_files_path:
            # 获取文件的MD5
            md5_hex = get_file_md5_hex(path)

            if check_md5_hex(md5_hex):
                logger.info(f"[加载知识库]{path}内容已经存在知识库内，跳过")
                continue

            try:
                documents: list[Document] = get_file_documents(path)

                if not documents:
                    logger.warning(f"[加载知识库]{path}内没有有效文本内容，跳过")
                    continue

                split_document: list[Document] = self.spliter.split_documents(documents)

                if not split_document:
                    logger.warning(f"[加载知识库]{path}分片后没有有效文本内容，跳过")
                    continue

                # 将内容存入向量库
                self.vector_store.add_documents(split_document)

                # 记录这个已经处理好的文件的md5，避免下次重复加载
                save_md5_hex(md5_hex)

                logger.info(f"[加载知识库]{path} 内容加载成功")
            except Exception as e:  # noqa: BLE001 - isolate each ingestion file.
                # exc_info为True会记录详细的报错堆栈，如果为False仅记录报错信息本身
                logger.error(f"[加载知识库]{path}加载失败：{e!s}", exc_info=True)
                continue


if __name__ == "__main__":
    vs = VectorStoreService()

    vs.load_document()

    retriever = vs.get_retriever()

    res = retriever.invoke("迷路")
    for r in res:
        print(r.page_content)
        print("-" * 20)
