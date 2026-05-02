import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pymilvus import MilvusClient

from app.core.config import get_settings

logger = logging.getLogger(__name__)
from app.models.document import Document, DocumentStatus, Chunk
from app.models.knowledge_base import KnowledgeBase
from app.services.document_loader import parse_document, split_documents
from app.services.embedding_service import get_embedding_model
from app.services.bm25_index import rebuild_index, invalidate_index

settings = get_settings()


class IngestionService:
    """文档入库流水线"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embeddings = get_embedding_model()
        self.milvus = MilvusClient(host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)

    async def process_document(self, document_id: int):
        """处理单篇文档：解析 → 分块 → 向量化 → 写入 Milvus"""
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        result = await self.db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.knowledge_base_id))
        kb = result.scalar_one_or_none()
        if not kb:
            return

        try:
            # 1. 解析文档
            logger.info("文档入库开始: doc_id=%d, file=%s", document_id, doc.file_path)
            doc.status = DocumentStatus.PARSING
            await self.db.commit()

            langchain_docs, _ = parse_document(doc.file_path)
            logger.info("文档解析完成: doc_id=%d, 页数=%d", document_id, len(langchain_docs))

            # 2. 分块
            doc.status = DocumentStatus.CHUNKING
            await self.db.commit()

            chunks = split_documents(langchain_docs)
            texts = [c.page_content for c in chunks]
            logger.info("文档分块完成: doc_id=%d, 块数=%d", document_id, len(chunks))

            # 3. 向量化
            doc.status = DocumentStatus.EMBEDDING
            await self.db.commit()

            vectors = await self.embeddings.aembed_documents(texts)
            logger.info("向量化完成: doc_id=%d, 向量数=%d", document_id, len(vectors))

            # 4. 写入 Milvus
            milvus_data = [
                {"vector": vec, "text": texts[i], "document_id": doc.id, "knowledge_base_id": kb.id}
                for i, vec in enumerate(vectors)
            ]
            insert_result = self.milvus.insert(collection_name=kb.milvus_collection, data=milvus_data)
            milvus_ids = insert_result.get("ids", [])

            # 5. 写入 Chunk 记录到 MySQL
            for i, (ldoc, mid) in enumerate(zip(chunks, milvus_ids)):
                import json
                self.db.add(Chunk(
                    document_id=doc.id,
                    knowledge_base_id=kb.id,
                    content=texts[i],
                    metadata_json=json.dumps(ldoc.metadata, ensure_ascii=False),
                    milvus_pk=str(mid),
                    chunk_index=i,
                ))

            # 6. 重建 BM25 索引
            all_chunks_result = await self.db.execute(
                select(Chunk.id, Chunk.content).where(Chunk.knowledge_base_id == kb.id)
            )
            all_rows = all_chunks_result.all()
            if all_rows:
                rebuild_index(kb.id, [r[0] for r in all_rows], [r[1] for r in all_rows])

            # 7. 更新统计
            doc.status = DocumentStatus.INDEXED
            doc.chunk_count = len(chunks)

            count_result = await self.db.execute(
                select(func.count()).select_from(Document).where(
                    Document.knowledge_base_id == kb.id,
                    Document.status == DocumentStatus.INDEXED,
                )
            )
            kb.document_count = count_result.scalar() or 0

            chunk_count_result = await self.db.execute(
                select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                    Document.knowledge_base_id == kb.id,
                    Document.status == DocumentStatus.INDEXED,
                )
            )
            kb.chunk_count = chunk_count_result.scalar() or 0

            await self.db.commit()
            logger.info("文档入库完成: doc_id=%d, chunks=%d, kb=%s", document_id, len(chunks), kb.name)

        except Exception as e:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            logger.error("文档入库失败: doc_id=%d, error=%s", document_id, str(e))
            await self.db.commit()
            raise
